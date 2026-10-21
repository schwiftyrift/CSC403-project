import json

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    return TestClient(main.app)


def upload(client, name="lecture.wav", data=b"RIFF fake audio"):
    res = client.post("/jobs", files={"file": (name, data)})
    assert res.status_code == 201
    return res.json()["job_id"]


def test_transcript_not_ready_until_saved(client, tmp_path):
    job_id = upload(client)
    res = client.get(f"/jobs/{job_id}/transcript")
    assert res.status_code == 404
    assert res.json() == {"error": "transcript not ready"}

    # Whisper-style output: extra keys are dropped and text is trimmed
    whisper = {"segments": [{"id": 0, "start": 0.0, "end": 2.5, "text": " Hello class.", "tokens": [1, 2]},
                            {"id": 1, "start": 2.9, "end": 5.0, "text": " Today: uploads.", "tokens": [3]}]}
    (tmp_path / "uploads" / f"{job_id}.transcript.json").write_text(json.dumps(whisper))
    res = client.get(f"/jobs/{job_id}/transcript")
    assert res.status_code == 200
    assert res.json() == {"segments": [{"start": 0.0, "end": 2.5, "text": "Hello class."},
                                       {"start": 2.9, "end": 5.0, "text": "Today: uploads."}]}


def test_media_streams_with_ranges(client):
    job_id = upload(client, data=b"0123456789")
    res = client.get(f"/jobs/{job_id}/media")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("audio/")
    assert res.content == b"0123456789"

    res = client.get(f"/jobs/{job_id}/media", headers={"Range": "bytes=2-4"})
    assert res.status_code == 206
    assert res.content == b"234"


@pytest.mark.parametrize("path", ["media", "transcript"])
@pytest.mark.parametrize("job_id", ["not-a-uuid", "00000000-0000-0000-0000-000000000000", "..%2Fsecrets"])
def test_unknown_jobs_are_404(client, path, job_id):
    res = client.get(f"/jobs/{job_id}/{path}")
    assert res.status_code == 404
