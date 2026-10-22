import time
import uuid
from pathlib import Path
from service.database import connect
from test_accounts import client, register, upload  # noqa: F401  (client is a fixture)

def add_transcript(client, job_id):
    with connect(client.app.state.data_dir) as db:
        db.execute("INSERT INTO transcripts VALUES (?, ?, ?, ?)", (str(uuid.uuid4()), job_id, "secret words", time.time()))
    (client.app.state.data_dir / "uploads" / f"{job_id}.transcript.json").write_text("{}")

def counts(client):
    with connect(client.app.state.data_dir) as db:
        return tuple(db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("jobs", "transcripts"))

def stored_files(client):
    return sorted(p.name for p in (client.app.state.data_dir / "uploads").iterdir())

def test_delete_one_removes_row_file_and_transcript(client):
    register(client)
    keep, gone = upload(client), upload(client)
    add_transcript(client, gone)
    assert client.delete(f"/jobs/{gone}").status_code == 204
    assert [j["job_id"] for j in client.get("/jobs").json()] == [keep]
    assert counts(client) == (1, 0)
    assert stored_files(client) == [f"{keep}.wav"]
    for suffix in ("", "/file"):
        assert client.get(f"/jobs/{gone}{suffix}").status_code == 404
    assert client.delete(f"/jobs/{gone}").status_code == 404

def test_delete_all_only_affects_current_user(client):
    register(client)
    a = upload(client)
    client.post("/auth/logout")
    register(client, "two@example.com")
    b1, b2 = upload(client), upload(client)
    add_transcript(client, b1)
    assert client.delete(f"/jobs/{a}").status_code == 404
    assert client.delete("/jobs").status_code == 204
    assert client.get("/jobs").json() == []
    assert client.delete("/jobs").status_code == 204
    assert counts(client) == (1, 0)
    assert stored_files(client) == [f"{a}.wav"]

def test_delete_when_file_already_missing(client):
    register(client)
    job = upload(client)
    (client.app.state.data_dir / "uploads" / f"{job}.wav").unlink()
    assert client.delete(f"/jobs/{job}").status_code == 204
    assert counts(client) == (0, 0)

def test_file_in_use_keeps_record_for_retry(client, monkeypatch):
    register(client)
    job, other = upload(client), upload(client)
    real_unlink = Path.unlink
    def locked(self, missing_ok=False):
        if self.name.startswith(job):
            raise PermissionError("in use")
        real_unlink(self, missing_ok=missing_ok)
    monkeypatch.setattr(Path, "unlink", locked)
    assert client.delete(f"/jobs/{job}").status_code == 409
    assert client.get(f"/jobs/{job}").status_code == 200
    assert client.delete("/jobs").status_code == 409
    assert [j["job_id"] for j in client.get("/jobs").json()] == [job]
    monkeypatch.setattr(Path, "unlink", real_unlink)
    assert client.delete("/jobs").status_code == 204
    assert stored_files(client) == []

def test_delete_requires_login_and_same_origin(client):
    assert client.delete("/jobs").status_code == 401
    assert client.delete(f"/jobs/{uuid.uuid4()}").status_code == 401
    register(client)
    job = upload(client)
    assert client.delete(f"/jobs/{job}", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.delete("/jobs", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.delete("/jobs/not-a-uuid").status_code == 400
    assert client.get(f"/jobs/{job}").status_code == 200

def test_secure_delete_enabled(client):
    with connect(client.app.state.data_dir) as db:
        assert db.execute("PRAGMA secure_delete").fetchone()[0] == 1

def test_deleted_text_not_left_in_database_file(client):
    register(client)
    job = upload(client)
    add_transcript(client, job)
    client.delete(f"/jobs/{job}")
    assert b"secret words" not in (client.app.state.data_dir / "accounts.sqlite3").read_bytes()
