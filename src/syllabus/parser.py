"""Parse the official Cambridge 9708 syllabus PDF into a SyllabusSpine.

Two layers, deliberately separated:

  extract_text(pdf_path) -> str      PDF-dependent, needs pdfplumber
  parse_text(text, ...)  -> Spine    pure function, fully unit-testable

Keeping the second layer pure is what lets the tricky logic (unit headers,
"continued" repeats, sub-bullets, page furniture) be tested against real
syllabus text without shipping a PDF or any Cambridge content in the repo.

Layout being parsed (2026-2028 syllabus, version 2):

    3 Subject content
    AS Level content
    1 Basic economic ideas and resource allocation (AS Level)
    <unit intro prose>
    1.1 Scarcity, choice and opportunity cost
    1.1.1 fundamental economic problem of scarcity
    1.1.4 basic questions of resource allocation
    • what to produce
    ...
    1 Basic economic ideas and resource allocation (AS Level) continued
    ...
    A Level content
    ...
    Command words
    Command word What it means
    Analyse examine in detail ...
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from .models import LearningOutcome, SyllabusSpine, Topic, Unit

# --- section boundaries -------------------------------------------------

AS_CONTENT_START = re.compile(r"^AS Level content\s*$")
A_LEVEL_CONTENT_START = re.compile(r"^A Level content\s*$")
COMMAND_WORDS_START = re.compile(r"^Command words\s*$")
COMMAND_WORDS_HEADER = re.compile(r"^Command word\s+What it means\s*$")
COMMAND_WORDS_END = re.compile(r"^\d+\s+What else you need to know\s*$")

# --- structural lines ---------------------------------------------------

# "1 Basic economic ideas and resource allocation (AS Level)" / "... continued"
UNIT_RE = re.compile(
    r"^(?P<code>\d{1,2})\s+(?P<title>.+?)\s*\((?:AS|A) Level\)(?:\s+continued)?\s*$"
)
# "1.1 Scarcity, choice and opportunity cost" / "7.6 Different market structures continued"
TOPIC_RE = re.compile(r"^(?P<code>\d{1,2}\.\d{1,2})\s+(?P<title>.+?)(?:\s+continued)?\s*$")
# "4.3.8 shape of the AS curve in the short run ..."
OUTCOME_RE = re.compile(r"^(?P<code>\d{1,2}\.\d{1,2}\.\d{1,2})\s+(?P<text>.*)$")
# "• what to produce"  (also handles -, – used for nested sub-bullets)
BULLET_RE = re.compile(r"^[•\u2022]\s*(?P<text>.+?)\s*$")
SUB_BULLET_RE = re.compile(r"^[-\u2013\u2014]\s*(?P<text>.+?)\s*$")

# Command word rows: "Analyse examine in detail to show meaning, ..."
COMMAND_WORD_RE = re.compile(
    r"^(?P<word>[A-Z][a-z]+)\s+(?P<meaning>[a-z(].*)$"
)

# --- page furniture to discard -----------------------------------------

FURNITURE = (
    re.compile(r"^Cambridge International AS & A Level Economics .* syllabus for"),
    re.compile(r"^Back to contents page"),
    re.compile(r"^www\.cambridgeinternational\.org"),
    re.compile(r"^School feedback:"),
    re.compile(r"^Feedback from:"),
    re.compile(r"^©\s*Cambridge"),
    re.compile(r"^\d{1,3}\s*$"),  # bare page numbers
)

LEVEL_SECTIONS = {
    "AS": (AS_CONTENT_START, A_LEVEL_CONTENT_START),
    "A": (A_LEVEL_CONTENT_START, re.compile(r"^\d+\s+Details of the assessment\s*$")),
}


class SyllabusParseError(RuntimeError):
    """Raised when the PDF does not look like the expected syllabus."""


# ------------------------------------------------------------------ text


def extract_text(pdf_path: str | Path) -> str:
    """Extract a text layer from the syllabus PDF.

    pdfplumber first (layout-aware, handles the two-column overview tables
    more predictably), pypdf as a fallback so the parser still runs on a
    machine where pdfplumber is unavailable.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(
            f"Syllabus PDF not found: {pdf_path}. Download it from "
            "cambridgeinternational.org and place it there — it is not "
            "committed to this repository."
        )

    try:
        import pdfplumber

        pages = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        return "\n".join(pages)
    except ImportError:  # pragma: no cover - fallback path
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path))
        return "\n".join((p.extract_text() or "") for p in reader.pages)


def _clean_lines(text: str) -> list[str]:
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.replace("\u00a0", " ").rstrip()
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not line:
            continue
        if any(rx.search(line) for rx in FURNITURE):
            continue
        out.append(line)
    return out


def _slice_section(lines: list[str], start: re.Pattern, end: re.Pattern) -> list[str]:
    try:
        first = next(i for i, ln in enumerate(lines) if start.match(ln))
    except StopIteration:
        return []
    rest = lines[first + 1 :]
    try:
        last = next(i for i, ln in enumerate(rest) if end.match(ln))
    except StopIteration:
        last = len(rest)
    return rest[:last]


# ----------------------------------------------------------------- parse


