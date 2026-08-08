"""Turn a Cambridge Principal Examiner Report into usable mistake lines.

WHY THIS EXISTS. Every `common_mistakes` line in the knowledge base so far was
written by a model from the syllabus outcomes — a plausible guess at what
loses marks. An examiner report is the real thing: what candidates actually
did wrong, observed across a whole cohort by the people marking it.

THREE RULES, all enforced, not merely intended.

1. NOTHING CAMBRIDGE WROTE IS EVER STORED. The PDF is read locally from
   `data/papers/` (git-ignored, your own copy). What lands in the database is
   a paraphrase, and `shares_long_shingle` rejects any output that reuses a
   run of words from the source. The extracted text is held in memory for the
   length of one script run and never written anywhere.

2. AS PAPERS ONLY. A June report covers all twelve components, including
   9708/31-43, which are A Level. Ingesting those would push A Level content
   into an AS knowledge base — the same failure that produced the Lorenz curve
   episode. Papers are filtered by component number AND by the level printed
   in the header, and the two must agree.

3. THE SPINE STILL DECIDES. Every produced line goes through the same
   out-of-scope check the notes generator uses, derived from the parsed
   syllabus rather than hard-coded here.

Mapping to topics is lexical, using the retriever the tutor already uses. A
line that matches nothing confidently is kept as general exam technique with
no topic, which is honest — many of the best observations in these reports
("candidates ignored the command word") belong to no single topic anyway.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from ..llm.provider import LLMProvider
from ..syllabus.models import SyllabusSpine

# Component numbers. 1x and 2x are the AS papers; 3x and 4x are A Level.
AS_COMPONENTS = re.compile(r"^[12]\d$")
PAPER_HEADER = re.compile(r"Paper\s+(\d{4})/(\d{2})\s*\n\s*(.+)")
LEVEL_IN_HEADER = re.compile(r"\bAS Level\b", re.IGNORECASE)
A_LEVEL_IN_HEADER = re.compile(r"(?<!AS\s)\bA[\s-]?Level\b", re.IGNORECASE)

SECTION_HEADS = ("Key messages", "General comments", "Comments on specific questions")
QUESTION_HEAD = re.compile(r"^Question\s+(\d+)\s*$", re.MULTILINE)
PART_HEAD = re.compile(r"^\((?:[a-z]|[ivx]+)\)", re.MULTILINE)
QUESTION_INLINE = re.compile(r"\bQuestion\s+(\d+)\b")

MAX_MISTAKE_CHARS = 240
MIN_MISTAKE_CHARS = 25
SHINGLE = 8

TECHNIQUE = "technique"
MISCONCEPTION = "misconception"


class ExaminerError(ValueError):
    """The report could not be read, or a produced line was rejected."""


@dataclass(frozen=True)
class PaperSection:
    code: str  # "9708/21"
    component: str  # "21"
    title: str
    level: str  # "AS" | "A"
    body: str

    @property
    def is_as(self) -> bool:
        return self.level == "AS"


@dataclass(frozen=True)
class Observation:
    """A chunk of examiner prose, held in memory only."""

    paper: str
    ref: str  # "Key messages" | "Question 1" | "Question 3(a)"
    kind: str
    text: str


@dataclass(frozen=True)
class Mistake:
    """A paraphrased line, safe to store."""

    text: str
    kind: str
    paper: str
    ref: str
    topic_code: str | None = None
    confidence: float = 0.0

    def fingerprint(self, source: str) -> str:
        raw = f"{source}|{self.paper}|{self.topic_code or ''}|{self.text.lower()}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


@dataclass
class IngestReport:
    papers_seen: int = 0
    papers_used: int = 0
    observations: int = 0
    written: int = 0
    duplicates: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"papers {self.papers_used}/{self.papers_seen} (AS only), "
            f"observations {self.observations}, written {self.written}, "
            f"duplicates {self.duplicates}, rejected {len(self.rejected)}"
        )


# ---- reading -----------------------------------------------------------


def read_pdf(path) -> str:
    try:
        import pdfplumber
    except ImportError as exc:  # pragma: no cover
        raise ExaminerError("pdfplumber is required to read the report") from exc
    with pdfplumber.open(str(path)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    if not any(p.strip() for p in pages):
        raise ExaminerError(
            f"no text layer in {path} — this looks like a scan, not the "
            "published PDF"
        )
    return "\n".join(pages)


def strip_furniture(text: str) -> str:
    """Remove the running header and footer repeated on every page."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Cambridge International"):
            continue
        if "Principal Examiner Report" in stripped:
            continue
        if re.fullmatch(r"©\s*\d{4}", stripped):
            continue
        if re.fullmatch(r"\d{4}\s+Economics\s+\w+\s+\d{4}", stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def split_papers(text: str) -> list[PaperSection]:
    """One section per component, with its level resolved twice.

    The header line and the component number must agree. They always have so
    far, but a level read from one source alone is a level that can be wrong
    silently, and this is the gate keeping A Level content out.
    """
    matches = list(PAPER_HEADER.finditer(text))
    sections = []
    for i, match in enumerate(matches):
        syllabus, component, title = match.group(1), match.group(2), match.group(3).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end]

        by_number = "AS" if AS_COMPONENTS.match(component) else "A"
        if LEVEL_IN_HEADER.search(title):
            by_title = "AS"
        elif A_LEVEL_IN_HEADER.search(title):
            by_title = "A"
        else:
            by_title = by_number  # header says nothing; trust the number

        if by_title != by_number:
            raise ExaminerError(
                f"component {component} says {by_number} by number but "
                f"{by_title!r} in its header ({title!r}) — refusing to guess "
                "which, because getting this wrong puts A Level content into "
                "an AS knowledge base"
            )
        sections.append(
            PaperSection(
                code=f"{syllabus}/{component}",
                component=component,
                title=title,
                level=by_number,
                body=body,
            )
        )
    return sections


