# Transcript Service

FastAPI service with email/password accounts, private media uploads, and upload history.

## Run locally (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Open http://localhost:8000/ to create an account. API documentation: `/docs`.
Tests: `.\.venv\Scripts\python.exe -m pytest -q`.
Docker: `docker compose up --build`; open http://localhost:8087/.

## Accounts and data

Passwords are salted and hashed using scrypt. Login creates a revocable seven-day
session in an HttpOnly, SameSite=Strict cookie; only a SHA-256 hash of its random
token is stored in the database. Logout revokes the current session.
Email addresses are normalized to lowercase; passwords must be 12-128 characters.

SQLite stores users, sessions, and jobs in `DATA_DIR/accounts.sqlite3`.
A transcript table is reserved for future automatic transcription; existing records are preserved.
Uploaded bytes live in `DATA_DIR/uploads`. The default DATA_DIR is `./data`;
Docker uses `/data` in the existing persistent volume. Back up the database and
uploads together while the service is stopped.

All job routes require login and check ownership, including downloads. Another account receives 404 when requesting a private job.
Existing JSON upload records remain on disk but are not assigned to any account;
an explicit owner mapping is required before migrating old uploads.

Automatic transcription is not implemented yet. The current demonstration covers
registration, login/logout, private file storage, downloads, and upload history.
There is no manual transcript entry or transcript API; a future transcription
integration can attach generated text to uploaded jobs.

## API

| Method | Route | Purpose |
| --- | --- | --- |
| POST | /auth/register | Create account and sign in (`email`, `password` JSON) |
| POST | /auth/login | Sign in with the same JSON fields |
| GET | /auth/me | Current account |
| POST | /auth/logout | Revoke current session |
| POST | /jobs | Upload multipart `file` |
| GET | /jobs | Current user's uploads |
| GET | /jobs/{id} | Upload metadata |
| GET | /jobs/{id}/file | Download original file |

Lists accept `limit` (1-100, default 50) and `offset` (default 0).
The UI pages through upload history.
Use a cookie jar with API clients. Browser writes must be from the same origin.

## Adding account features

- `service/database.py`: connection management, foreign keys, schema version 1.
  Add versioned migrations here when changing an existing schema.
- `service/auth.py`: accounts, password hashing, reusable `current_user` dependency.
- `service/jobs.py`: owned uploads, downloads, and upload history.
- `main.py`: app factory, configuration, shared middleware, router registration.

For a feature such as preferences or notes, add a table with
`user_id REFERENCES users(id) ON DELETE CASCADE`, create a separate router module,
use `Depends(current_user)`, and constrain every read/write by that user's ID.
For data attached to a job, verify ownership with `owned_job` before reading or writing it.
Never accept an owner ID from the browser as proof of authorization.

## Deployment configuration

- `DATA_DIR`: persistent database and file directory.
- `MAX_UPLOAD_MB`: maximum file size (default 500).
- `COOKIE_SECURE=true`: required when serving over HTTPS in deployment.
- `PUBLIC_ORIGIN`: exact public origin, e.g. `https://transcripts.example.com`,
  for same-origin validation behind a reverse proxy. No trailing slash.

Before public deployment, configure HTTPS, secure cookies, and proxy-level login
rate limiting. Email verification, password reset, MFA, account deletion, storage
quotas, and automated transcription are not implemented in this initial foundation.
