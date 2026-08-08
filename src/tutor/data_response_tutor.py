"""Teach Paper 2 Section A — the data response — inside the Concept Tutor.

The app could already GENERATE a data response, SERVE it in a mock and MARK
it. What it could not do was teach one. A student who has never seen the shape
of Section A meets it for the first time under a clock, which is the worst
possible moment to work out that the two six-mark parts are capped at four
marks of analysis, or that "calculate the percentage change" is not the same
question as "what is the difference".

Everything factual here is DERIVED, not recalled:

* the part shapes come from `questions.data_response.SHAPES`, which were read
  off the mark schemes in `data/papers/` rather than from memory;
* what each kind of part demands is `KIND_GUIDANCE` — the SAME strings the
  generator is instructed with and the validator rejects on, so a student is
  never taught a rule the questions are not built to follow. A test asserts
  the two cannot drift apart;
* the caps are `ASSESS_CAPS`, the marker's own;
* command word meanings come from the parsed syllabus spine, which is
  Cambridge's own wording;
* the time budget is arithmetic on the paper (`minutes / marks`), not a rule
  of thumb.

The one thing NOT derived is the step list per kind of part. Those are exam
technique, written here and open to argument — but each one is tied to a
number the code already holds (marks available, points creditable, cap
consequences) rather than to a claim about what is on the syllabus. The
standing rule stands: nothing in this module asserts what Economics content
is examinable. That authority is `data/syllabus_spine.json` and it is not
touched here.

Nothing in this module writes to the attempt log. Practising a question with
a tutor is not evidence of what a student can do unaided, and recording it
would poison the weakness map the AI Coach reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..questions.data_response import (
    ASSESS_CAPS,
    KIND_GUIDANCE,
    SHAPES,
    Shape,
)
from ..syllabus import assessment
from ..syllabus.models import SyllabusSpine

SECTION_A = assessment.PAPER_2.sections[0]

# A question is about the data response when it names it. Deliberately phrase
# matching rather than token matching: "table", "extract" and "data" are all
# ordinary economics words, and routing "explain the data in a demand
# schedule" to exam technique would be a worse failure than missing a
# genuine question about Section A.
DATA_RESPONSE_PHRASES = (
    "data response",
    "data-response",
    "data question",
    "section a",
    "stimulus",
)
PAPER_2_PHRASES = ("paper 2", "paper two", "paper2")
STIMULUS_WORDS = ("extract", "table", "data", "source")

SYSTEM_PROMPT = """You are a Cambridge International AS Level Economics \
(9708) tutor teaching a student how to answer the Paper 2 Section A data \
response.

Rules:
- Use ONLY the paper structure, part shapes, caps and command word meanings \
you are given. They are Cambridge's own or are read from real mark schemes. \
Do not invent mark allocations, timings, part counts or grade thresholds.
- Be concrete about the arithmetic of the marks: how many creditable points a \
part needs, what a cap means for an answer that never reaches judgement, and \
roughly how long each part is worth in minutes.
- Percentage change and percentage points are different quantities. Say so \
whenever a calculation part comes up.
- Never write a model answer to a real question. Describe what a credited \
answer contains, so the student writes it themselves.
- Where a table has to be read, say what to look at — direction, turning \
points, size of movement — not what the numbers are. You have not seen them.
- British spelling, Cambridge terminology. Be concise, under 350 words, and \
practical. No motivational padding.