def _named_section(body: str, head: str) -> str:
    start = body.find(head)
    if start < 0:
        return ""
    start += len(head)
    ends = [body.find(other, start) for other in SECTION_HEADS if body.find(other, start) > 0]
    return body[start: min(ends)] if ends else body[start:]


def split_observations(paper: PaperSection) -> list[Observation]:
    """Chunk one paper into things worth paraphrasing.

    Two kinds come out, and they are genuinely different: 'Key messages' are
    exam technique that applies everywhere, while the per-question comments
    carry topic-specific misconceptions.
    """
    out: list[Observation] = []

    for head in ("Key messages", "General comments"):
        block = _named_section(paper.body, head).strip()
        if len(block) > MIN_MISTAKE_CHARS:
            out.append(
                Observation(paper=paper.code, ref=head, kind=TECHNIQUE, text=block)
            )

    specific = _named_section(paper.body, "Comments on specific questions")
    if specific:
        marks = list(QUESTION_HEAD.finditer(specific))
        if marks:
            for i, mark in enumerate(marks):
                end = marks[i + 1].start() if i + 1 < len(marks) else len(specific)
                chunk = specific[mark.end():end].strip()
                if len(chunk) > MIN_MISTAKE_CHARS:
                    out.append(
                        Observation(
                            paper=paper.code,
                            ref=f"Question {mark.group(1)}",
                            kind=MISCONCEPTION,
                            text=chunk,
                        )
                    )
        else:
            # MCQ papers comment question by question in RUNNING PROSE, with
            # no heading to split on. Left as one 2-3k chunk covering four
            # unrelated questions, the topic mapping is meaningless — the
            # chunk matches everything weakly and nothing well. Split on the
            # inline "Question N" that opens each comment instead.
            inline = list(QUESTION_INLINE.finditer(specific))
            for i, mark in enumerate(inline):
                end = inline[i + 1].start() if i + 1 < len(inline) else len(specific)
                chunk = specific[mark.start():end].strip()
                if len(chunk) > MIN_MISTAKE_CHARS:
                    out.append(
                        Observation(
                            paper=paper.code,
                            ref=f"Question {mark.group(1)}",
                            kind=MISCONCEPTION,
                            text=chunk,
                        )
                    )
            if not inline and len(specific.strip()) > MIN_MISTAKE_CHARS:
                out.append(
                    Observation(
                        paper=paper.code,
                        ref="Comments on specific questions",
                        kind=MISCONCEPTION,
                        text=specific.strip(),
                    )
                )
    return out


# ---- the copyright guard ------------------------------------------------


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def shingles(text: str, n: int = SHINGLE) -> set[tuple[str, ...]]:
    words = _words(text)
    return {tuple(words[i: i + n]) for i in range(len(words) - n + 1)}


def shares_long_shingle(source: str, candidate: str, n: int = SHINGLE) -> bool:
    """Does the output reuse a run of n words from the source?

    This is what makes 'paraphrase, never quote' a property of the pipeline
    rather than an instruction the model may ignore. Eight words is short
    enough to catch a lifted clause and long enough that shared technical
    phrasing does not trip it.
    """
    overlap = shingles(source, n) & shingles(candidate, n)
    return bool(overlap)


# ---- generation ---------------------------------------------------------

SYSTEM_PROMPT = """You are helping a Cambridge AS Level Economics (9708) \
student learn from an examiner's report.

You are given the examiner's observations about one question or one paper. \
Extract the MISTAKES CANDIDATES MADE, and write each one as a single sentence \
of advice in your own words.

Absolute rules:
- Paraphrase. Never reuse the examiner's phrasing. If a sentence of yours \
could be found in the source, rewrite it.
- One mistake per line. Say what candidates did wrong and, where the report \
explains it, why it was wrong.
- Write to the student in the second person or as a general rule. Do not \
mention the examiner, the report, the session or the question number.
- Do not include statistics, percentages of candidates, or option letters.
- If the observations describe no mistake — only what candidates did well — \
return an empty list. An invented mistake is worse than none.
- Only AS Level content. Never mention a concept outside the AS syllabus.

Return ONLY a JSON object. No prose, no markdown fences."""

