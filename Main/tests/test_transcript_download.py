import time
import uuid
from service.database import connect
from test_accounts import client, register, upload  # noqa: F401  (client is a fixture)

def add_transcript(client, job_id, text, created_at=None):
    with connect(client.app.state.data_dir) as db:
        db.execute("INSERT INTO transcripts VALUES (?, ?, ?, ?)", (str(uuid.uuid4()), job_id, text, created_at or time.time()))

def ready_flags(client):
    return {j["job_id"]: j["transcript_ready"] for j in client.get("/jobs").json()}

def test_download_after_transcription_finishes(client):
    register(client)
    job = upload(client)
    assert ready_flags(client) == {job: False}
    response = client.get(f"/jobs/{job}/transcript.txt")
    assert response.status_code == 404
    assert "isn't ready yet" in response.json()["error"]

    add_transcript(client, job, "  Welcome back to class.\nToday: uploads.  ")
    assert ready_flags(client) == {job: True}
    response = client.get(f"/jobs/{job}/transcript.txt")
    assert response.status_code == 200
    assert response.text == "Welcome back to class.\nToday: uploads.\n"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["content-disposition"] == "attachment; filename*=utf-8''audio.txt"

def test_newest_transcript_wins(client):
    # A retried job can end up with more than one transcript row.
    register(client)
    job = upload(client)
    add_transcript(client, job, "old attempt", created_at=1)
    add_transcript(client, job, "new attempt", created_at=2)
    assert client.get(f"/jobs/{job}/transcript.txt").text == "new attempt\n"

def test_filename_keeps_non_ascii_characters(client):
    register(client)
    response = client.post("/jobs", files={"file": ("Café lecture.mp3", b"audio", "audio/mpeg")})
    job = response.json()["job_id"]
    add_transcript(client, job, "bonjour")
    disposition = client.get(f"/jobs/{job}/transcript.txt").headers["content-disposition"]
    assert disposition == "attachment; filename*=utf-8''Caf%C3%A9%20lecture.txt"

def test_only_the_owner_can_download(client):
    register(client)
    job = upload(client)
    add_transcript(client, job, "secret words")
    client.post("/auth/logout")
    assert client.get(f"/jobs/{job}/transcript.txt").status_code == 401
    register(client, "two@example.com")
    response = client.get(f"/jobs/{job}/transcript.txt")
    assert response.status_code == 404
    assert "secret" not in response.text

def test_deleted_job_has_no_transcript(client):
    register(client)
    job = upload(client)
    add_transcript(client, job, "gone soon")
    assert client.delete(f"/jobs/{job}").status_code == 204
    assert client.get(f"/jobs/{job}/transcript.txt").status_code == 404
