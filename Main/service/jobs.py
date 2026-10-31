"""User-owned media uploads and downloads."""
import hashlib
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from .auth import current_user
from .database import connect

router = APIRouter(tags=["jobs"])
# Single source of truth for upload limits; the UI reads these from GET /jobs/limits.
ALLOWED = (".mp3", ".wav", ".m4a", ".mp4", ".mov")
DEFAULT_MAX_MB = 500  # the MAX_UPLOAD_MB environment variable overrides this
FORMATS = ", ".join(ALLOWED)
PUBLIC_COLUMNS = "job_id, filename, size_bytes, status, uploaded_at"
RECENT_SECONDS = 60 * 60 * 24  # finished jobs stay in /jobs/activity this long, for "finished while you were away"
STALLED_SECONDS = 180  # one Whisper window on a slow CPU can legitimately take a minute or more
MIN_ETA_ELAPSED = 15  # earlier estimates swing too much to be useful

def owned_job(db, job_id, user_id):
    row = db.execute("SELECT * FROM jobs WHERE job_id=? AND user_id=?", (str(job_id), user_id)).fetchone()
    if row is None:
        raise HTTPException(404, "job not found")
    return row

def progress_fields(row, now):
    """Turn a jobs + job_progress row into what the progress UI shows."""
    status = row["status"]
    fields = dict(stage="preparing" if status == "processing" else status, percent=100 if status == "done" else None, eta_seconds=None, stalled=False)
    # jobs.status wins over job_progress, so an old row can't make a requeued job look active.
    if status != "processing" or row["updated_at"] is None:
        return fields
    since_update = max(0, now - row["updated_at"])
    fields["stalled"] = since_update > STALLED_SECONDS
    if row["stage"] != "transcribing":
        return fields
    fields["stage"] = "transcribing"
    duration = row["duration_seconds"]
    if not duration:
        return fields
    processed = min(row["processed_seconds"], duration)
    # 100 is reserved for status "done", so the bar never sits full while work continues.
    fields["percent"] = min(99, int(processed / duration * 100))
    elapsed = row["updated_at"] - row["started_at"]
    if processed > 0 and elapsed >= MIN_ETA_ELAPSED:
        fields["eta_seconds"] = max(0, round(elapsed / processed * (duration - processed) - since_update))
    return fields

def fingerprint_existing_uploads(data_dir):
    """Hash uploads stored before duplicate detection existed, or by code without it."""
    with connect(data_dir) as db:
        missing = db.execute("SELECT j.job_id, j.user_id, j.storage_name FROM jobs j LEFT JOIN upload_hashes h ON h.job_id=j.job_id WHERE h.job_id IS NULL").fetchall()
        for row in missing:
            path = data_dir / "uploads" / row["storage_name"]
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stored:
                    while chunk := stored.read(1024 * 1024):
                        digest.update(chunk)
                db.execute("INSERT INTO upload_hashes VALUES (?, ?, ?)", (row["job_id"], row["user_id"], digest.hexdigest()))

def checked_extension(filename):
    ext = Path(filename or "").suffix.lower()
    if not ext:
        raise HTTPException(400, f"The file has no extension. Rename it to end in one of: {FORMATS}.")
    if ext not in ALLOWED:
        raise HTTPException(400, f"{ext} files are not supported. Upload one of: {FORMATS}. Try converting the file to {ALLOWED[0]}.")
    return ext

