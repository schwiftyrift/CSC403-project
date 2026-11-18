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
Docker (from the repo root): `docker compose up --build` starts the app, transcription workers,
and local study-output services; open http://localhost:8087/. The text model must also be downloaded
once; see Deployment configuration below.

For study generation without Docker, start Ollama separately and run `ollama pull qwen3:1.7b`.
In a second terminal, from `Main` with the same virtual environment and `DATA_DIR` as the API, run
`.\.venv\Scripts\python.exe -m service.output_worker`. The worker uses `http://localhost:11434`
unless `OLLAMA_URL` is set. Audio transcription still needs the existing Whisper worker.

## Accounts and data

Passwords are salted and hashed using scrypt. Login creates a revocable seven-day
session in an HttpOnly, SameSite=Strict cookie; only a SHA-256 hash of its random
token is stored in the database. Logout revokes the current session.
Email addresses are normalized to lowercase; passwords must be 12-128 characters.

SQLite stores users, sessions, and jobs in `DATA_DIR/accounts.sqlite3`.
Transcripts are stored in `transcripts`, their timestamps in `transcript_segments` and `transcript_words`,
and transcription progress in `job_progress`; existing records are preserved.
Content/output selections are stored in `output_preferences`, and generated results and their
statuses in `styled_outputs`. Results belong to a particular transcript, so a replacement transcript
does not reuse results generated from an older attempt. Deleting the upload also deletes these rows.
Uploaded bytes live in `DATA_DIR/uploads`. The default DATA_DIR is `./data`;
Docker uses `/data` in the existing persistent volume. Back up the database and
uploads together while the service is stopped.

Deleting an upload removes its database row, its transcripts (by cascade), its stored
hash, and every `uploads/<job_id>.*` file. SQLite `secure_delete` is enabled so deleted rows are
overwritten in the database file. If a file is in use (for example, being downloaded on
Windows), the API returns 409 and keeps the record so the user can retry. Backups made
before a deletion still contain the deleted data.

All job routes except `/jobs/limits` require login and check ownership, including downloads. Another account receives 404 when requesting a private job.
Existing JSON upload records remain on disk but are not assigned to any account;
an explicit owner mapping is required before migrating old uploads.

## Transcription progress

The worker (`Transcribe/worker.py`) transcribes uploads automatically, one at a time, in upload
order. Jobs move through `queued`, `preparing` (decoding audio and detecting language, so no percent
is available yet), `transcribing`, and then `done` or `failed`. A file with no readable audio fails.

While transcribing, the worker stores progress in `job_progress` every 2 seconds. `GET /jobs/activity`
turns that into a percent and an estimated time left, and keeps finished jobs for 24 hours. A page
gets the progress panel and milestone notifications by including `job-progress.js` with one script tag.

## Study outputs

On `/upload.html`, choose General transcription, Lecture, Video captions, or Notes and select
Summary, Important topics, or Study guide independently. Notes means an audio/video recording
to turn into study material; document uploads are not supported. Lecture defaults to summary and
topics, and Notes defaults to a study guide. The original transcript is always available.

After transcription finishes, `output-worker` generates selected formats through the local Ollama
service. Summaries are one paragraph of up to 500 words; topics are bullets with explanations;
study guides have up to five short-answer questions and a separate answer section. Generation
requests English material based only on the transcript. Whisper's language detection is unchanged.

Open View transcript from Your uploads to switch output tabs, generate formats for existing uploads,
or regenerate a saved result. Each generated format has its own TXT and DOCX downloads containing
only that output. Video captions use the existing SRT/VTT download options. PDF export is not included.

Generation is separate from transcription: a generation failure leaves the original transcript usable.
Failed outputs require Retry after the underlying issue is fixed. During regeneration, previous text
is retained until a replacement succeeds; downloads become available again when generation finishes.
An interrupted generation is requeued after ten minutes. CPU generation can take several minutes.
Transcripts longer than 16,000 characters are rejected for study generation with an explanatory
message; original transcript and caption downloads remain available. Review generated material
against the transcript, since source-only instructions cannot guarantee factual accuracy.

