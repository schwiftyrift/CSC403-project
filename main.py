import json
import mimetypes
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
ALLOWED = {".mp3", ".wav", ".m4a", ".mp4", ".mov"}
MAX_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "500")) * 1024 * 1024

app = FastAPI(title="Transcript Service", version="0.1.0")


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@app.exception_handler(RequestValidationError)
async def bad_request(request, exc):
    return error(400, "invalid request")


@app.get("/app", summary="Check that the service is running")
def root():
    """Expects nothing. Returns the service name and status."""
    return {"service": "Transcript Service", "status": "running"}


@app.post("/jobs", status_code=201, summary="Upload a file",
          responses={400: {"description": "missing file or unsupported type"},
                     413: {"description": "file too large"}})
async def create_job(file: UploadFile):
    """Expects a multipart `file` (mp3, wav, m4a, mp4, mov). Stores it and returns a job id."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        return error(400, "unsupported file type")

    uploads = DATA_DIR / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    job_id = str(uuid.uuid4())
    dest = uploads / f"{job_id}{ext}"

    size = 0
    with dest.open("wb") as out:
        while chunk := await file.read(1024 * 1024):  # stream to disk, 1 MB at a time
            size += len(chunk)
            if size > MAX_BYTES:
                out.close()
                dest.unlink(missing_ok=True)
                return error(413, "file too large")
            out.write(chunk)

    meta = {"job_id": job_id, "filename": Path(file.filename).name, "size_bytes": size,
            "status": "stored", "uploaded_at": time.time()}
    (uploads / f"{job_id}.json").write_text(json.dumps(meta))
    return meta


@app.get("/jobs/{job_id}", summary="Get an upload's record",
         responses={400: {"description": "job_id is not a UUID"}, 404: {"description": "no such job"}})
def get_job(job_id: str):
    """Expects a job id (UUID). Returns the stored file's record."""
    try:
        uuid.UUID(job_id)
    except ValueError:
        return error(400, "job_id must be a valid UUID")
    meta_file = DATA_DIR / "uploads" / f"{job_id}.json"
    if not meta_file.exists():
        return error(404, "job not found")
    return json.loads(meta_file.read_text())


def find_job_file(job_id: str, suffix: str) -> Path | None:
    """Returns data/uploads/<job_id><suffix> if job_id is a UUID and the file exists."""
    try:
        uuid.UUID(job_id)
    except ValueError:
        return None
    path = DATA_DIR / "uploads" / f"{job_id}{suffix}"
    return path if path.is_file() else None


@app.get("/jobs/{job_id}/media", summary="Stream an upload's audio/video",
         responses={404: {"description": "no such job"}})
def get_media(job_id: str):
    """Expects a job id. Returns the uploaded file inline, with range support so players can seek."""
    for ext in ALLOWED:
        if path := find_job_file(job_id, ext):
            return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")
    return error(404, "job not found")


@app.get("/jobs/{job_id}/transcript", summary="Get an upload's timestamped transcript",
         responses={404: {"description": "no such job, or not transcribed yet"}})
def get_transcript(job_id: str):
    """Expects a job id. Returns {"segments": [{"start", "end", "text"}]} with times in seconds.

    The transcriber saves Whisper's result["segments"] to data/uploads/<job_id>.transcript.json.
    """
    if not find_job_file(job_id, ".json"):
        return error(404, "job not found")
    path = find_job_file(job_id, ".transcript.json")
    if not path:
        return error(404, "transcript not ready")
    segments = json.loads(path.read_text())["segments"]
    return {"segments": [{"start": s["start"], "end": s["end"], "text": s["text"].strip()} for s in segments]}


# The upload page, served at /app/ (only if the static folder exists)
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")