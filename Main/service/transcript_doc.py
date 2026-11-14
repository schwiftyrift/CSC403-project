"""Formatted .docx transcripts (US-23): segments -> paragraphs -> sections -> Word document.

Whisper segments are roughly one sentence each. They are joined into paragraphs at pauses,
and paragraphs into time-based sections ("Part 2 (5:10)"); there is no topic detection.
"""
import io
import re

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

PARAGRAPH_GAP = 2.0    # a pause this long (seconds) starts a new paragraph
PARAGRAPH_MAX = 60.0   # paragraphs longer than this break at the next sentence end...
                       # ...and at 2x this even without one, so unpunctuated text still breaks
SECTION_GAP = 6.0      # a pause this long starts a new section
SECTION_MAX = 300.0    # ...as does a section passing 5 minutes, at the next paragraph
FALLBACK_SENTENCES = 5 # sentences per paragraph for transcripts without timestamps
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SENTENCE_END = (".", "?", "!")
# Characters XML (and so python-docx) rejects; uploaded filenames and Whisper text are not sanitized.
_BAD_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def clean(text):
    return _BAD_XML.sub("", text)


def clock(seconds):
    """Same format as clock() in static/transcript-player.js: 75.4 -> "1:15", 3725 -> "1:02:05"."""
    total = int(seconds)
    h, m, s = total // 3600, total // 60 % 60, total % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def paragraphs(segments):
    """Segments ({start, end, text}, oldest first) -> [{start, end, text}]; blank segments are skipped."""
    paras, current, prev = [], None, None
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        if current is not None:
            length = prev["end"] - current["start"]
            if (seg["start"] - prev["end"] >= PARAGRAPH_GAP
                    or (length >= PARAGRAPH_MAX and prev["text"].rstrip().endswith(SENTENCE_END))
                    or length >= 2 * PARAGRAPH_MAX):
                paras.append(current)
                current = None
        if current is None:
            current = {"start": seg["start"], "end": seg["end"], "text": text}
        else:
            current["end"] = seg["end"]
            current["text"] += " " + text
        prev = seg
    if current is not None:
        paras.append(current)
    return paras


def sections(paras):
    """Paragraphs -> [{title, start, paragraphs}], split at long pauses or every ~5 minutes."""
    result = []
    for para in paras:
        last = result[-1] if result else None
        prev_end = last["paragraphs"][-1]["end"] if last else 0
        if last is None or para["start"] - prev_end >= SECTION_GAP or prev_end - last["start"] >= SECTION_MAX:
            result.append({"title": f"Part {len(result) + 1} ({clock(para['start'])})", "start": para["start"], "paragraphs": []})
        result[-1]["paragraphs"].append(para)
    return result


def text_paragraphs(text):
    """Fallback for transcripts saved before timestamps: split plain text into sentence groups."""
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]
    return [" ".join(sentences[i:i + FALLBACK_SENTENCES]) for i in range(0, len(sentences), FALLBACK_SENTENCES)]


def plain_title_style(doc):
    """Word's default Title style has a bottom border, a large blue heading font, and letter
    spacing. Strip all of it so the title looks like body text, just centered and bold. It keeps the
    Title style name, so Word's navigation pane still treats it as the title."""
    style = doc.styles["Title"].element
    border = style.pPr.find(qn("w:pBdr"))
    if border is not None:
        style.pPr.remove(border)
    if style.rPr is not None:
        style.remove(style.rPr)  # font, color, size, letter spacing: inherit Normal instead
    doc.styles["Title"].paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.styles["Title"].font.bold = True


def build_docx(title, metadata, segments, text):
    """Title, a "Label: value" metadata block, then timestamped paragraphs under section headings.
    Uses the plain text, untimed, when there are no non-blank segments."""
    doc = docx.Document()
    plain_title_style(doc)
    doc.add_heading(clean(title), level=0)
    for label, value in metadata:
        line = doc.add_paragraph()
        line.add_run(clean(label) + ": ").bold = True
        line.add_run(clean(value))
    doc.add_paragraph()
    paras = paragraphs(segments)
    if paras:
        parts = sections(paras)
        for part in parts:
            if len(parts) > 1:
                doc.add_heading(part["title"], level=1)
            for para in part["paragraphs"]:
                line = doc.add_paragraph()
                line.add_run(f"[{clock(para['start'])}] ").bold = True
                line.add_run(clean(para["text"]))
    else:
        for chunk in text_paragraphs(text) or ["This transcript is empty."]:
            doc.add_paragraph(clean(chunk))
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
