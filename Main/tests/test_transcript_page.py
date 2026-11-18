"""US-22: the transcript page and the endpoints it calls."""
import re
import time
import uuid
from pathlib import Path
from service.database import connect
from test_accounts import client, register, upload  # noqa: F401  (client is a fixture)

STATIC = Path(__file__).resolve().parents[1] / "static"

def add_transcript(client, job_id, text, created_at=None):
    with connect(client.app.state.data_dir) as db:
        db.execute("INSERT INTO transcripts VALUES (?, ?, ?, ?)", (str(uuid.uuid4()), job_id, text, created_at or time.time()))
        db.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job_id,))

def test_latest_is_the_newest_of_my_transcripts(client):
    register(client)
    response = client.get("/transcripts/latest")
    assert response.status_code == 404
    assert response.json() == {"error": "No completed transcript found."}
    older, newer = upload(client, b"older"), upload(client, b"newer")
    add_transcript(client, newer, "newer words", created_at=2)
    add_transcript(client, older, "older words", created_at=1)
    latest = client.get("/transcripts/latest").json()
    assert (latest["job_id"], latest["text"], latest["filename"]) == (newer, "newer words", "audio.wav")

def test_latest_never_shows_someone_elses_transcript(client):
    register(client)
    add_transcript(client, upload(client), "secret words")
    client.post("/auth/logout")
    assert client.get("/transcripts/latest").status_code == 401
    register(client, "two@example.com")
    response = client.get("/transcripts/latest")
    assert response.status_code == 404 and "secret" not in response.text

def test_job_transcript_for_view_transcript_links(client):
    register(client)
    job = upload(client)
    assert client.get(f"/jobs/{job}").json()["status"] == "queued"  # the page shows progress from this
    assert client.get(f"/jobs/{job}/transcript").status_code == 404
    add_transcript(client, job, "hello class")
    assert client.get(f"/jobs/{job}").json()["status"] == "done"
    assert client.get(f"/jobs/{job}/transcript").json()["text"] == "hello class"
    client.post("/auth/logout")
    register(client, "two@example.com")
    assert client.get(f"/jobs/{job}").status_code == 404
    assert client.get(f"/jobs/{job}/transcript").status_code == 404

def test_page_only_calls_routes_that_exist(client):
    # The page once asked for "/transcript/latest" (no s), which 404s, so it always said "Request failed".
    source = (STATIC / "transcribe.js").read_text(encoding="utf-8")
    paths = set(re.findall(r'[`"](/(?:jobs|transcripts?)[^`"?]*)', source))
    assert "/transcripts/latest" in paths
    register(client)
    job = upload(client)
    for path in paths:
        response = client.get(path.replace("${encodeURIComponent(jobId)}", job))
        # Our endpoints answer with data or {"error": ...}; only a route that doesn't exist says {"detail": "Not Found"}.
        assert response.json().get("detail") != "Not Found", f"transcribe.js calls {path}, which is not a route"

def test_page_markup(client):
    html = (STATIC / "transcribe.html").read_text(encoding="utf-8")
    assert '<html lang="en">' in html
    assert html.index("<body") < html.index('class="top-ribbon"')  # the ribbon is inside <body>
    assert '<script type="module" src="/transcribe.js">' in html  # it uses import, so it must be a module
    assert '<script src="/job-progress.js">' in html  # sends the updates that load an unfinished transcript

def test_archive_links_each_finished_upload_to_its_transcript():
    history = (STATIC / "history.js").read_text(encoding="utf-8")
    assert "/transcribe.html?job=${encodeURIComponent(job.job_id)}" in history
