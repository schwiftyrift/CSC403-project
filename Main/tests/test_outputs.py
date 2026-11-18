import io
import json
import time

import docx
import pytest
from service.database import connect
from service import output_worker
from service.output_worker import process_next, render_output
from test_accounts import client, register, upload  # noqa: F401
from test_transcript_download import add_transcript


def test_caption_generation_and_distinct_download_names(client, monkeypatch):
    register(client)
    job = upload(client)
    add_transcript(client, job, "Cells contain DNA.")
    base = f"/jobs/{job}/outputs"
    assert client.get(base).json() == []
    assert client.post(base + "/captions").status_code == 409
    with connect(client.app.state.data_dir) as db:
        transcript = db.execute("SELECT id FROM transcripts WHERE job_id=?", (job,)).fetchone()[0]
        db.execute("INSERT INTO transcript_words VALUES (?, ?, ?, ?, ?)", (transcript, 0, 0.0, 1.5, "Cells contain DNA."))
    assert client.get(base + "/captions/download/srt").status_code == 409
    assert client.post(base + "/captions").status_code == 202
    assert not process_next(client.app.state.data_dir)
    monkeypatch.setattr(output_worker, "generate", lambda format, text: text)
    names = set()
    for format in ["summary", "topics", "study_guide", "captions"]:
        if format != "captions":
            assert client.post(base + "/" + format).status_code == 202
            assert process_next(client.app.state.data_dir)
        for extension in (["srt", "vtt"] if format == "captions" else ["txt", "docx"]):
            response = client.get(f"{base}/{format}/download/{extension}")
            assert response.status_code == 200
            name = response.headers["content-disposition"]
            assert f"audio-{format}.{extension}" in name
            assert name not in names
            names.add(name)
            if extension == "srt":
                assert "00:00:00,000 -->" in response.text
            if extension == "vtt":
                assert response.text.startswith("WEBVTT")
    assert client.get(base + "/captions/download/txt").status_code == 404
    assert client.get(base + "/summary/download/srt").status_code == 404


def test_upload_preferences_and_validation(client):
    register(client)
    response = client.post("/jobs", files={"file": ("lecture.wav", b"audio")},
                           data={"content_type": "lecture", "formats": '["summary", "topics"]'})
    assert response.status_code == 201
    job = response.json()["job_id"]
    assert client.get(f"/jobs/{job}/output-preferences").json() == {"content_type": "lecture", "formats": ["summary", "topics"]}
    for value in ['{}', 'null', '["bad"]', '[{}]', 'broken']:
        assert client.post("/jobs", files={"file": ("x.wav", b"other")}, data={"formats": value}).status_code == 400
    assert client.put(f"/jobs/{job}/output-preferences", json={"content_type": "bad"}).status_code == 400


@pytest.mark.parametrize("format", ["summary", "topics", "study_guide"])
def test_preferences_require_an_explicit_generation_request(client, monkeypatch, format):
    register(client)
    response = client.post("/jobs", files={"file": ("lecture.wav", b"audio")},
                           data={"content_type": "lecture", "formats": '["summary", "topics", "study_guide"]'})
    assert response.status_code == 201
    job = response.json()["job_id"]
    add_transcript(client, job, "Cells contain DNA.")
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE jobs SET status='done' WHERE job_id=?", (job,))
    calls = []
    def generate(format, text):
        calls.append(format)
        return "Cells contain DNA."
    monkeypatch.setattr(output_worker, "generate", generate)
    assert not process_next(client.app.state.data_dir)
    assert client.get(f"/jobs/{job}/outputs").json() == []
    client.put(f"/jobs/{job}/output-preferences", json={"content_type": "notes", "formats": ["study_guide"]})
    assert not process_next(client.app.state.data_dir)
    assert calls == []
    assert client.post(f"/jobs/{job}/outputs/{format}").status_code == 202
    assert process_next(client.app.state.data_dir)
    assert calls == [format]
    assert [item["format"] for item in client.get(f"/jobs/{job}/outputs").json()] == [format]
    assert not process_next(client.app.state.data_dir)


