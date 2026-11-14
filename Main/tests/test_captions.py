import random
import re
import time
import uuid
from service.captions import MAX_CUE_SECONDS, MAX_LINE, cues, timestamp, to_srt, to_vtt, words_from_segments, wrap
from service.database import connect
from test_accounts import client, register, upload  # noqa: F401  (client is a fixture)
from test_segments import FakeModel, run_worker_on
from test_transcript_download import add_transcript

def w(start, end, text):
    return {"start": start, "end": end, "text": text}

def assert_valid(cue_list):
    """The guarantees in the service/captions.py docstring."""
    for i, cue in enumerate(cue_list):
        lines = cue["text"].split("\n")
        assert 1 <= len(lines) <= 2, cue
        assert all(0 < len(line) <= MAX_LINE for line in lines), cue
        assert cue["end"] > cue["start"], cue
        assert cue["end"] - cue["start"] <= MAX_CUE_SECONDS + 1e-9, cue
        assert "-->" not in cue["text"], cue
        if i:
            assert cue["start"] >= cue_list[i - 1]["end"] - 1e-9, (cue_list[i - 1], cue)

# --- timestamps and file formats -------------------------------------------------------------

def test_timestamps():
    assert timestamp(0, ",") == "00:00:00,000"
    assert timestamp(3725.5, ",") == "01:02:05,500"
    assert timestamp(59.9996, ",") == "00:01:00,000"  # never 00:00:60,000
    assert timestamp(1.25, ".") == "00:00:01.250"

def test_srt_and_vtt_output():
    cue_list = [{"start": 0, "end": 1.5, "text": "Hello & <b>"}, {"start": 2, "end": 3, "text": "Line one\nline two"}]
    assert to_srt(cue_list) == ("1\n00:00:00,000 --> 00:00:01,500\nHello & <b>\n\n"
                                "2\n00:00:02,000 --> 00:00:03,000\nLine one\nline two\n\n")
    assert to_vtt(cue_list) == ("WEBVTT\n\n00:00:00.000 --> 00:00:01.500\nHello &amp; &lt;b>\n\n"
                                "00:00:02.000 --> 00:00:03.000\nLine one\nline two\n\n")

# --- splitting -------------------------------------------------------------------------------

def test_breaks_at_pauses_and_sentence_ends():
    assert cues([]) == []
    texts = [c["text"] for c in cues([w(0, .5, " Hello"), w(.5, 1, " there."), w(1, 1.5, " Next"), w(3, 3.5, " pause")])]
    assert texts == ["Hello there.", "Next", "pause"]

def test_sentence_ends_inside_quotes_and_in_cjk():
    texts = [c["text"] for c in cues([w(0, .5, ' He said "stop."'), w(.5, 1, " Then"), w(1, 1.5, " (see 2.)"), w(1.5, 2, " Next")])]
    assert texts == ['He said "stop."', "Then (see 2.)", "Next"]
    assert [c["text"] for c in cues([w(0, .5, "你好。"), w(.5, 1, "再见")])] == ["你好。", "再见"]

def test_blank_words_are_skipped():
    assert [c["text"] for c in cues([w(0, 1, "  "), w(1, 2, " Hi"), w(2, 3, "")])] == ["Hi"]

def test_long_runs_respect_line_and_duration_limits():
    words = [w(i * .3, i * .3 + .3, " word") for i in range(60)]
    result = cues(words)
    assert_valid(result)
    assert len(result) > 1
    assert " ".join(c["text"].replace("\n", " ") for c in result).split() == ["word"] * 60  # nothing lost

def test_wrap_balances_two_lines():
    assert wrap("a" * 42) == "a" * 42
    lines = wrap("the quick brown fox jumps over the lazy dog and keeps running").split("\n")
    assert len(lines) == 2 and all(len(line) <= MAX_LINE for line in lines)
    assert abs(len(lines[0]) - len(lines[1])) < 12
    assert wrap("x" * 60) == "x" * 42 + "\n" + "x" * 18  # no spaces: break at the limit

def test_long_tokens_and_unspaced_text_are_chopped():
    url = "https://example.com/" + "y" * 80
    result = cues([w(i, i + .9, " " + url) for i in range(3)])
    assert_valid(result)
    assert "".join(c["text"].replace("\n", "") for c in result) == url * 3
    cjk = cues([w(i * .2, i * .2 + .2, "学") for i in range(100)])
    assert_valid(cjk)
    assert all(" " not in c["text"] for c in cjk)

# --- timing ----------------------------------------------------------------------------------

