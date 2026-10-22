"""Database connections and versioned schema; add account features in new tables."""
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE,
 password_hash TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
 job_id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 filename TEXT NOT NULL, storage_name TEXT NOT NULL UNIQUE,
 size_bytes INTEGER NOT NULL, status TEXT NOT NULL, uploaded_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS transcripts (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
 text TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS upload_hashes (
 job_id TEXT PRIMARY KEY REFERENCES jobs(job_id) ON DELETE CASCADE,
 user_id TEXT NOT NULL, sha256 TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(user_id, uploaded_at);
CREATE INDEX IF NOT EXISTS upload_hashes_owner ON upload_hashes(user_id, sha256);
CREATE INDEX IF NOT EXISTS transcripts_job ON transcripts(job_id, created_at);
CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(user_id);
"""

@contextmanager
def connect(data_dir):
    db = sqlite3.connect(data_dir / "accounts.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    try:
        with db:
            yield db
    finally:
        db.close()

def initialize(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    with connect(data_dir) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > 1:
            raise RuntimeError("Database schema is newer than this application")
        db.executescript(SCHEMA)
        db.execute("PRAGMA user_version = 1")
