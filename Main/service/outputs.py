"""US-24: saved output selections, generation requests, and selected-output downloads."""
import io
import json
import time
import uuid
from pathlib import Path

import docx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from .auth import current_user
from .database import connect
from .jobs import attachment, newest_transcript, owned_job
from .transcript_doc import DOCX_TYPE, clean, plain_title_style

router = APIRouter(tags=["outputs"])
CONTENT_TYPES = {"general", "lecture", "video", "notes"}
OUTPUT_FORMATS = {"summary", "topics", "study_guide"}


class Preferences(BaseModel):
    content_type: str = "general"
    formats: list[str] = Field(default_factory=list, max_length=3)


def validate_preferences(content_type, formats):
    if content_type not in CONTENT_TYPES or any(f not in OUTPUT_FORMATS for f in formats):
        raise HTTPException(400, "Choose a supported content type and output format.")


@router.get("/jobs/{job_id}/output-preferences")
def get_preferences(job_id: uuid.UUID, request: Request, user=Depends(current_user)):
    with connect(request.app.state.data_dir) as db:
        owned_job(db, job_id, user["id"])
        row = db.execute("SELECT content_type, formats FROM output_preferences WHERE job_id=?", (str(job_id),)).fetchone()
    return {"content_type": row["content_type"], "formats": json.loads(row["formats"])} if row else {"content_type": "general", "formats": []}


@router.put("/jobs/{job_id}/output-preferences")
def put_preferences(job_id: uuid.UUID, body: Preferences, request: Request, user=Depends(current_user)):
    validate_preferences(body.content_type, body.formats)
    with connect(request.app.state.data_dir) as db:
        owned_job(db, job_id, user["id"])
        db.execute("INSERT INTO output_preferences VALUES (?, ?, ?) ON CONFLICT(job_id) DO UPDATE SET content_type=excluded.content_type, formats=excluded.formats",
                   (str(job_id), body.content_type, json.dumps(list(dict.fromkeys(body.formats)))))
    return body.model_dump()


@router.get("/jobs/{job_id}/outputs")
def list_outputs(job_id: uuid.UUID, request: Request, user=Depends(current_user)):
    with connect(request.app.state.data_dir) as db:
        _, transcript = newest_transcript(db, job_id, user["id"])
        return [dict(row) for row in db.execute("SELECT format, status, text, error FROM styled_outputs WHERE transcript_id=?", (transcript["id"],))]


@router.post("/jobs/{job_id}/outputs/{format}", status_code=202)
def generate_output(job_id: uuid.UUID, format: str, request: Request, user=Depends(current_user)):
    if format not in OUTPUT_FORMATS:
        raise HTTPException(400, "Unsupported output format.")
    with connect(request.app.state.data_dir) as db:
        _, transcript = newest_transcript(db, job_id, user["id"])
        if not transcript["text"].strip():
            raise HTTPException(409, "No speech was found, so there is no study material to generate.")
        db.execute("INSERT INTO styled_outputs (transcript_id, format, status, updated_at) VALUES (?, ?, 'queued', ?) ON CONFLICT(transcript_id, format) DO UPDATE SET status='queued', error='', updated_at=excluded.updated_at WHERE styled_outputs.status IN ('done', 'failed')",
                   (transcript["id"], format, time.time()))
    return {"status": "queued"}


@router.get("/jobs/{job_id}/outputs/{format}/download/{extension}")
def download_output(job_id: uuid.UUID, format: str, extension: str, request: Request, user=Depends(current_user)):
    if format not in OUTPUT_FORMATS or extension not in {"txt", "docx"}:
        raise HTTPException(404, "Output format not found.")
    with connect(request.app.state.data_dir) as db:
        job, transcript = newest_transcript(db, job_id, user["id"])
        row = db.execute("SELECT * FROM styled_outputs WHERE transcript_id=? AND format=?", (transcript["id"], format)).fetchone()
    if row is None or row["status"] != "done":
        raise HTTPException(409, "This output is not ready yet.")
    name = f"{Path(job['filename']).stem}-{format}.{extension}"
    if extension == "txt":
        return Response(row["text"] + "\n", media_type="text/plain; charset=utf-8", headers=attachment(name))
    doc = docx.Document()
    plain_title_style(doc)
    doc.add_heading(clean(Path(job["filename"]).stem), 0)
    doc.add_heading(format.replace("_", " ").title(), 1)
    for line in row["text"].splitlines():
        doc.add_paragraph(clean(line[2:] if line.startswith("- ") else line), style="List Bullet" if line.startswith("- ") else None)
    out = io.BytesIO()
    doc.save(out)
    return Response(out.getvalue(), media_type=DOCX_TYPE, headers=attachment(name))