SCHEMA = """The object must have exactly this key:
  "mistakes": array of strings, each one sentence, at most 200 characters.
             May be empty."""


def build_prompt(observation: Observation, forbidden: list[str]) -> str:
    banned = ""
    if forbidden:
        banned = (
            "\nThese are A Level, not AS. Never mention them:\n"
            + ", ".join(forbidden)
            + "\n"
        )
    return f"""Examiner observations:
\"\"\"
{observation.text}
\"\"\"
{banned}
{SCHEMA}"""


def parse_mistakes(text: str) -> list[str]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ExaminerError("response contained no JSON object")
        payload = json.loads(match.group(0))
    raw = payload.get("mistakes")
    if raw is None or not isinstance(raw, list):
        raise ExaminerError("response had no 'mistakes' list")
    return [str(item).strip() for item in raw if str(item).strip()]


SESSION_LEAK = re.compile(
    r"\b(examiner|mark scheme|the report|candidates were asked|option [A-E]\b"
    r"|question \d|june 20\d\d|november 20\d\d|per cent of)",
    re.IGNORECASE,
)


def validate_line(
    line: str,
    observation: Observation,
    *,
    forbidden: list[str],
) -> None:
    if not MIN_MISTAKE_CHARS <= len(line) <= MAX_MISTAKE_CHARS:
        raise ExaminerError(f"line is {len(line)} characters, expected {MIN_MISTAKE_CHARS}-{MAX_MISTAKE_CHARS}")
    if shares_long_shingle(observation.text, line):
        raise ExaminerError(
            "line reuses a run of words from the report — it must be "
            "paraphrased, not quoted"
        )
    if SESSION_LEAK.search(line):
        raise ExaminerError("line refers to the report or a specific paper rather than the economics")
    lowered = line.lower()
    for term in forbidden:
        if term in lowered:
            raise ExaminerError(f"line teaches A Level content ({term})")


# ---- ingestion ----------------------------------------------------------

# A line has to match a topic clearly to be filed under it. Below this it is
# kept as general exam technique, which is honest: "candidates ignored the
# command word" belongs to no single topic, and filing it under whichever
# topic shared a word would be worse than filing it nowhere.
MAP_FLOOR = 0.16


class ExaminerIngestor:
    def __init__(self, provider: LLMProvider, store, spine: SyllabusSpine, retriever=None):
        from ..tutor.corpus import excluded_phrases, load_note_documents
        from ..tutor.retriever import SpineRetriever

        self.provider = provider
        self.store = store
        self.spine = spine
        self.retriever = retriever or SpineRetriever(
            spine,
            documents=load_note_documents(store, spine),
            excluded_phrases=excluded_phrases(spine),
        )
        from .generator import out_of_scope_terms

        self.forbidden = out_of_scope_terms(spine)

    def map_topic(self, line: str) -> tuple[str | None, float]:
        hits = self.retriever.search(line, k=3)
        hits = [h for h in hits if h.source != "chapter"]
        if not hits or hits[0].score < MAP_FLOOR:
            return None, hits[0].score if hits else 0.0
        return hits[0].topic_code, hits[0].score

    def ingest(
        self,
        observations: list[Observation],
        *,
        source: str,
        report: IngestReport | None = None,
        limit: int | None = None,
    ) -> IngestReport:
        report = report or IngestReport()
        for observation in observations[:limit] if limit else observations:
            report.observations += 1
            try:
                response = self.provider.generate(
                    build_prompt(observation, self.forbidden),
                    system=SYSTEM_PROMPT,
                    max_tokens=900,
                    temperature=0.3,
                )
                lines = parse_mistakes(response.text)
            except ExaminerError as exc:
                report.rejected.append((f"{observation.paper} {observation.ref}", str(exc)))
                continue

            for line in lines:
                try:
                    validate_line(line, observation, forbidden=self.forbidden)
                except ExaminerError as exc:
                    report.rejected.append((f"{observation.paper} {observation.ref}", str(exc)))
                    continue

                topic_code, score = (
                    self.map_topic(line)
                    if observation.kind == MISCONCEPTION
                    else (None, 0.0)
                )
                mistake = Mistake(
                    text=line,
                    kind=observation.kind,
                    paper=observation.paper,
                    ref=observation.ref,
                    topic_code=topic_code,
                    confidence=round(score, 3),
                )
                written = self.store.add_observed_mistake(
                    source=source,
                    paper=mistake.paper,
                    ref=mistake.ref,
                    kind=mistake.kind,
                    text=mistake.text,
                    topic_code=mistake.topic_code,
                    confidence=mistake.confidence,
                    fingerprint=mistake.fingerprint(source),
                )
                if written:
                    report.written += 1
                else:
                    report.duplicates += 1
        return report
