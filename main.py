import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

app = FastAPI(title="Transcript Service", version="0.1.0")

ALLOWED = {".mp3", ".wav", ".m4a", ".mp4", ".mov"}
jobs = {}  # job_id -> {"filename": ..., "status": ...}  (in memory for now)


def error(status: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": message})


@app.exception_handler(RequestValidationError)
async def bad_request(request, exc):
    return error(400, "invalid request")


@app.get("/", summary="Check that the service is running")
def root():
    """Expects nothing. Returns the service name and status."""
    return {"service": "Transcript Service", "status": "running"}


@app.post("/jobs", status_code=202, summary="Start a transcription job",
          responses={400: {"description": "missing file or unsupported file type"}})
async def create_job(file: UploadFile):
    """Expects a multipart `file` (mp3, wav, m4a, mp4, mov). Returns a job id."""
    if Path(file.filename or "").suffix.lower() not in ALLOWED:
        return error(400, "unsupported file type")
    job_id = str(uuid.uuid4())
    jobs[job_id] = {"filename": file.filename, "status": "queued"}  # no transcription yet
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}", summary="Get a job's status",
         responses={404: {"description": "no job with that id"}})
def get_job(job_id: str):
    """Expects a job id. Returns the job's filename and status."""
    if job_id not in jobs:
        return error(404, "job not found")
    return {"job_id": job_id, **jobs[job_id]}
