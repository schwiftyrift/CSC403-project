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

def save_transcript(job, text):
    db = connect(DATA_DIR)
    try:
        with db:
            db.execute("UPDATE jobs SET status = 'done' WHERE job_id = ?", (job["job_id"],))
            db.execute("INSERT INTO transcripts (id, job_id, text, created_at) VALUES (?, ?, ? ,?)",(str(uuid.uuid4()), job["job_id"], text, time.time()))
    finally:
        db.close()

def mark_failed(job):
    db = connect(DATA_DIR)
    try:
        with db:
            db.execute("UPDATE jobs SET status = 'failed' WHERE job_id = ?", (job["job_id"],))
    finally:
        db.close()


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
            segments, info = model.transcribe(str(path))
            print(f"  language={info.language} duration={info.duration:.1f}s", flush=True)
            text = " ".join(segment.text.strip() for segment in segments)
        except Exception as e:
            print(f"  FAILED {job['job_id']}: {e}", flush=True)
            mark_failed(job)
            continue

        print(f"  done in {time.time() - started:.1f}s", flush=True)
        save_transcript(job, text)

if __name__ == "__main__":
    main()
