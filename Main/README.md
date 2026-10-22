# Transcript Service

FastAPI service with email/password accounts, private media uploads, and upload history.

## Run locally (PowerShell)

Run these from this `Main` folder.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Open http://localhost:8000/ and choose "Log in or create an account".
The separate `/login.html` page uses the login design from the team's `test` branch,
connected to the account API. Successful login returns to the upload page;
logout revokes the session and opens the login page. API documentation: `/docs`.
Tests: `.\.venv\Scripts\python.exe -m pytest -q`.
Docker (from the repo root): `docker compose up --build` starts the app and the transcription
worker; open http://localhost:8087/.

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

Deleting an upload removes its database row, its transcripts (by cascade), and every
`uploads/<job_id>.*` file. SQLite `secure_delete` is enabled so deleted rows are
overwritten in the database file. If a file is in use (for example, being downloaded on
Windows), the API returns 409 and keeps the record so the user can retry. Backups made
before a deletion still contain the deleted data.

All job routes require login and check ownership, including downloads. Another account receives 404 when requesting a private job.
Existing JSON upload records remain on disk but are not assigned to any account;
an explicit owner mapping is required before migrating old uploads.

Automatic transcription is not implemented yet. The current demonstration covers
registration, login/logout, private file storage, downloads, upload history, and deletion.
There is no manual transcript entry or transcript API; a future transcription
integration can attach generated text to uploaded jobs.

## Email verification

New accounts are emailed a link to `/verify.html?token=...`; opening it marks the address
verified. Links expire after 24 hours and only verify the account's current email address.
Signed-in users with an unverified email see a banner with a Resend button (at most one email
a minute and five a day per account). Unverified accounts can still use the site, and
`GET /auth/me` reports `email_verified`. Links are stored only as SHA-256 hashes
(`email_tokens`); verified addresses are kept in `verified_emails`.

Email is sent over SMTP using the settings below. Without `SMTP_HOST`, emails are written to
`outbox.log` in the data folder instead, so development and tests never send real email. With
`SMTP_HOST` set, `MAIL_FROM` is required and the app will not start without it. For Docker,
copy `.env.example` to `.env` at the repo root and fill it in (`.env` is never committed).
When running locally without Docker, set the variables in PowerShell first, for example
`$env:SMTP_HOST = "smtp.resend.com"`.

## API

| Method | Route | Purpose |
| --- | --- | --- |
| POST | /auth/register | Create account and sign in (`email`, `password` JSON) |
| POST | /auth/login | Sign in with the same JSON fields |
| GET | /auth/me | Current account |
| POST | /auth/logout | Revoke current session |
| POST | /auth/verify | Verify an email address from a link (`token` JSON; no login needed) |
| POST | /auth/verification-email | Email a new verification link to the signed-in user |
| POST | /jobs | Upload multipart `file` |
| GET | /jobs | Current user's uploads |
| GET | /jobs/{id} | Upload metadata |
| GET | /jobs/{id}/file | Download original file |
| DELETE | /jobs/{id} | Delete one upload, its stored file, and its transcript |
| DELETE | /jobs | Delete all of the current user's uploads and transcripts |

Lists accept `limit` (1-100, default 50) and `offset` (default 0).
The history page (`/history.html`) pages
through uploads, offers list and grid layouts, and deletes one upload or all of them.
Use a cookie jar with API clients. Browser writes must be from the same origin.

## Adding account features

- `service/database.py`: connection management, foreign keys, schema version 1.
  Add versioned migrations here when changing an existing schema.
- `service/auth.py`: accounts, password hashing, reusable `current_user` dependency.
- `service/jobs.py`: owned uploads, downloads, upload history, and deletion.
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
  for same-origin validation behind a reverse proxy and for links in emails. No trailing slash.
- `SMTP_HOST`, `SMTP_PORT` (default 587; 465 also works), `SMTP_USER`, `SMTP_PASSWORD`:
  outgoing mail server. For Resend: `smtp.resend.com`, 587, `resend`, and an API key.
- `MAIL_FROM`: sender, e.g. `Transcript Service <no-reply@mail.example.com>`, on a domain
  your mail provider has verified.

Before public deployment, configure HTTPS, secure cookies, and proxy-level login
rate limiting. Password reset, MFA, account deletion, storage
quotas, and automated transcription are not implemented in this initial foundation.
