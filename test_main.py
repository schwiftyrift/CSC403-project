from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def upload(name):
    return client.post("/jobs", files={"file": (name, b"audio", "application/octet-stream")})


def test_upload_creates_job():
    r = upload("talk.mp3")
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    assert client.get(f"/jobs/{job_id}").json()["status"] == "queued"


def test_unsupported_file_is_refused():
    assert upload("notes.txt").status_code == 400
