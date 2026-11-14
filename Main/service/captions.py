"""Caption files (US-26): timed words -> cues -> SRT / WebVTT text.

Every cue from cues() has 1-2 lines of 1-42 characters, ends after it starts, lasts at most
MAX_CUE_SECONDS, never overlaps the next cue, and contains no "-->" or blank line (either
would corrupt the file).

Known, harmless limits: an abbreviation like "Dr." ends a cue early, and many words stamped at
the exact same time push the following cues later by MIN_GAP each.
"""
from .transcript_doc import clean as remove_control_characters

MAX_LINE = 42           # characters per line, the common broadcast/YouTube limit
MAX_LINES = 2
MAX_CUE_SECONDS = 6.0   # a cue never stays up longer than this
MIN_CUE_SECONDS = 1.0   # short cues are held this long, if the next cue allows
MIN_GAP = 0.1           # the shortest cue, even when the next cue starts immediately
PAUSE = 1.0             # a silence this long between words starts a new cue
SENTENCE_END = (".", "?", "!", "…", "。", "？", "！")  # incl. … and the CJK 。？！
CLOSERS = "\"')]}”’»」』"  # quotes/brackets after a sentence end, e.g. world."


def ends_sentence(text):
    return text.rstrip().rstrip(CLOSERS).endswith(SENTENCE_END)


def clean(text):
    text = remove_control_characters(text)
    for whitespace in ("\r", "\n", "\t"):
        text = text.replace(whitespace, " ")
    return text.replace("-->", "->")


def normalize(words):
    """Clean the text, drop blanks, stop times going backwards, and chop any token longer than
    a line into line-sized pieces, so every later step can rely on tokens of at most MAX_LINE."""
    out, prev_end = [], 0.0
    for word in words:
        text = clean(word["text"])
        body = text.strip()
        if not body:
            continue
        start = max(float(word["start"]), prev_end)
        end = max(float(word["end"]), start)
        lead = " " if text[0].isspace() else ""
        pieces = [body[i:i + MAX_LINE] for i in range(0, len(body), MAX_LINE)]
        span = (end - start) / len(pieces)
        for i, piece in enumerate(pieces):
            # Only the first piece keeps the space, so unspaced languages stay unspaced.
            out.append({"start": start + i * span, "end": start + (i + 1) * span, "text": (lead if i == 0 else "") + piece})
        prev_end = end
    return out


def words_from_segments(segments):
    """Fallback for transcripts saved before word timings: spread each segment's time across
    its words in proportion to their length."""
    words = []
    for segment in segments:
        tokens = segment["text"].split()
        if not tokens:
            continue
        span = max(0.0, segment["end"] - segment["start"])
        total = sum(len(token) + 1 for token in tokens)
        at = segment["start"]
        for token in tokens:
            length = span * (len(token) + 1) / total
            words.append({"start": at, "end": at + length, "text": " " + token})
            at += length
    return words


def split_point(text):
    """None if text fits on one line; else where to break it into two lines of at most
    MAX_LINE (the space nearest the middle, or MAX_LINE for unspaced text); -1 if impossible."""
    if len(text) <= MAX_LINE:
        return None
    spaces = [i for i, ch in enumerate(text) if ch == " "]
    if not spaces:
        return MAX_LINE if len(text) <= MAX_LINE * MAX_LINES else -1
    fitting = [i for i in spaces if i <= MAX_LINE and len(text) - i - 1 <= MAX_LINE]
    if not fitting:
        return -1
    return min(fitting, key=lambda i: abs(i - len(text) / 2))


def fits(text):
    return split_point(text) != -1


def wrap(text):
    i = split_point(text)
    if i is None:
        return text
    if text[i] == " ":
        return text[:i] + "\n" + text[i + 1:]
    return text[:i] + "\n" + text[i:]


def cues(words):
    """Words ({start, end, text}, oldest first) -> [{start, end, text}] where text may hold one "\\n"."""
    groups = []
    for word in normalize(words):
        group = groups[-1] if groups else None
        if (group is None
                or word["start"] - group["end"] >= PAUSE
                or ends_sentence(group["last"])
                or not fits((group["text"] + word["text"]).strip())
                or word["end"] - group["start"] > MAX_CUE_SECONDS):
            group = {"start": word["start"], "text": ""}
            groups.append(group)
        group["text"] += word["text"]
        group["last"] = word["text"]
        group["end"] = word["end"]

    result, prev_end = [], 0.0
    for i, group in enumerate(groups):
        start = max(group["start"], prev_end)
        next_start = groups[i + 1]["start"] if i + 1 < len(groups) else float("inf")
        end = max(group["end"], start + MIN_CUE_SECONDS)
        end = min(end, next_start, start + MAX_CUE_SECONDS)
        end = max(end, start + MIN_GAP)  # may pass next_start; the next cue's start moves up to it
        result.append({"start": start, "end": end, "text": wrap(group["text"].strip())})
        prev_end = end
    return result


def timestamp(seconds, separator):
    """Whole milliseconds first, so 59.9996 becomes 00:01:00,000 and never 00:00:60,000."""
    ms = round(seconds * 1000)
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    secs, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{ms:03d}"


def to_srt(cue_list):
    return "".join(f"{i}\n{timestamp(c['start'], ',')} --> {timestamp(c['end'], ',')}\n{c['text']}\n\n"
                   for i, c in enumerate(cue_list, 1))


def to_vtt(cue_list):
    # WebVTT reads & and < as markup; SRT needs no escaping.
    body = "".join(f"{timestamp(c['start'], '.')} --> {timestamp(c['end'], '.')}\n{c['text'].replace('&', '&amp;').replace('<', '&lt;')}\n\n"
                   for c in cue_list)
    return "WEBVTT\n\n" + body
