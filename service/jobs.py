"""User-owned media uploads and downloads."""
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from .auth import current_user
from .database import connect

router = APIRouter(tags=["jobs"])
# Single source of truth for upload limits; the UI reads these from GET /jobs/limits.
ALLOWED = (".mp3", ".wav", ".m4a", ".mp4", ".mov")
DEFAULT_MAX_MB = 500  # the MAX_UPLOAD_MB environment variable overrides this
FORMATS = ", ".join(ALLOWED)
PUBLIC_COLUMNS = "job_id, filename, size_bytes, status, uploaded_at"

def owned_job(db, job_id, user_id):
    row = db.execute("SELECT * FROM jobs WHERE job_id=? AND user_id=?", (str(job_id), user_id)).fetchone()
    if row is None:
        raise HTTPException(404, "job not found")
    return row

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
    try:
        with destination.open("xb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > request.app.state.max_bytes:
                    limit_mb = request.app.state.max_bytes / 1024 ** 2
                    raise HTTPException(413, f"The file is larger than the {limit_mb:g} MB limit. Trim or compress the recording and try again.")
                out.write(chunk)
        if size == 0:
            raise HTTPException(400, "The file is empty. Choose a file that contains audio or video.")
        meta = dict(job_id=job_id, filename=(file.filename or "upload").replace("\\", "/").split("/")[-1], size_bytes=size, status="stored", uploaded_at=time.time())
        with connect(request.app.state.data_dir) as db:
            db.execute("INSERT INTO jobs VALUES (?, ?, ?, ?, ?, ?, ?)", (job_id, user["id"], meta["filename"], storage_name, size, meta["status"], meta["uploaded_at"]))
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

@router.get("/jobs")
def list_jobs(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(current_user)):
    with connect(request.app.state.data_dir) as db:
        return [dict(row) for row in db.execute(f"SELECT {PUBLIC_COLUMNS} FROM jobs WHERE user_id=? ORDER BY uploaded_at DESC, job_id LIMIT ? OFFSET ?", (user["id"], limit, offset))]

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
