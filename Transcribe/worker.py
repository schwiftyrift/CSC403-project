"""Transcription worker (stub).

Planned loop:
  1. claim one 'queued' job atomically:
       UPDATE jobs SET status='processing', updated_at=? WHERE id=(
           SELECT id FROM jobs WHERE status='queued' ORDER BY created_at LIMIT 1)
       RETURNING id, stored_path
  2. prepare the media (ingestion step)
  3. faster-whisper transcribe (iterate the generator inside try/except)
  4. write the transcript to a temp name, then rename into place
  5. set status to 'done' or 'failed'; requeue stale 'processing' jobs on startup
"""
import os
import time
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "./data"))
MODEL = os.environ.get("WHISPER_MODEL", "medium")
THREADS = int(os.environ.get("WHISPER_THREADS", "4"))
POLL_SECONDS = 2


def main() -> None:
    print(f"worker up: model={MODEL} threads={THREADS} data_dir={DATA_DIR}", flush=True)
    while True:
        # TODO: claim and process jobs (see module docstring)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