@router.post("/jobs", status_code=201)
async def create_job(request: Request, file: UploadFile, user=Depends(current_user)):
    ext = checked_extension(file.filename)
    uploads = request.app.state.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    job_id = str(uuid.uuid4())
    storage_name = f"{job_id}{ext}"
    destination = uploads / storage_name
    size = 0
    digest = hashlib.sha256()
    try:
        with destination.open("xb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > request.app.state.max_bytes:
                    limit_mb = request.app.state.max_bytes / 1024 ** 2
                    raise HTTPException(413, f"The file is larger than the {limit_mb:g} MB limit. Trim or compress the recording and try again.")
                out.write(chunk)
                digest.update(chunk)
        if size == 0:
            raise HTTPException(400, "The file is empty. Choose a file that contains audio or video.")
        meta = dict(job_id=job_id, filename=(file.filename or "upload").replace("\\", "/").split("/")[-1], size_bytes=size, status="queued", uploaded_at=time.time())
        sha256 = digest.hexdigest()
        with connect(request.app.state.data_dir) as db:
            # Lock before checking so two simultaneous uploads of the same file cannot both pass.
            db.execute("BEGIN IMMEDIATE")
            matches = db.execute("SELECT j.filename, j.storage_name FROM upload_hashes h JOIN jobs j ON j.job_id=h.job_id WHERE h.user_id=? AND h.sha256=?", (user["id"], sha256)).fetchall()
            # Only a copy still on disk counts, so a record whose file was lost cannot block re-uploading it.
            duplicate = next((match for match in matches if (uploads / match["storage_name"]).is_file()), None)
            if duplicate:
                raise HTTPException(409, f'You already uploaded this file as "{duplicate["filename"]}". Delete that upload first if you want to replace it.')
            db.execute("INSERT INTO jobs (job_id, user_id, filename, storage_name, size_bytes, status, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (job_id, user["id"], meta["filename"], storage_name, size, meta["status"], meta["uploaded_at"]))
            db.execute("INSERT INTO upload_hashes VALUES (?, ?, ?)", (job_id, user["id"], sha256))
        return meta
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await file.close()

# Registered before /jobs/{job_id} so "limits" is not parsed as a job ID.
@router.get("/jobs/limits")
def upload_limits(request: Request):
    return {"extensions": list(ALLOWED), "max_bytes": request.app.state.max_bytes}

@router.get("/jobs/activity")
def job_activity(request: Request, user=Depends(current_user)):
    """The user's unfinished jobs and recently finished ones, for the progress panel on every page."""
    now = time.time()
    jobs = []
    with connect(request.app.state.data_dir) as db:
        rows = db.execute("""SELECT j.job_id, j.filename, j.status, j.uploaded_at, p.stage, p.duration_seconds, p.processed_seconds, p.started_at, p.updated_at
            FROM jobs j LEFT JOIN job_progress p ON p.job_id=j.job_id
            WHERE j.user_id=? AND (j.status IN ('queued', 'processing') OR (j.status IN ('done', 'failed') AND p.updated_at>?))
            ORDER BY j.uploaded_at DESC, j.job_id LIMIT 100""", (user["id"], now - RECENT_SECONDS)).fetchall()
        for row in rows:
            ahead = None
            if row["status"] == "queued":
                # The queue is shared between accounts. Only a count is exposed, never other users' jobs.
                ahead = db.execute("SELECT COUNT(*) FROM jobs WHERE status='processing' OR (status='queued' AND uploaded_at<?)", (row["uploaded_at"],)).fetchone()[0]
            jobs.append({"job_id": row["job_id"], "filename": row["filename"], "status": row["status"], "jobs_ahead": ahead,
                         "finished_at": row["updated_at"] if row["status"] in ("done", "failed") else None} | progress_fields(row, now))
    return {"jobs": jobs}

@router.get("/jobs")
def list_jobs(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(current_user)):
    with connect(request.app.state.data_dir) as db:
        rows = db.execute(f"SELECT {PUBLIC_COLUMNS}, EXISTS(SELECT 1 FROM transcripts t WHERE t.job_id=jobs.job_id) AS transcript_ready FROM jobs WHERE user_id=? ORDER BY uploaded_at DESC, job_id LIMIT ? OFFSET ?", (user["id"], limit, offset))
        return [dict(row) | {"transcript_ready": bool(row["transcript_ready"])} for row in rows]

@router.get("/jobs/{job_id}")
def get_job(job_id: uuid.UUID, request: Request, user=Depends(current_user)):
    with connect(request.app.state.data_dir) as db:
        row = owned_job(db, job_id, user["id"])
        return {key: row[key] for key in PUBLIC_COLUMNS.split(", ")}

@router.get("/jobs/{job_id}/file")
def download(job_id: uuid.UUID, request: Request, user=Depends(current_user)):
    with connect(request.app.state.data_dir) as db:
        row = owned_job(db, job_id, user["id"])
    path = request.app.state.data_dir / "uploads" / row["storage_name"]
    if not path.is_file():
        raise HTTPException(404, "file not found")
    return FileResponse(path, filename=row["filename"], media_type="application/octet-stream")

@router.get("/jobs/{job_id}/transcript.txt")
def download_transcript(job_id: uuid.UUID, request: Request, user=Depends(current_user)):
    """The newest transcript for one of the user's jobs, as a .txt download named after the upload."""
    with connect(request.app.state.data_dir) as db:
        job = owned_job(db, job_id, user["id"])
        row = db.execute("SELECT text FROM transcripts WHERE job_id=? ORDER BY created_at DESC LIMIT 1", (str(job_id),)).fetchone()
    if row is None:
        raise HTTPException(404, "The transcript isn't ready yet. Try again once transcription finishes.")
    name = f"{Path(job['filename']).stem or 'transcript'}.txt"
    return Response(row["text"].strip() + "\n", media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(name)}"})

def remove_files(uploads, job_id):
    """Delete the upload and any sidecar files (e.g. <job_id>.transcript.json)."""
    for path in uploads.glob(f"{job_id}.*"):
        path.unlink(missing_ok=True)

@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: uuid.UUID, request: Request, user=Depends(current_user)):
    with connect(request.app.state.data_dir) as db:
        owned_job(db, job_id, user["id"])
        db.execute("DELETE FROM jobs WHERE job_id=? AND user_id=?", (str(job_id), user["id"]))
        try:
            remove_files(request.app.state.data_dir / "uploads", job_id)
        except OSError:
            # Raising inside the transaction rolls back, so the job stays listed and can be retried.
            raise HTTPException(409, "file is in use; try again")

@router.delete("/jobs", status_code=204)
def delete_all_jobs(request: Request, user=Depends(current_user)):
    uploads = request.app.state.data_dir / "uploads"
    failed = 0
    with connect(request.app.state.data_dir) as db:
        for row in db.execute("SELECT job_id FROM jobs WHERE user_id=?", (user["id"],)).fetchall():
            try:
                remove_files(uploads, row["job_id"])
            except OSError:
                failed += 1
                continue
            db.execute("DELETE FROM jobs WHERE job_id=? AND user_id=?", (row["job_id"], user["id"]))
    if failed:
        raise HTTPException(409, f"{failed} file(s) are in use and were not deleted; try again")