## Transcript downloads

On the history page, "Download transcript" opens a menu offering a text file (`transcript.txt`)
or a Word document (`transcript.docx`). Both routes follow the same rules: they need a login,
return 404 for other accounts' jobs, and use the newest transcript when a job was retried.

The Word document has the upload's name as its title, then the original file, upload time
(in UTC, because the server doesn't know the reader's timezone), length, word count, and creation time.
Whisper's segments are joined into paragraphs at pauses of 2 seconds or more, or at a
sentence end once a paragraph passes a minute (and at two minutes regardless). Each paragraph starts with its timestamp. Longer recordings are split
into sections ("Part 2 (5:10)") at pauses of 6 seconds or more, or every 5 minutes. The sections
are time-based; there is no topic detection. The thresholds are constants at the top of
`service/transcript_doc.py`. Transcripts made before timestamps were saved still download: the
plain text is split into paragraphs without timestamps, and a note says why.

### Captions

The same menu offers captions as SubRip (`captions.srt`, for video editors) or WebVTT
(`captions.vtt`, for browsers and web players). The worker asks Whisper for word timestamps and
stores them in `transcript_words`; captions are cut from those words. A new caption starts at a
pause of 1 second or more, after each sentence, when the text would no longer fit in two lines of
42 characters, or before it would pass 6 seconds. Short captions are held for at least 1 second when
the next one allows, and captions never overlap. The limits are constants at the top of
`service/captions.py`.

Transcripts made before word timestamps were saved still get captions: each segment's time is
spread across its words by length, which is less precise. Transcripts with no timestamps at all,
and recordings with no speech, return 409 with a message saying why. After updating, rebuild the
worker (`docker compose up --build`) so new transcriptions store word timings.

## Upload limits

Allowed: .mp3, .wav, .m4a, .mp4, .mov. Max size: 500 MB (set `MAX_UPLOAD_MB` to change).
To change them, edit `ALLOWED` and `DEFAULT_MAX_MB` at the top of `service/jobs.py`;
nothing else needs to change. The upload page reads them from
`GET /jobs/limits`, so the browser and server always agree. Rejected files get a message
explaining why and how to fix it. The server re-checks every upload.

Duplicate uploads are blocked by content, not name: the server takes a SHA-256 hash while
receiving the file and rejects it (409) if the same account already has a file with that hash
stored on the server, even under another name. A record whose file is missing from disk does
not block re-uploading it. Different files with the same name are allowed, and other accounts
are unaffected. Hashes live in the `upload_hashes` table and are removed with their upload.
Uploads stored before this check existed are hashed automatically at startup.

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

## Passwords

The login page links to "Forgot password?" (`/forgot.html`): users enter their email and, if an
account exists, receive a link to `/reset.html?token=...`. The reply is the same whether or not
the address has an account, and the email is sent after the response so timing does not reveal
it either. Reset links work once, expire after one hour, and are stored only as SHA-256 hashes
(`password_resets`). Using one sets the new password, signs the account out everywhere, signs this
browser in, marks the email verified, and emails a "password changed" notice.

The Settings page (`/settings.html`) lets signed-in users change their password with their current
one (other devices are signed out) or email themselves a reset link. Reset emails are limited to
one a minute and five a day per account; failed sends do not count.

## API

