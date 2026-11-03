import os
import time
import uuid
from pathlib import Path
import sqlite3
from faster_whisper import WhisperModel

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
MODEL = os.environ.get("WHISPER_MODEL", "medium")
THREADS = int(os.environ.get("WHISPER_THREADS", "4"))
POLL_SECONDS = 2
PROGRESS_INTERVAL = 2  # seconds between progress writes, so the database stays quiet

class JobDeleted(Exception):
    """The user deleted the job while it was being transcribed."""

def connect(data_dir):
    db = sqlite3.connect(data_dir / "accounts.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA secure_delete = ON") 
    return db

# look for jobs that are stuck and requeue them
def requeue_stale():
    db = connect(DATA_DIR)
    try:
        with db:
            db.execute("UPDATE jobs SET status = 'queued' WHERE status = 'processing'")
    finally:
        db.close()

# find queued jobs and pick one based on upload time
def claim_job():
    db = connect(DATA_DIR)
    try:
        with db:
            job = db.execute("""
                UPDATE jobs SET status = 'processing' 
                WHERE job_id = (SELECT job_id FROM jobs 
                WHERE status = 'queued' ORDER BY uploaded_at LIMIT 1) 
                RETURNING job_id, storage_name, filename""").fetchone()
    finally:
        db.close()
    
    return job

def save_transcript(job, text, segments=()):
    """segments: (start_seconds, end_seconds, text) per Whisper segment, for clickable timestamps."""
    db = connect(DATA_DIR)
    try:
        with db:
            updated = db.execute("UPDATE jobs SET status = 'done' WHERE job_id = ?", (job["job_id"],))
            if updated.rowcount:  # zero means the user deleted the job while it ran
                transcript_id = str(uuid.uuid4())
                db.execute("INSERT INTO transcripts (id, job_id, text, created_at) VALUES (?, ?, ? ,?)",(transcript_id, job["job_id"], text, time.time()))
                try:
                    db.executemany("INSERT INTO transcript_segments (transcript_id, position, start_seconds, end_seconds, text) VALUES (?, ?, ?, ?, ?)",
                                   [(transcript_id, i, start, end, part) for i, (start, end, part) in enumerate(segments)])
                except sqlite3.OperationalError as e:
                    # An API too old to have created the table: keep the plain transcript rather than lose it.
                    print(f"  timestamps not saved for {job['job_id']}: {e}", flush=True)
    finally:
        db.close()

def mark_failed(job):
    db = connect(DATA_DIR)
    try:
        with db:
            db.execute("UPDATE jobs SET status = 'failed' WHERE job_id = ?", (job["job_id"],))
    finally:
        db.close()

# Best effort: a busy database or a table the API hasn't created yet must never fail a transcription.
def write_progress(job, stage, duration=None, processed=0, started=None):
    now = time.time()
    try:
        db = connect(DATA_DIR)
        try:
            with db:
                db.execute("""
                    INSERT INTO job_progress (job_id, stage, duration_seconds, processed_seconds, started_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET stage = excluded.stage, duration_seconds = excluded.duration_seconds,
                    processed_seconds = excluded.processed_seconds, started_at = excluded.started_at, updated_at = excluded.updated_at""",
                    (job["job_id"], stage, duration, processed, started or now, now))
        finally:
            db.close()
    except sqlite3.IntegrityError:
        # The foreign key fails only when the job row is gone.
        raise JobDeleted()
    except sqlite3.Error as e:
        print(f"  progress not saved for {job['job_id']}: {e}", flush=True)

def record_finish(job, stage):
    try:
        write_progress(job, stage)
    except JobDeleted:
        pass

def transcribe_job(model, job, path):
    write_progress(job, "preparing")
    segments, info = model.transcribe(str(path))
    print(f"  language={info.language} duration={info.duration:.1f}s", flush=True)
    # faster-whisper doesn't raise on a damaged file: it reports no audio and returns no text.
    if info.duration <= 0:
        raise ValueError("the file contains no readable audio")
    started = last_write = time.time()
    processed = 0.0
    write_progress(job, "transcribing", info.duration, processed, started)
    parts = []
    for segment in segments:  # lazy: the real work happens during this loop
        text = segment.text.strip()
        if text:
            parts.append((segment.start, segment.end, text))
        processed = max(processed, segment.end)
        if time.time() - last_write >= PROGRESS_INTERVAL:
            write_progress(job, "transcribing", info.duration, processed, started)
            last_write = time.time()
    return " ".join(part for _, _, part in parts), parts


def main():
    print(f"worker up: model={MODEL} threads={THREADS} data_dir={DATA_DIR}", flush=True)
    model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=THREADS, download_root="/models")
    print("model loaded", flush=True)
    requeue_stale()
    while True:
        job = claim_job()
        if job is None:
            time.sleep(POLL_SECONDS)
            continue
        
        print(f"claimed {job['job_id']} ({job['filename']})", flush=True)
        path = DATA_DIR / "uploads" / job["storage_name"]
        started = time.time()

        try:
            text, segments = transcribe_job(model, job, path)
        except JobDeleted:
            print(f"  deleted during transcription: {job['job_id']}", flush=True)
            continue
        except Exception as e:
            print(f"  FAILED {job['job_id']}: {e}", flush=True)
            mark_failed(job)
            record_finish(job, "failed")
            continue

        print(f"  done in {time.time() - started:.1f}s", flush=True)
        save_transcript(job, text, segments)
        record_finish(job, "done")

if __name__ == "__main__":
    main()
