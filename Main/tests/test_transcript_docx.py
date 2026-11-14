import io
import time
import uuid
import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from service.database import connect
from service.transcript_doc import clock, paragraphs, sections, PARAGRAPH_MAX
from test_accounts import client, register, upload  # noqa: F401
from test_transcript_download import add_transcript

def seg(start, end, text):
    return {"start": start, "end": end, "text": text}

def add_segments(client, job_id, segs, text=None, created_at=None):
    tid = str(uuid.uuid4())
    with connect(client.app.state.data_dir) as db:
        db.execute("INSERT INTO transcripts VALUES (?, ?, ?, ?)", (tid, job_id, text or " ".join(t for _, _, t in segs), created_at or time.time()))
        for i, (s, e, t) in enumerate(segs):
            db.execute("INSERT INTO transcript_segments VALUES (?, ?, ?, ?, ?)", (tid, i, s, e, t))

def get_doc(client, job):
    r = client.get(f"/jobs/{job}/transcript.docx")
    assert r.status_code == 200, r.text
    return docx.Document(io.BytesIO(r.content))

def test_clock():
    assert [clock(0), clock(75.4), clock(3725), clock(59.9)] == ["0:00", "1:15", "1:02:05", "0:59"]

def test_paragraph_rules():
    assert paragraphs([]) == []
    p = paragraphs([seg(0, 1, " Hi."), seg(1.5, 2, " there "), seg(2, 2.5, "  "), seg(5, 6, "Next.")])
    assert [x["text"] for x in p] == ["Hi. there", "Next."]
    long = [seg(i, i + 1, "word") for i in range(0, 200)]
    assert all(x["end"] - x["start"] <= 2 * PARAGRAPH_MAX + 1 for x in paragraphs(long))
    run = [seg(i, i + 1, "a" if i != 70 else "end.") for i in range(0, 100)]
    assert paragraphs(run)[0]["end"] == 71

def test_section_rules():
    paras = [dict(start=0, end=5, text="a"), dict(start=12, end=20, text="b"), dict(start=20.5, end=330, text="c"), dict(start=330.5, end=340, text="d")]
    assert [s["title"] for s in sections(paras)] == ["Part 1 (0:00)", "Part 2 (0:12)", "Part 3 (5:30)"]

def test_docx_download(client):
    register(client)
    job = upload(client)
    r = client.get(f"/jobs/{job}/transcript.docx")
    assert r.status_code == 404 and "isn't ready yet" in r.json()["error"]
    add_segments(client, job, [(0, 3, "Welcome back."), (10, 12, "Today: uploads.")])
    r = client.get(f"/jobs/{job}/transcript.docx")
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert r.headers["content-disposition"] == "attachment; filename*=utf-8''audio.docx"
    d = docx.Document(io.BytesIO(r.content))
    title = d.paragraphs[0]
    assert title.text == "audio" and title.style.name == "Title"
    # Centered, bold, no border line, and the same font, size, and color as the body text.
    assert title.style.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert title.style.element.pPr.find(qn("w:pBdr")) is None
    assert title.style.font.bold is True
    assert title.style.font.size is None and title.style.font.color.rgb is None and title.style.font.name is None
    texts = [p.text for p in d.paragraphs]
    assert "Original file: audio.wav" in texts and any(t.startswith("Words:") for t in texts)
    assert "[0:00] Welcome back." in texts and "[0:10] Today: uploads." in texts
    assert [p.text for p in d.paragraphs if p.style.name == "Heading 1"] == ["Part 1 (0:00)", "Part 2 (0:10)"]

def test_single_section_has_no_heading(client):
    register(client)
    job = upload(client)
    add_segments(client, job, [(0, 3, "One."), (3, 4, "Two.")])
    assert not [p for p in get_doc(client, job).paragraphs if p.style.name == "Heading 1"]

def test_fallback_without_segments(client):
    register(client)
    job = upload(client)
    add_transcript(client, job, "Plain text only. No times here.")
    texts = [p.text for p in get_doc(client, job).paragraphs]
    assert any("Timestamps aren't available" in t for t in texts)
    assert "Plain text only. No times here." in texts and not any(t.startswith("[") for t in texts)

def test_all_blank_segments_fall_back(client):
    register(client)
    job = upload(client)
    add_segments(client, job, [(0, 1, "  ")], text="Saved text.")
    texts = [p.text for p in get_doc(client, job).paragraphs]
    assert "Saved text." in texts

def test_control_characters_do_not_crash(client):
    register(client)
    job = client.post("/jobs", files={"file": ("bad\x07name.wav", b"audio", "audio/wav")}).json()["job_id"]
    add_segments(client, job, [(0, 1, "nul\x00here")])
    texts = [p.text for p in get_doc(client, job).paragraphs]
    assert "[0:00] nulhere" in texts

def test_newest_and_non_ascii_and_owner(client):
    register(client)
    job = client.post("/jobs", files={"file": ("Café lecture.mp3", b"audio", "audio/mpeg")}).json()["job_id"]
    add_segments(client, job, [(0, 1, "old secret")], created_at=1)
    add_segments(client, job, [(0, 1, "new secret")], created_at=2)
    r = client.get(f"/jobs/{job}/transcript.docx")
    assert r.headers["content-disposition"] == "attachment; filename*=utf-8''Caf%C3%A9%20lecture.docx"
    texts = [p.text for p in docx.Document(io.BytesIO(r.content)).paragraphs]
    assert "[0:00] new secret" in texts and "[0:00] old secret" not in texts
    client.post("/auth/logout")
    assert client.get(f"/jobs/{job}/transcript.docx").status_code == 401
    register(client, "two@example.com")
    r = client.get(f"/jobs/{job}/transcript.docx")
    assert r.status_code == 404 and "secret" not in r.text