def test_short_cues_are_held_but_never_overlap():
    assert cues([w(0, .3, " Hi."), w(5, 6, " Later.")])[0]["end"] == 1.0
    assert cues([w(0, .3, " Hi."), w(.5, 1, " There.")])[0]["end"] == .5

def test_zero_length_and_overlapping_words():
    same = cues([w(2, 2, " One."), w(2, 2, " Two.")])
    assert_valid(same)
    backwards = cues([w(5, 6, " Late."), w(1, 2, " Early.")])
    assert_valid(backwards)

def test_long_word_is_capped():
    assert_valid(cues([w(0, 9, " Stretched")]))

def test_text_that_would_corrupt_a_file_is_cleaned():
    text = cues([w(0, 1, " a --> b\x07"), w(1, 2, " c\nd\te")])[0]["text"]
    assert "-->" not in text and "\x07" not in text and "\t" not in text
    assert "\n" not in text  # short enough for one line, so no newline survives from the source

def test_random_transcripts_always_produce_valid_cues():
    rng = random.Random(1)
    vocab = ["the", "lecture", "photosynthesis.", "why?", "Okay!", "x" * 50, "https://example.com/" + "y" * 80,
             "Dr.", "3.5", "&", "<b>", "-->", "\x07bell", "  ", "", "学习机器", "uninterruptible"]
    for _ in range(500):
        t, words = rng.uniform(0, 5), []
        for _ in range(rng.randint(0, 80)):
            duration = rng.choice([0.0, 0.05, 0.3, 0.6, 2.0, 9.0])
            start = t + rng.choice([0, 0.1, 0.5, 1.2, 4.0, -0.3])  # includes overlaps and backwards times
            words.append(w(start, start + duration, rng.choice([" ", ""]) + rng.choice(vocab)))
            t = max(t, start + duration)
        assert_valid(cues(words))
        segments = sorted(({"start": rng.uniform(0, 100), "end": rng.uniform(0, 100),
                            "text": " ".join(rng.choice(vocab) for _ in range(rng.randint(0, 30)))} for _ in range(rng.randint(0, 5))),
                          key=lambda s: s["start"])
        assert_valid(cues(words_from_segments(segments)))

def test_words_from_segments_fill_each_segment():
    words = words_from_segments([{"start": 10, "end": 14, "text": "a longerword"}, {"start": 20, "end": 20, "text": "   "}])
    assert [x["text"] for x in words] == [" a", " longerword"]
    assert words[0]["start"] == 10 and abs(words[-1]["end"] - 14) < 1e-9
    assert words[1]["end"] - words[1]["start"] > words[0]["end"] - words[0]["start"]

# --- worker ----------------------------------------------------------------------------------

def stored_words(client):
    with connect(client.app.state.data_dir) as db:
        return [tuple(r) for r in db.execute("SELECT start_seconds, end_seconds, text FROM transcript_words ORDER BY position")]

def test_worker_asks_for_and_stores_word_timings(client, monkeypatch):
    register(client)
    job = upload(client)
    model = FakeModel([(0.0, 2.0, " Hello there.", [(0.0, 0.8, " Hello"), (0.9, 1.0, "  "), (1.0, 2.0, " there.")])])
    run_worker_on(client, monkeypatch, job, None, model=model)
    assert model.options == {"word_timestamps": True}
    assert stored_words(client) == [(0.0, 0.8, " Hello"), (1.0, 2.0, " there.")]  # blank words dropped

def test_worker_keeps_transcript_and_segments_without_the_words_table(client, monkeypatch):
    register(client)
    job = upload(client)
    with connect(client.app.state.data_dir) as db:
        db.execute("DROP TABLE transcript_words")  # an API older than this change
    run_worker_on(client, monkeypatch, job, [(0.0, 1.0, "still saved", [(0.0, 1.0, " still"), (0.5, 1.0, " saved")])])
    assert client.get(f"/jobs/{job}/transcript.txt").text == "still saved\n"
    assert client.get(f"/jobs/{job}/segments").json()["segments"][0]["text"] == "still saved"

def test_deleting_a_job_deletes_its_words(client, monkeypatch):
    register(client)
    job = upload(client)
    run_worker_on(client, monkeypatch, job, [(0.0, 1.0, "gone", [(0.0, 1.0, " gone")])])
    assert client.delete(f"/jobs/{job}").status_code == 204
    assert stored_words(client) == []

# --- endpoints -------------------------------------------------------------------------------