| Method | Route | Purpose |
| --- | --- | --- |
| POST | /auth/register | Create account and sign in (`email`, `password` JSON) |
| POST | /auth/login | Sign in with the same JSON fields |
| GET | /auth/me | Current account |
| POST | /auth/logout | Revoke current session |
| POST | /auth/verify | Verify an email address from a link (`token` JSON; no login needed) |
| POST | /auth/verification-email | Email a new verification link to the signed-in user |
| POST | /auth/password-reset-request | Email a reset link if the account exists (`email` JSON; always 202) |
| POST | /auth/password-reset | Set a new password from a link (`token`, `password` JSON); signs in |
| POST | /auth/password | Change password when signed in (`current_password`, `new_password` JSON) |
| POST | /auth/password-reset-email | Email a reset link to the signed-in user |
| POST | /jobs | Upload multipart `file`, optional `content_type` and JSON-encoded `formats` |
| GET | /jobs/limits | Allowed extensions and max upload size (no login needed) |
| GET | /jobs | Current user's uploads |
| GET | /jobs/activity | Unfinished and recently finished jobs with stage, percent, and estimated time |
| GET | /jobs/{id} | Upload metadata |
| GET | /jobs/{id}/file | Download original file |
| GET | /jobs/{id}/transcript.txt | Download the transcript as a text file |
| GET | /jobs/{id}/transcript.docx | Download the transcript as a formatted Word document |
| GET | /jobs/{id}/captions.srt | Download captions as SubRip |
| GET | /jobs/{id}/captions.vtt | Download captions as WebVTT |
| GET | /jobs/{id}/output-preferences | Read saved content type and requested formats |
| PUT | /jobs/{id}/output-preferences | Save `content_type` and `formats` as JSON |
| GET | /jobs/{id}/outputs | Read generated outputs, statuses, and errors for the newest transcript |
| POST | /jobs/{id}/outputs/{format} | Queue generation or regeneration; returns 202 |
| GET | /jobs/{id}/outputs/{format}/download/{extension} | Download a finished output as `txt` or `docx` |
| DELETE | /jobs/{id} | Delete one upload, its stored file, and its transcript |
| DELETE | /jobs | Delete all of the current user's uploads and transcripts |

Lists accept `limit` (1-100, default 50) and `offset` (default 0).
The history page (`/history.html`) pages
through uploads, offers list and grid layouts, and deletes one upload or all of them.
Use a cookie jar with API clients. Browser writes must be from the same origin.

Content types are `general`, `lecture`, `video`, and `notes`; generated formats are `summary`,
`topics`, and `study_guide`. Uploads default to `general` and no generated formats. Generation
statuses are `queued`, `generating`, `done`, and `failed`. Output downloads return 409 until
the selected output is ready. Saving preferences lets the worker queue missing outputs after
transcription; the generation route also supports explicit retry and regeneration.

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
- `OUTPUT_MODEL`: local text model used by `output-worker` (default `qwen3:1.7b`).
  Set it in the repository-root `.env`; Compose passes it to the worker. Pull the same model in Ollama.
- `OLLAMA_URL`: Ollama address used by `output-worker`. Compose sets `http://ollama:11434`;
  outside Docker the default is `http://localhost:11434`. To use another address with Compose,
  change the output-worker environment in `docker-compose.yml`; `.env` alone does not override it.

Before public deployment, configure HTTPS, secure cookies, and proxy-level login
rate limiting. MFA, account deletion, and storage
quotas are not implemented in this initial foundation.

### Server setup and upgrades

Run these commands from the server's existing repository root, alongside `docker-compose.yml`.
Use the same checkout directory, Compose project name, and existing data volumes as the current
deployment. Before upgrading, stop the service and back up the database and uploads together as
described under Accounts and data. Update the deployed branch to include the study-output changes,
keeping the server's existing `.env` and reverse-proxy configuration.

The stack now includes `api`, `worker` (Whisper), `ollama` (local text inference), and `output-worker`.
No hosted AI account or API key is required. The server needs access to download container images
and models during setup. Allow disk space for the new model and several GB of additional inference
memory alongside the existing Whisper workers; start testing with short recordings.

```sh
docker compose config --quiet
docker compose up -d --build
docker compose exec ollama ollama pull qwen3:1.7b
docker compose exec ollama ollama list
docker compose ps
```

