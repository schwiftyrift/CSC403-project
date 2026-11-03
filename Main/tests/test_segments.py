import types
from service.database import connect
from test_accounts import client, register, upload  # noqa: F401  (client is a fixture)
from test_retry import load_worker, set_status

class FakeModel:
    """Stands in for faster-whisper: returns segments lazily, like the real model."""
    def __init__(self, segments, duration=10.0):
        self.segments, self.duration = segments, duration
    def transcribe(self, path):
        parts = (types.SimpleNamespace(start=s, end=e, text=t) for s, e, t in self.segments)
        return parts, types.SimpleNamespace(language="en", duration=self.duration)

def run_worker_on(client, monkeypatch, job_id, segments):
    worker = load_worker(monkeypatch, client.app.state.data_dir)
    job = worker.claim_job()
    assert job["job_id"] == job_id
    text, parts = worker.transcribe_job(FakeModel(segments), job, client.app.state.data_dir / "uploads" / job["storage_name"])
    worker.save_transcript(job, text, parts)
    return worker, text

def test_worker_saves_timestamps_the_page_can_read(client, monkeypatch):
    register(client)
    job = upload(client)
    whisper = [(0.0, 3.2, " Welcome back to class."), (3.2, 4.0, "   "), (4.0, 9.5, " Today: file uploads. ")]
    _, text = run_worker_on(client, monkeypatch, job, whisper)
    assert text == "Welcome back to class. Today: file uploads."  # the plain transcript is unchanged
    assert client.get(f"/jobs/{job}").json()["status"] == "done"
    assert client.get(f"/jobs/{job}/segments").json() == {"segments": [
        {"start": 0.0, "end": 3.2, "text": "Welcome back to class."},  # blank segments are dropped
        {"start": 4.0, "end": 9.5, "text": "Today: file uploads."}]}
    assert client.get(f"/jobs/{job}/transcript.txt").text == text + "\n"

def test_transcripts_from_before_timestamps_have_no_segments(client):
    register(client)
    job = upload(client)
    assert client.get(f"/jobs/{job}/segments").status_code == 404  # not transcribed yet
    with connect(client.app.state.data_dir) as db:
        db.execute("INSERT INTO transcripts VALUES ('old', ?, 'plain text only', 1)", (job,))
    assert client.get(f"/jobs/{job}/segments").json() == {"segments": []}

def test_retried_job_shows_the_newest_attempts_timestamps(client, monkeypatch):
    register(client)
    job = upload(client)
    run_worker_on(client, monkeypatch, job, [(0.0, 1.0, "first try")])
    set_status(client, job, "queued")
    run_worker_on(client, monkeypatch, job, [(0.0, 2.0, "second try")])
    assert [s["text"] for s in client.get(f"/jobs/{job}/segments").json()["segments"]] == ["second try"]

def test_worker_keeps_the_transcript_if_the_segments_table_is_missing(client, monkeypatch):
    register(client)
    job = upload(client)
    with connect(client.app.state.data_dir) as db:
        db.execute("DROP TABLE transcript_segments")  # an API older than this change
    run_worker_on(client, monkeypatch, job, [(0.0, 1.0, "still saved")])
    assert client.get(f"/jobs/{job}/transcript.txt").text == "still saved\n"

def test_deleting_a_job_deletes_its_segments(client, monkeypatch):
    register(client)
    job = upload(client)
    run_worker_on(client, monkeypatch, job, [(0.0, 1.0, "gone soon")])
    assert client.delete(f"/jobs/{job}").status_code == 204
    with connect(client.app.state.data_dir) as db:
        assert db.execute("SELECT COUNT(*) FROM transcript_segments").fetchone()[0] == 0

def test_media_streams_inline_with_seeking(client):
    register(client)
    job = upload(client, b"0123456789")
    response = client.get(f"/jobs/{job}/media")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert "attachment" not in response.headers.get("content-disposition", "")
    response = client.get(f"/jobs/{job}/media", headers={"Range": "bytes=2-4"})
    assert response.status_code == 206
    assert response.content == b"234"

def test_only_the_owner_can_see_segments_or_media(client, monkeypatch):
    register(client)
    job = upload(client)
    run_worker_on(client, monkeypatch, job, [(0.0, 1.0, "secret words")])
    client.post("/auth/logout")
    for path in ("segments", "media"):
        assert client.get(f"/jobs/{job}/{path}").status_code == 401
    register(client, "two@example.com")
    for path in ("segments", "media"):
        response = client.get(f"/jobs/{job}/{path}")
        assert response.status_code == 404
        assert "secret" not in response.text
