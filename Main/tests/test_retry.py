import importlib.util
import sys
import time
import types
from pathlib import Path
from service.database import connect
from test_accounts import client, register, upload  # noqa: F401  (client is a fixture)

def set_status(client, job_id, status):
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE jobs SET status=? WHERE job_id=?", (status, job_id))

def status_of(client, job_id):
    return client.get(f"/jobs/{job_id}").json()["status"]

def test_failed_job_goes_back_to_queued(client):
    register(client)
    job = upload(client)
    set_status(client, job, "failed")
    with connect(client.app.state.data_dir) as db:
        db.execute("INSERT INTO job_progress (job_id, stage, processed_seconds, started_at, updated_at) VALUES (?, 'failed', 0, ?, ?)", (job, time.time(), time.time()))
    response = client.post(f"/jobs/{job}/retry")
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert status_of(client, job) == "queued"
    with connect(client.app.state.data_dir) as db:
        assert db.execute("SELECT COUNT(*) FROM job_progress WHERE job_id=?", (job,)).fetchone()[0] == 0

def test_only_failed_jobs_can_be_retried(client):
    register(client)
    job = upload(client)
    for status in ("queued", "processing", "done"):
        set_status(client, job, status)
        response = client.post(f"/jobs/{job}/retry")
        assert response.status_code == 409
        assert response.json()["error"] == "Only failed transcriptions can be retried."
        assert status_of(client, job) == status

def test_retry_twice_only_requeues_once(client):
    register(client)
    job = upload(client)
    set_status(client, job, "failed")
    assert client.post(f"/jobs/{job}/retry").status_code == 200
    assert client.post(f"/jobs/{job}/retry").status_code == 409

def test_missing_upload_cannot_be_retried(client):
    register(client)
    job = upload(client)
    set_status(client, job, "failed")
    (client.app.state.data_dir / "uploads" / f"{job}.wav").unlink()
    response = client.post(f"/jobs/{job}/retry")
    assert response.status_code == 409
    assert "upload the file again" in response.json()["error"]
    assert status_of(client, job) == "failed"

def test_only_the_owner_can_retry(client):
    register(client)
    job = upload(client)
    set_status(client, job, "failed")
    client.post("/auth/logout")
    assert client.post(f"/jobs/{job}/retry").status_code == 401
    register(client, "two@example.com")
    assert client.post(f"/jobs/{job}/retry").status_code == 404
    assert client.post("/jobs/not-a-uuid/retry").status_code == 400

def load_worker(monkeypatch, data_dir):
    # The worker imports faster_whisper at the top; the recovery code doesn't need it.
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=None))
    path = Path(__file__).resolve().parents[2] / "Transcribe" / "worker.py"
    spec = importlib.util.spec_from_file_location("worker", path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    monkeypatch.setattr(worker, "DATA_DIR", data_dir)
    return worker

def test_worker_restart_requeues_stuck_jobs(client, monkeypatch):
    register(client)
    stuck, finished, broken = upload(client, b"stuck"), upload(client, b"finished"), upload(client, b"broken")
    set_status(client, stuck, "processing")  # the worker died mid-transcription
    set_status(client, finished, "done")
    set_status(client, broken, "failed")
    worker = load_worker(monkeypatch, client.app.state.data_dir)
    worker.requeue_stale()
    assert status_of(client, stuck) == "queued"
    assert status_of(client, finished) == "done"
    assert status_of(client, broken) == "failed"  # failed jobs wait for the user to press Retry
    assert worker.claim_job()["job_id"] == stuck
    assert status_of(client, stuck) == "processing"

def test_retried_job_is_claimed_by_the_worker(client, monkeypatch):
    register(client)
    job = upload(client)
    set_status(client, job, "failed")
    worker = load_worker(monkeypatch, client.app.state.data_dir)
    assert worker.claim_job() is None
    client.post(f"/jobs/{job}/retry")
    assert worker.claim_job()["job_id"] == job