If `OUTPUT_MODEL` in `.env` is different, replace `qwen3:1.7b` in the pull command with that
exact model name. The default model download is approximately 1.4 GB. Model downloads are not
automatic: wait for the pull to finish before requesting study outputs. If a request failed before
the model was ready, use Retry on that output's tab after installation.

`output-worker` uses the existing API image build and shares its `/data` volume. Tables are
created automatically at startup without replacing existing records; no manual SQL migration is
needed. Keep one output-worker replica. The existing configuration requests three Whisper workers
with four threads each. If the server needs a lighter test configuration, start with one:

```sh
docker compose up -d --build --scale worker=1
```

The existing `uploads` and `whisper_models` volumes retain their names. The new `output_models`
volume stores Ollama models across container rebuilds. Do not use `docker compose down -v` when
upgrading or stopping the server, because it removes these volumes. `docker compose down` stops
the stack while keeping its volumes.

Keep the reverse proxy pointed to the existing API port, 8087 on the host. Ollama is accessed
only on the internal Compose network; port 11434 does not need to be exposed publicly. Rebuilding
the API is necessary to serve the new Upload page and transcript controls. After deploying, refresh
the browser before testing through the server's normal public address.

### Server verification

1. Open the deployed site, sign in, and choose Start Transcribing to reach `/upload.html`.
2. Upload a short English recording with Lecture selected. Confirm Summary and Important topics
   are checked, then wait for transcription and both outputs to finish.
3. Open View transcript from Your uploads. Check the original player, the generated tabs, and
   source accuracy. Download each generated output as TXT and DOCX; also check the original
   transcript and caption downloads.
4. Select Study guide on that existing upload and generate it. Check the questions and answers,
   then refresh the page to confirm the result was saved.
5. On a test deployment, stop Ollama with `docker compose stop ollama` and regenerate an output.
   Confirm the failure leaves the transcript usable. Run `docker compose start ollama`, then Retry
   and confirm generation completes. This step temporarily interrupts all study generation.

Automated tests use temporary data and mock model generation; the browser checks above verify
the installed model and real server setup. The production image excludes the tests and transcription
source needed by some tests. Mount the checkout read-only for a one-off test container:

```sh
docker compose run --rm --no-deps -v .:/workspace:ro -w /workspace/Main api python -m pytest -q -p no:cacheprovider
```

### Troubleshooting study generation

Check service state, installed models, and recent logs first:

```sh
docker compose ps
docker compose exec ollama ollama list
docker compose logs --tail=100 api worker output-worker ollama
```

| Symptom | Check or action |
| --- | --- |
| Original transcript is not ready | Check `worker` logs first. Study generation waits for Whisper to finish. |
| Transcript works, output stays queued | Confirm `output-worker` is running and shares the API's `uploads:/data` volume. Run `docker compose up -d output-worker` if it is stopped. |
| Local generation is unavailable | Confirm Ollama is running, the configured model appears in `ollama list`, and `OLLAMA_URL` matches the Compose service. Check both services' logs, correct the cause, then Retry. |
| Model name changed but generation still uses the old one | Recreate the worker with `docker compose up -d output-worker` after editing `.env`, and pull the newly configured model. Restart alone does not apply changed environment settings. |
| Container exits or generation is very slow | Check host memory, CPU load, and Ollama logs. Reduce Whisper concurrency with `--scale worker=1` and use shorter test recordings. |
| Output remains generating after a worker restart | Interrupted work is requeued after ten minutes. Check the worker logs if it does not recover. |
| Recording is rejected for study generation | Check for an empty transcript or the 16,000-character limit. Use a shorter recording; transcription downloads still work. |
| Model response is invalid or exceeds the summary limit | Retry; the worker validates model output before saving a replacement. Check source length and model configuration if failures repeat. |
| New controls are missing | Confirm the deployed branch includes the UI changes, rebuild `api`, and refresh the browser. Selections are on `/upload.html`, not the home page. |
