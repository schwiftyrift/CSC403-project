import importlib
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from service.database import connect
from service.jobs import STALLED_SECONDS, progress_fields
from test_accounts import client, register, upload  # noqa: F401  (client is a fixture)

STATIC = Path(__file__).parents[1] / "static"

@pytest.fixture
def worker(client, monkeypatch):
    # faster_whisper is only installed in the worker image, so stub it to import worker.py.
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=None))
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "Transcribe"))
    sys.modules.pop("worker", None)
    module = importlib.import_module("worker")
    monkeypatch.setattr(module, "DATA_DIR", client.app.state.data_dir)
    monkeypatch.setattr(module, "PROGRESS_INTERVAL", 0)
    yield module
    sys.modules.pop("worker", None)

class FakeModel:
    def __init__(self, ends, duration, on_segment=lambda end: None):
        self.ends, self.duration, self.on_segment = ends, duration, on_segment

    def transcribe(self, path):
        def segments():
            for end in self.ends:
                yield SimpleNamespace(text=f" {end} ", end=end)
                self.on_segment(end)
        return segments(), SimpleNamespace(language="en", duration=self.duration)

def activity(client):
    return {job["job_id"]: job for job in client.get("/jobs/activity").json()["jobs"]}

def row(**values):
    return {"status": "processing", "stage": "transcribing", "duration_seconds": 100.0, "processed_seconds": 50.0,
            "started_at": 1000.0, "updated_at": 1060.0} | values

def test_percent_and_eta():
    fields = progress_fields(row(), now=1060.0)
    assert (fields["stage"], fields["percent"], fields["eta_seconds"], fields["stalled"]) == ("transcribing", 50, 60, False)

def test_eta_counts_down_between_updates_and_never_goes_negative():
    assert progress_fields(row(), now=1070.0)["eta_seconds"] == 50
    assert progress_fields(row(), now=1500.0)["eta_seconds"] == 0

def test_no_eta_until_there_is_enough_data():
    assert progress_fields(row(updated_at=1005.0), now=1005.0)["eta_seconds"] is None
    assert progress_fields(row(processed_seconds=0.0), now=1060.0)["eta_seconds"] is None

def test_percent_stays_below_100_until_done():
    assert progress_fields(row(processed_seconds=250.0), now=1060.0)["percent"] == 99
    assert progress_fields(row(status="done"), now=1060.0)["percent"] == 100

def test_unknown_duration_has_no_percent():
    fields = progress_fields(row(duration_seconds=None), now=1060.0)
    assert fields["percent"] is None and fields["eta_seconds"] is None

def test_requeued_job_ignores_old_progress():
    assert progress_fields(row(status="queued"), now=1060.0) == {"stage": "queued", "percent": None, "eta_seconds": None, "stalled": False}

def test_processing_without_a_progress_row_is_preparing():
    assert progress_fields(row(updated_at=None, stage=None), now=1060.0)["stage"] == "preparing"

def test_stalled():
    assert progress_fields(row(), now=1060.0 + STALLED_SECONDS + 1)["stalled"] is True

def test_route_is_not_parsed_as_a_job_id_and_requires_login(client):
    assert client.get("/jobs/activity").status_code == 401
    register(client)
    response = client.get("/jobs/activity")
    assert response.status_code == 200 and response.json() == {"jobs": []}
    assert response.headers["cache-control"] == "no-store"

def test_only_shows_own_jobs_but_counts_the_shared_queue(client):
    register(client)
    mine_first = upload(client)
    client.post("/auth/logout")
    register(client, "two@example.com")
    theirs = upload(client, b"other")
    jobs = activity(client)
    assert list(jobs) == [theirs]
    assert jobs[theirs]["jobs_ahead"] == 1 and mine_first not in jobs

def test_worker_reports_progress_then_finish(client, worker):
    register(client)
    job_id = upload(client)
    job = worker.claim_job()
    seen = []
    model = FakeModel([25.0, 50.0], 100.0, on_segment=lambda end: seen.append(activity(client)[job_id]["percent"]))
    assert worker.transcribe_job(model, job, "ignored") == "25.0 50.0"
    assert seen == [25, 50]
    worker.save_transcript(job, "words")
    worker.record_finish(job, "done")
    finished = activity(client)[job_id]
    assert finished["status"] == "done" and finished["percent"] == 100 and finished["finished_at"]

def test_failed_job_is_reported(client, worker):
    register(client)
    job_id = upload(client)
    job = worker.claim_job()
    worker.mark_failed(job)
    worker.record_finish(job, "failed")
    assert activity(client)[job_id]["stage"] == "failed"

def test_damaged_file_with_zero_duration_fails(client, worker):
    # faster-whisper reports this for a damaged file instead of raising.
    register(client)
    upload(client)
    job = worker.claim_job()
    with pytest.raises(ValueError):
        worker.transcribe_job(FakeModel([], 0.0), job, "ignored")

def test_delete_during_transcription_stops_the_worker_cleanly(client, worker):
    register(client)
    job_id = upload(client)
    job = worker.claim_job()
    model = FakeModel([1.0, 2.0], 100.0, on_segment=lambda end: client.delete(f"/jobs/{job_id}"))
    with pytest.raises(worker.JobDeleted):
        worker.transcribe_job(model, job, "ignored")
    worker.record_finish(job, "failed")  # must not raise

def test_saving_a_deleted_job_does_not_crash(client, worker):
    register(client)
    job_id = upload(client)
    job = worker.claim_job()
    assert client.delete(f"/jobs/{job_id}").status_code == 204
    worker.save_transcript(job, "words")
    with connect(client.app.state.data_dir) as db:
        assert db.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0] == 0

def test_missing_progress_table_does_not_fail_the_job(client, worker):
    register(client)
    upload(client)
    job = worker.claim_job()
    with connect(client.app.state.data_dir) as db:
        db.execute("DROP TABLE job_progress")
    assert worker.transcribe_job(FakeModel([1.0], 2.0), job, "ignored") == "1.0"

def test_deleting_a_job_removes_its_progress(client, worker):
    register(client)
    job_id = upload(client)
    worker.write_progress(worker.claim_job(), "preparing")
    assert client.delete(f"/jobs/{job_id}").status_code == 204
    with connect(client.app.state.data_dir) as db:
        assert db.execute("SELECT COUNT(*) FROM job_progress").fetchone()[0] == 0

def test_old_and_pre_feature_finished_jobs_are_left_out(client, worker):
    register(client)
    old, legacy = upload(client, b"old"), upload(client, b"legacy")
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE jobs SET status='done'")
        db.execute("INSERT INTO job_progress (job_id, stage, started_at, updated_at) VALUES (?, 'done', 1, ?)", (old, time.time() - 90000))
    assert activity(client) == {}

def test_signed_in_pages_load_the_progress_script(client):
    for page in ("index", "history", "settings", "transcribe", "archive", "verify"):
        assert "/job-progress.js" in (STATIC / f"{page}.html").read_text(encoding="utf-8"), page
    assert client.get("/job-progress.js").headers["cache-control"] == "no-cache"

def test_existing_database_gets_the_new_table_without_a_version_bump(client):
    with connect(client.app.state.data_dir) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        db.execute("SELECT * FROM job_progress")