def test_old_upload_generation_download_regeneration_and_deletion(client, monkeypatch):
    register(client)
    job = upload(client)
    assert client.get(f"/jobs/{job}/output-preferences").json()["formats"] == []
    assert client.post(f"/jobs/{job}/outputs/summary").status_code == 404
    add_transcript(client, job, "Cells contain DNA.")
    monkeypatch.setattr(output_worker, "generate", lambda format, text: "Cells contain DNA.")
    assert client.post(f"/jobs/{job}/outputs/summary").status_code == 202
    assert client.get(f"/jobs/{job}/outputs/summary/download/txt").status_code == 409
    assert process_next(client.app.state.data_dir)
    result = client.get(f"/jobs/{job}/outputs").json()[0]
    assert result["status"] == "done" and result["text"] == "Cells contain DNA."
    assert client.get(f"/jobs/{job}/outputs/summary/download/txt").text == "Cells contain DNA.\n"
    response = client.get(f"/jobs/{job}/outputs/summary/download/docx")
    document = docx.Document(io.BytesIO(response.content))
    assert "Cells contain DNA." in [p.text for p in document.paragraphs]
    assert client.post(f"/jobs/{job}/outputs/summary").status_code == 202
    assert process_next(client.app.state.data_dir)
    assert client.delete(f"/jobs/{job}").status_code == 204
    with connect(client.app.state.data_dir) as db:
        assert db.execute("SELECT COUNT(*) FROM styled_outputs").fetchone()[0] == 0


def test_automatic_outputs_failure_retry_and_stale_recovery(client, monkeypatch):
    register(client)
    job = upload(client)
    client.put(f"/jobs/{job}/output-preferences", json={"content_type": "notes", "formats": ["study_guide"]})
    add_transcript(client, job, "Cells contain DNA.")
    def fail(*args):
        raise ValueError("Generation failed")
    monkeypatch.setattr(output_worker, "generate", fail)
    assert not process_next(client.app.state.data_dir)
    assert client.post(f"/jobs/{job}/outputs/study_guide").status_code == 202
    assert process_next(client.app.state.data_dir)
    assert client.get(f"/jobs/{job}/outputs").json()[0]["status"] == "failed"
    assert client.get(f"/jobs/{job}/transcript").json()["text"] == "Cells contain DNA."
    assert not process_next(client.app.state.data_dir)
    client.post(f"/jobs/{job}/outputs/study_guide")
    monkeypatch.setattr(output_worker, "generate", lambda *args: "Review questions\n1. What do cells contain?\n\nAnswers\n1. DNA.")
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE styled_outputs SET status='generating', updated_at=?", (time.time() - 700,))
    assert process_next(client.app.state.data_dir)
    assert client.get(f"/jobs/{job}/outputs").json()[0]["status"] == "done"


def test_output_ownership_and_newest_transcript(client, monkeypatch):
    register(client)
    job = upload(client)
    add_transcript(client, job, "Old", created_at=1)
    monkeypatch.setattr(output_worker, "generate", lambda *args: "Old summary")
    client.post(f"/jobs/{job}/outputs/summary")
    process_next(client.app.state.data_dir)
    add_transcript(client, job, "New", created_at=2)
    assert client.get(f"/jobs/{job}/outputs").json() == []
    assert client.get(f"/jobs/{job}/outputs/summary/download/txt").status_code == 409
    client.post("/auth/logout")
    assert client.get(f"/jobs/{job}/outputs").status_code == 401
    register(client, "other@example.com")
    for route in ["outputs", "output-preferences", "outputs/summary/download/docx"]:
        assert client.get(f"/jobs/{job}/{route}").status_code == 404
    assert client.post(f"/jobs/{job}/outputs/summary").status_code == 404
    assert client.put(f"/jobs/{job}/output-preferences", json={}).status_code == 404


def test_output_validation():
    assert render_output("summary", {"summary": "One\nparagraph."}) == "One paragraph."
    assert render_output("topics", {"topics": [{"topic": "Cells", "explanation": "Contain DNA."}]}).startswith("- Cells:")
    assert "Answers\n1. DNA" in render_output("study_guide", {"questions": [{"question": "What?", "answer": "DNA"}]})
    for data in [{"summary": " "}, {"summary": "word " * 501}]:
        with pytest.raises(ValueError):
            render_output("summary", data)
    with pytest.raises(ValueError):
        render_output("study_guide", {"questions": []})
    with pytest.raises(ValueError, match="too long"):
        output_worker.generate("summary", "x" * 16001)


def test_empty_transcript(client):
    register(client)
    job = upload(client)
    add_transcript(client, job, " ")
    assert client.post(f"/jobs/{job}/outputs/summary").status_code == 409