def add_timed(client, job_id, text, segments=(), words=(), created_at=None):
    tid = str(uuid.uuid4())
    with connect(client.app.state.data_dir) as db:
        db.execute("INSERT INTO transcripts VALUES (?, ?, ?, ?)", (tid, job_id, text, created_at or time.time()))
        db.executemany("INSERT INTO transcript_segments VALUES (?, ?, ?, ?, ?)", [(tid, i, *s) for i, s in enumerate(segments)])
        db.executemany("INSERT INTO transcript_words VALUES (?, ?, ?, ?, ?)", [(tid, i, *x) for i, x in enumerate(words)])

WORDS = [(0.0, 0.5, " Welcome"), (0.5, 1.2, " back."), (3.0, 3.5, " Today:"), (3.5, 4.2, " captions.")]

def test_srt_and_vtt_downloads(client):
    register(client)
    job = upload(client)
    response = client.get(f"/jobs/{job}/captions.srt")
    assert response.status_code == 404 and "isn't ready yet" in response.json()["error"]
    add_timed(client, job, "Welcome back. Today: captions.", [(0.0, 4.2, "Welcome back. Today: captions.")], WORDS)

    srt = client.get(f"/jobs/{job}/captions.srt")
    assert srt.status_code == 200
    assert srt.headers["content-type"].startswith("application/x-subrip")
    assert srt.headers["content-disposition"] == "attachment; filename*=utf-8''audio.srt"
    assert srt.text == ("1\n00:00:00,000 --> 00:00:01,200\nWelcome back.\n\n"
                        "2\n00:00:03,000 --> 00:00:04,200\nToday: captions.\n\n")

    vtt = client.get(f"/jobs/{job}/captions.vtt")
    assert vtt.headers["content-type"].startswith("text/vtt")
    assert vtt.headers["content-disposition"] == "attachment; filename*=utf-8''audio.vtt"
    assert vtt.text.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.200\nWelcome back.\n\n")

def cue_times(srt_text):
    def seconds(stamp):
        h, m, rest = stamp.split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest.replace(",", "."))
    return [(seconds(a), seconds(b)) for a, b in re.findall(r"(\S+) --> (\S+)", srt_text)]

def test_segments_only_transcripts_get_estimated_captions(client):
    register(client)
    job = upload(client)
    add_timed(client, job, "First part. Second part.", [(10.0, 12.0, "First part."), (20.0, 23.0, "Second part.")])
    response = client.get(f"/jobs/{job}/captions.srt")
    assert response.status_code == 200
    times = cue_times(response.text)
    assert times and all(10.0 <= a < b <= 23.0 for a, b in times)

def test_junk_words_fall_back_to_segments(client):
    register(client)
    job = upload(client)
    add_timed(client, job, "Real text.", [(0.0, 2.0, "Real text.")], [(0.0, 1.0, "\x07"), (1.0, 2.0, "   ")])
    assert "Real text." in client.get(f"/jobs/{job}/captions.srt").text

def test_no_timestamps_and_no_speech_explain_why(client):
    register(client)
    old = upload(client, b"old")
    add_transcript(client, old, "Plain text from before timestamps.")
    response = client.get(f"/jobs/{old}/captions.vtt")
    assert response.status_code == 409 and "before timestamps were saved" in response.json()["error"]

    silent = upload(client, b"silent")
    add_timed(client, silent, "")
    response = client.get(f"/jobs/{silent}/captions.srt")
    assert response.status_code == 409 and "No speech was found" in response.json()["error"]

def test_newest_transcript_and_non_ascii_name(client):
    register(client)
    job = client.post("/jobs", files={"file": ("Café clip.mp4", b"video", "video/mp4")}).json()["job_id"]
    add_timed(client, job, "old", words=[(0.0, 1.0, " old")], created_at=1)
    add_timed(client, job, "new", words=[(0.0, 1.0, " new")], created_at=2)
    response = client.get(f"/jobs/{job}/captions.srt")
    assert response.headers["content-disposition"] == "attachment; filename*=utf-8''Caf%C3%A9%20clip.srt"
    assert "new" in response.text and "old" not in response.text

def test_only_the_owner_can_download_captions(client):
    register(client)
    job = upload(client)
    add_timed(client, job, "secret words", words=[(0.0, 1.0, " secret"), (1.0, 2.0, " words")])
    client.post("/auth/logout")
    for fmt in ("srt", "vtt"):
        assert client.get(f"/jobs/{job}/captions.{fmt}").status_code == 401
    register(client, "two@example.com")
    for fmt in ("srt", "vtt"):
        response = client.get(f"/jobs/{job}/captions.{fmt}")
        assert response.status_code == 404 and "secret" not in response.text