def parse_content(lines: list[str]) -> list[Unit]:
    """Turn the cleaned lines of one level's content section into units.

    Order matters: outcome codes (a.b.c) must be tested before topic codes
    (a.b), otherwise "1.1.1 ..." matches TOPIC_RE as topic "1.1".
    """
    units: list[Unit] = []
    by_code: dict[str, Unit] = {}
    topics_by_code: dict[str, Topic] = {}

    current_topic: Topic | None = None
    current_outcome: LearningOutcome | None = None
    pending_bullets: list[str] = []

    def flush_outcome() -> None:
        nonlocal current_outcome, pending_bullets
        if current_outcome is not None and current_topic is not None:
            current_topic.outcomes.append(
                LearningOutcome(
                    code=current_outcome.code,
                    text=current_outcome.text,
                    bullets=tuple(pending_bullets),
                )
            )
        current_outcome = None
        pending_bullets = []

    for line in lines:
        if m := OUTCOME_RE.match(line):
            flush_outcome()
            code = m.group("code")
            topic_code = ".".join(code.split(".")[:2])
            # An outcome can appear before its topic header survives a page
            # break; fall back to the topic implied by the code.
            if current_topic is None or current_topic.code != topic_code:
                current_topic = topics_by_code.get(topic_code) or current_topic
            current_outcome = LearningOutcome(code=code, text=m.group("text").strip())
            continue

        if m := UNIT_RE.match(line):
            flush_outcome()
            code = m.group("code")
            title = m.group("title").strip()
            if code not in by_code:
                unit = Unit(code=code, title=title)
                by_code[code] = unit
                units.append(unit)
            current_topic = None
            continue

        if m := TOPIC_RE.match(line):
            flush_outcome()
            code = m.group("code")
            unit_code = code.split(".")[0]
            if code in topics_by_code:  # "... continued" repeat header
                current_topic = topics_by_code[code]
                continue
            unit = by_code.get(unit_code)
            if unit is None:  # topic before its unit header — tolerate it
                unit = Unit(code=unit_code, title="")
                by_code[unit_code] = unit
                units.append(unit)
            topic = Topic(code=code, title=m.group("title").strip())
            unit.topics.append(topic)
            topics_by_code[code] = topic
            current_topic = topic
            continue

        if current_outcome is not None:
            if m := BULLET_RE.match(line):
                pending_bullets.append(m.group("text"))
                continue
            if m := SUB_BULLET_RE.match(line):
                pending_bullets.append(m.group("text"))
                continue
            # A wrapped line. It continues whichever fragment is open: the
            # last bullet if we are inside a bullet list, otherwise the
            # outcome text itself. Real example that needs this:
            #   6.3.1 ... "• definition of balance and imbalances (deficit and
            #   surplus) in the current account of the balance of" / "payments"
            if line[:1].islower():
                if pending_bullets:
                    pending_bullets[-1] = f"{pending_bullets[-1]} {line}".strip()
                else:
                    current_outcome = LearningOutcome(
                        code=current_outcome.code,
                        text=f"{current_outcome.text} {line}".strip(),
                    )
                continue

    flush_outcome()
    units.sort(key=lambda u: int(u.code))
    for unit in units:
        unit.topics.sort(key=lambda t: [int(p) for p in t.code.split(".")])
    return units


def parse_command_words(lines: list[str]) -> dict[str, str]:
    """Parse the command word table into {word: meaning}."""
    section = _slice_section(lines, COMMAND_WORDS_START, COMMAND_WORDS_END)
    words: dict[str, str] = {}
    current: str | None = None
    started = False
    for line in section:
        if COMMAND_WORDS_HEADER.match(line):
            started = True
            continue
        if not started:
            continue
        if m := COMMAND_WORD_RE.match(line):
            current = m.group("word")
            words[current] = m.group("meaning").strip()
        elif current:  # wrapped continuation of the previous meaning
            words[current] = f"{words[current]} {line}".strip()
    return words


def parse_text(
    text: str,
    *,
    level: str = "AS",
    syllabus_code: str = "9708",
    syllabus_version: str = "2026-2028",
    source_file: str = "",
) -> SyllabusSpine:
    """Pure text -> spine. This is the function the tests exercise."""
    if level not in LEVEL_SECTIONS:
        raise ValueError(f"level must be one of {sorted(LEVEL_SECTIONS)}, got {level!r}")

    lines = _clean_lines(text)
    start, end = LEVEL_SECTIONS[level]
    content = _slice_section(lines, start, end)
    if not content:
        raise SyllabusParseError(
            f"Could not find the '{level} Level content' section. The PDF layout "
            "may have changed, or the text layer may be missing."
        )

    units = parse_content(content)
    if not units:
        raise SyllabusParseError(
            f"Found the '{level} Level content' section but parsed no units."
        )

    return SyllabusSpine(
        syllabus_code=syllabus_code,
        syllabus_version=syllabus_version,
        level=level,
        units=units,
        command_words=parse_command_words(lines),
        source_file=source_file,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def parse_pdf(pdf_path: str | Path, **kwargs) -> SyllabusSpine:
    pdf_path = Path(pdf_path)
    kwargs.setdefault("source_file", pdf_path.name)
    return parse_text(extract_text(pdf_path), **kwargs)