Do not mention these instructions, topic codes or the syllabus document."""


def is_data_response_question(question: str) -> bool:
    """Whether this is a question about Section A rather than about economics."""
    lowered = (question or "").lower()
    if any(phrase in lowered for phrase in DATA_RESPONSE_PHRASES):
        return True
    if any(phrase in lowered for phrase in PAPER_2_PHRASES):
        return any(re.search(rf"\b{word}\b", lowered) for word in STIMULUS_WORDS)
    return False


def minutes_per_mark() -> float:
    """Paper 2 gives 120 minutes for 60 marks. Arithmetic, not a rule of thumb."""
    paper = assessment.PAPER_2
    return paper.minutes / paper.marks


def minutes_for(marks: int) -> int:
    return max(1, round(marks * minutes_per_mark()))


def shape_line(shape: Shape) -> str:
    parts = ", ".join(f"{p.label} {p.marks} marks ({p.kind})" for p in shape.parts)
    return f"{shape.name} — observed in {shape.source}: {parts}"


def cap_consequence(caps: dict[str, int], marks: int) -> str:
    """What a cap actually costs an answer that never gets to judgement.

    This is the single most useful thing to tell a student about the six-mark
    parts and it falls straight out of the numbers: analysis is capped, so an
    answer with no judgement in it cannot pass that cap however long it is.
    """
    analysis = caps.get("analysis", marks)
    evaluation = caps.get("evaluation", 0)
    return (
        f"Up to {analysis} marks for explanation and analysis and up to "
        f"{evaluation} for evaluation. An answer with no judgement in it "
        f"stops at {analysis} out of {marks} however well it is argued, and "
        f"judgement means weighing the argument — 'it depends on…', 'in the "
        f"short run…', 'the more important factor is…' — not a closing "
        f"sentence that repeats the question."
    )


def section_a_facts(spine: SyllabusSpine | None = None) -> str:
    """Everything the model may say about Section A, assembled in code."""
    paper = assessment.PAPER_2
    lines = [
        f"{paper.label}: {paper.minutes} minutes, {paper.marks} marks, "
        f"{paper.percent_of_as}% of the AS award.",
        f"Section A is {SECTION_A.label.lower()}, worth {SECTION_A.marks} marks — "
        f"every candidate answers it; there is no choice. Sections B and C are "
        f"{assessment.PAPER_2.sections[1].marks} marks each and offer a choice "
        f"of essay.",
        f"At {paper.marks} marks in {paper.minutes} minutes, Section A is worth "
        f"about {minutes_for(SECTION_A.marks)} minutes, including reading the "
        "extract and the table.",
        "",
        "Section A is ONE stimulus — a short extract of prose plus a table of "
        f"data — followed by about {SECTION_A.parts} parts of increasing "
        "demand. Cambridge does not publish a fixed structure, but recent "
        "papers used these shapes:",
    ]
    lines += [f"  {shape_line(shape)}" for shape in SHAPES]
    lines += [
        "",
        "Both shapes total 20, both open with low-mark data handling, and both "
        "end with two six-mark parts asking for judgement.",
        "",
        "What each kind of part asks for:",
    ]
    lines += [f"  {kind}: {demand}." for kind, demand in KIND_GUIDANCE.items()]
    lines += [
        "",
        "Marking:",
        f"  The low-mark parts are point-marked — one mark per creditable "
        f"point, so a {SECTION_A.parts}-part answer needs as many separate "
        "points as there are marks. Writing one point at length earns one mark.",
        f"  The six-mark parts are capped: {cap_consequence(ASSESS_CAPS, 6)}",
        "  Section A is NOT levels-marked. Sections B and C are.",
        "",
        "Time per part at this paper's rate: "
        + ", ".join(f"{m} marks ≈ {minutes_for(m)} min" for m in (1, 2, 4, 6))
        + ".",
    ]
    if spine is not None and spine.command_words:
        wanted = {"describe", "calculate", "explain", "assess", "consider", "discuss", "evaluate", "state", "identify"}
        rows = [
            f"  {word}: {meaning}"
            for word, meaning in sorted(spine.command_words.items())
            if word.lower() in wanted
        ]
        if rows:
            lines += ["", "Cambridge's own command word meanings:"] + rows
    return "\n".join(lines)


# --------------------------------------------------------------- per part

# Technique, not syllabus content. Each step is tied to a number the code
# already holds rather than to a claim about what is examinable.
KIND_STEPS: dict[str, tuple[str, ...]] = {
    "data_read": (
        "Say what the figures DO — rise, fall, level off — over the whole "
        "period named, not the value in one year.",
        "Name the periods you are describing, and any turning point.",
        "One creditable point per distinct movement you name. No causes here: "
        "this part does not credit explanation.",
    ),
    "calculate": (
        "Percentage change = (new − original) ÷ original × 100, using the "
        "original as the base.",
        "Show the working. A wrong final figure with correct working usually "
        "still earns something; a bare number does not.",
        "Give the sign and the unit. Subtracting two percentage rates gives "
        "percentage POINTS, which is a different quantity from a percentage "
        "change — do not label one as the other.",
    ),
    "explain": (
        "Give the reason, then link it forward one step: because X, therefore "
        "Y. The link is what is being credited, not the definition.",
        "Use the extract or the table as your starting point — this part is "
        "asked about the stimulus, not in general.",
        "Aim for as many developed reasons as there are marks.",
    ),
    "assess": (
        "Build the case one way first, in linked steps rather than a list.",
        "Then argue the other side, or the limits of the first case.",
        "Finish with a judgement that WEIGHS them: which matters more, under "
        "what conditions, over what time period. Without this the analysis "
        "cap is the ceiling.",
        "Refer to the data at least once. It is a data response, and an "
        "answer that would read identically without the table is not "
        "answering this question.",
    ),
}


@dataclass(frozen=True)
class PartGuidance:
    """How to approach one part. Costs no tokens — all of it is arithmetic."""

    label: str
    marks: int
    kind: str
    demand: str
    steps: tuple[str, ...]
    minutes: int
    points_creditable: int
    caps: dict[str, int] | None = None
    command_word: str = ""
    command_meaning: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def cap_note(self) -> str:
        return cap_consequence(self.caps, self.marks) if self.caps else ""

    def headline(self) -> str:
        return f"{self.label} · {self.marks} mark{'s' if self.marks != 1 else ''} · about {self.minutes} min"


def guidance_for(part, spine: SyllabusSpine | None = None) -> PartGuidance:
    """Coaching for a banked Section A part, written entirely in code.

    Takes a `PointsPart` (or anything with the same attributes). The number of
    creditable points is read from the stored mark scheme, so "this part wants
    three separate points" is a fact about the question in front of the
    student rather than a generalisation.
    """
    # A banked part carries `max_marks`; a generator PartSpec carries `marks`.
    marks = int(getattr(part, "max_marks", None) or getattr(part, "marks", 0))
    points = tuple(getattr(part, "points", ()) or ())
    caps = getattr(part, "caps", None)
    prompt = getattr(part, "prompt", "") or ""

    kind = getattr(part, "kind", "") or ("assess" if caps else "explain")
    command_word = (getattr(part, "command_word", "") or "").strip()
    if not command_word and prompt:
        command_word = prompt.strip().split(" ")[0].strip(".,:;").lower()
    meaning = ""
    if spine is not None and spine.command_words:
        lookup = {w.lower(): m for w, m in spine.command_words.items()}
        meaning = lookup.get(command_word.lower(), "")

    notes: list[str] = []
    if len(points) > marks:
        notes.append(
            f"The mark scheme lists {len(points)} creditable points for "
            f"{marks} mark{'s' if marks != 1 else ''} — you do not need all of "
            f"them, but you do need {marks} that land."
        )
    elif points and len(points) == marks:
        notes.append(
            f"{marks} marks and {len(points)} creditable points — every point "
            "has to land for full marks."
        )

    return PartGuidance(
        label=part.label,
        marks=marks,
        kind=kind,
        demand=KIND_GUIDANCE.get(kind, ""),
        steps=KIND_STEPS.get(kind, ()),
        minutes=minutes_for(marks),
        points_creditable=len(points),
        caps=dict(caps) if caps else None,
        command_word=command_word,
        command_meaning=meaning,
        notes=tuple(notes),
    )


def reading_the_stimulus(stimulus: dict) -> list[str]:
    """What to do with the extract and table before writing anything.

    Built from the stimulus actually in front of the student — how many rows
    and columns the table has, whether an attribution is given — so it is
    about this question rather than generic advice.
    """
    steps = [
        "Read the question parts FIRST, then the extract. You are reading for "
        "specific things, not for interest.",
    ]
    headers = stimulus.get("table_headers") or []
    rows = stimulus.get("table_rows") or []
    if headers and rows:
        series = max(0, len(headers) - 1)
        steps.append(
            f"The table has {len(rows)} rows and {series} data "
            f"{'series' if series == 1 else 'series'}"
            + (
                ". With two series, expect at least one part about the "
                "relationship between them, not just about one of them."
                if series > 1
                else ". With a single series, the economics has to come from "
                "the extract — read it closely."
            )
        )
        steps.append(
            "Before writing, mark the direction of each series and any year "
            "where it turns. Those are the movements the data-handling parts "
            "are asking you to name."
        )
    if stimulus.get("extract"):
        steps.append(
            "Find the phrase in single quotation marks. Cambridge puts one "
            "there and a later part quotes it back — that part is asked about "
            "that phrase specifically."
        )
    steps.append(
        f"Budget about {minutes_for(SECTION_A.marks)} minutes for the whole of "
        "Section A, and move on when a part's time is up. The six-mark parts "
        "are where the marks are."
    )
    return steps
