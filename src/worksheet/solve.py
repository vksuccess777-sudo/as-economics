"""Work out a worksheet item and explain it at AS 9708 standard.

Three decisions shape everything below.

**Solutions are derived, not authoritative.** A school worksheet arrives
without its mark scheme. Nothing here awards a mark, and every solution
carries `provenance="derived"` so the UI can say so. That is not a disclaimer
for its own sake: this project's whole marking design rests on marks being
computed by code from a validated key, and an answer a model produced for an
unseen question is a different kind of object. Treating the two the same would
quietly corrupt the one dashboard the student relies on.

**Essays get a plan, not an essay.** For a twelve-mark "discuss", a finished
answer is the least useful thing to hand over — it can be copied without
thought, and it is exactly the writing the student needs the practice of doing.
So `ESSAY` items return the demand of the question, a paragraph plan, the
evaluation lines available, the diagram required, and what separates a top-band
answer from a middle one. Then the student writes it on the Essay Practice page
and gets it marked properly.

**Scope is advisory here, not a gate.** The Concept Tutor refuses off-syllabus
questions, and should: a student types anything. A worksheet came from their
teacher. Refusing to help with a printed question because the retriever scored
it low would be useless, so scope findings are reported alongside the solution
("this looks like A Level content") and never suppress it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from src.syllabus.models import SyllabusSpine

from .classify import command_word_note, command_words
from .models import ESSAY, MCQ, SHORT, STRUCTURED, Item

MAX_ATTEMPTS = 2
DERIVED = "derived"

# Data-response worksheets put an extract, table or chart above the questions.
# It is not part of any single item but no part can be answered without it, so
# it travels into every prompt on the sheet, bounded so a long extract cannot
# crowd out the syllabus lines.
MAX_STIMULUS_CHARS = 1500


class SolveError(RuntimeError):
    """The model's answer could not be used, after a retry."""


@dataclass
class Solution:
    item_label: str
    kind: str
    answer: str = ""
    working: list[str] = field(default_factory=list)
    evaluation: list[str] = field(default_factory=list)
    diagram: str = ""
    marks_guidance: str = ""
    common_error: str = ""
    mcq_key: str = ""
    option_notes: dict[str, str] = field(default_factory=dict)
    # Computed in code from the retriever — never taken from the model, which
    # invents plausible-looking outcome codes and sends a student to the wrong
    # page with an authoritative-sounding reference.
    topic_code: str = ""
    topic_title: str = ""
    unit_code: str = ""
    unit_title: str = ""
    syllabus_refs: list[str] = field(default_factory=list)
    scope_note: str = ""
    provenance: str = DERIVED
    provider: str = ""
    attempts: int = 1

    @property
    def is_plan(self) -> bool:
        return self.kind == ESSAY


SYSTEM = (
    "You are an experienced Cambridge International AS Level Economics (9708) "
    "teacher helping one student with a worksheet their school set. Answer at "
    "AS standard: correct, specific, and no wider than the AS syllabus. Never "
    "invent a syllabus reference, a mark scheme, or a mark. Reply with one JSON "
    "object and nothing else."
)

SCHEMAS = {
    MCQ: """Reply with exactly this JSON:
{
  "answer": "the letter of the correct option, then a short sentence saying why",
  "mcq_key": "A single letter",
  "option_notes": {"A": "why this option is right or wrong, one line", "B": "...", "C": "...", "D": "..."},
  "working": ["the reasoning that gets you there, one step per string"],
  "common_error": "the misconception that makes a student pick the most tempting wrong option"
}""",
    SHORT: """Reply with exactly this JSON:
{
  "answer": "the answer itself, stated directly in one or two sentences",
  "working": ["the justification, one point per string"],
  "marks_guidance": "how a marker would split the printed marks across those points",
  "common_error": "the commonest wrong answer to this and why it is wrong"
}""",
    STRUCTURED: """Reply with exactly this JSON:
{
  "answer": "what this question is asking for, in one sentence",
  "working": ["the chain of reasoning, one link per string, in order"],
  "diagram": "the diagram to draw: what goes on each axis, which curve shifts and which way, and what happens to price and quantity. Empty string if no diagram is needed.",
  "marks_guidance": "how a marker would split the printed marks",
  "common_error": "where students lose marks on this"
}""",
    ESSAY: """Reply with exactly this JSON:
{
  "answer": "what the question is actually demanding, in one sentence, taking the command word seriously",
  "working": ["a paragraph plan: one string per paragraph, each naming the point and the analysis that supports it"],
  "evaluation": ["the evaluation lines available: counter-arguments, 'it depends on' conditions, short run vs long run, one per string"],
  "diagram": "the diagram expected: axes, which curve shifts, direction, and the effect. Empty string if none is needed.",
  "marks_guidance": "what separates a top-band answer from a middle-band one on this question",
  "common_error": "the commonest way students lose marks here"
}""",
}

REQUIRED_KEYS = {
    MCQ: ("answer", "mcq_key"),
    SHORT: ("answer",),
    STRUCTURED: ("answer", "working"),
    ESSAY: ("answer", "working", "evaluation"),
}


def build_prompt(
    item: Item,
    *,
    spine: SyllabusSpine,
    syllabus_lines: list[str],
    note_lines: list[str] | None = None,
    excluded: list[str] | None = None,
    stimulus: str = "",
    rejection: str | None = None,
) -> str:
    blocks: list[str] = []

    if stimulus.strip():
        blocks.append(
            "Printed at the top of the worksheet (this may be stimulus material "
            "the questions refer to, or it may just be a heading - use it only "
            "if the question needs it):\n" + stimulus.strip()[:MAX_STIMULUS_CHARS]
        )

    if item.context.strip():
        blocks.append(
            "The instruction printed above this question on the worksheet:\n"
            + item.context.strip()
        )

    blocks.append(f"Question {item.label}:\n{item.text.strip()}")

    if item.options:
        blocks.append(
            "Options:\n"
            + "\n".join(f"{k} {v}" for k, v in sorted(item.options.items()))
        )

    if item.marks:
        blocks.append(
            f"The worksheet prints [{item.marks}] for this question. Shape the "
            "answer to that tariff — the number of developed points a marker "
            "would expect."
        )
    else:
        blocks.append(
            "No mark allocation is printed. Do not invent one and do not award "
            "a mark."
        )

    note = command_word_note(item, spine)
    if note:
        blocks.append(
            "Cambridge defines this question's command word as:\n"
            f"{note}\nAnswer that demand exactly — not a lower or higher one."
        )

    if syllabus_lines:
        blocks.append(
            "The AS syllabus content this question sits on (quoted from the "
            "syllabus itself — stay inside it):\n"
            + "\n".join(f"- {line}" for line in syllabus_lines)
        )

    if note_lines:
        blocks.append(
            "Relevant material from the student's own revision notes:\n"
            + "\n".join(f"- {line}" for line in note_lines)
        )

    if excluded:
        blocks.append(
            "The AS syllabus names these but marks them NOT REQUIRED at AS: "
            + ", ".join(sorted(excluded))
            + ". Do not build the answer on them. If the question genuinely "
            "needs one, say so plainly in 'answer' and give the AS-level "
            "treatment instead."
        )

    if item.kind == ESSAY:
        blocks.append(
            "This is extended writing. Do NOT write the essay. The student has "
            "to write it themselves — give them the plan they would need to do "
            "that well, and nothing more finished than a plan."
        )

    if rejection:
        blocks.append(
            f"Your previous attempt was rejected: {rejection}\nFix exactly that "
            "and keep everything else."
        )

    blocks.append(SCHEMAS.get(item.kind, SCHEMAS[STRUCTURED]))
    return "\n\n".join(blocks)


def parse_response(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(),
                     flags=re.MULTILINE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise SolveError("response contained no JSON object")
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise SolveError(f"response was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SolveError("expected a JSON object")
    return payload


def _as_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    return [str(v).strip() for v in value if str(v).strip()]


def validate(payload: dict, item: Item) -> None:
    for key in REQUIRED_KEYS.get(item.kind, ("answer",)):
        if not payload.get(key):
            raise SolveError(f"missing {key!r}")

    if item.kind == MCQ:
        key = str(payload.get("mcq_key", "")).strip().upper()[:1]
        if key not in item.options:
            raise SolveError(
                f"mcq_key {key!r} is not one of the printed options "
                f"({', '.join(sorted(item.options))})"
            )

    if item.kind == ESSAY:
        working = _as_list(payload.get("working"))
        # A single 900-character "plan" is an essay wearing a plan's clothes.
        if any(len(line) > 600 for line in working):
            raise SolveError("plan points are prose paragraphs — keep each to a point")


def solve_item(
    item: Item,
    *,
    provider,
    spine: SyllabusSpine,
    retriever=None,
    excluded: list[str] | None = None,
    stimulus: str = "",
    max_tokens: int = 1400,
) -> Solution:
    """Solve one item. One bounded retry, then give up loudly."""
    syllabus_lines: list[str] = []
    note_lines: list[str] = []
    solution = Solution(item_label=item.label, kind=item.kind)

    if retriever is not None:
        hits = retriever.search(item.full_text(), k=6)
        for hit in hits:
            line = (hit.text or "").strip()
            if hit.source == "syllabus" and line:
                syllabus_lines.append(line)
                if hit.ref and hit.ref not in solution.syllabus_refs:
                    solution.syllabus_refs.append(hit.ref)
            elif hit.source == "note" and line:
                note_lines.append(line[:400])
        topical = [h for h in hits if h.source != "chapter"]
        if topical:
            best = topical[0]
            solution.topic_code = best.topic_code
            solution.topic_title = best.topic_title
            solution.unit_code = best.unit_code
            solution.unit_title = best.unit_title
        if not topical:
            solution.scope_note = (
                "This question does not match anything in the AS 9708 syllabus "
                "closely — it may be A Level content, or from another subject. "
                "Treat the solution below with more caution than usual."
            )

    rejection: str | None = None
    last_error: SolveError | None = None

    for attempt in range(MAX_ATTEMPTS):
        prompt = build_prompt(
            item,
            spine=spine,
            syllabus_lines=syllabus_lines[:8],
            note_lines=note_lines[:4],
            excluded=excluded,
            stimulus=stimulus,
            rejection=rejection,
        )
        response = provider.generate(
            prompt,
            system=SYSTEM,
            max_tokens=max_tokens,
            # Repeating a temperature reproduces the answer that was just
            # rejected, so the retry moves.
            temperature=0.2 if attempt == 0 else 0.5,
        )
        try:
            payload = parse_response(response.text)
            validate(payload, item)
        except SolveError as exc:
            last_error = exc
            rejection = str(exc)
            continue

        solution.answer = str(payload.get("answer", "")).strip()
        solution.working = _as_list(payload.get("working"))
        solution.evaluation = _as_list(payload.get("evaluation"))
        solution.diagram = str(payload.get("diagram", "") or "").strip()
        solution.marks_guidance = str(payload.get("marks_guidance", "") or "").strip()
        solution.common_error = str(payload.get("common_error", "") or "").strip()
        solution.mcq_key = str(payload.get("mcq_key", "") or "").strip().upper()[:1]
        notes = payload.get("option_notes") or {}
        if isinstance(notes, dict):
            solution.option_notes = {
                str(k).strip().upper()[:1]: str(v).strip() for k, v in notes.items()
            }
        solution.provider = getattr(response, "provider", "")
        solution.attempts = attempt + 1
        return solution

    raise SolveError(str(last_error) if last_error else "no usable answer")


def check_mcq(item: Item, solution: Solution, chosen: str) -> bool | None:
    """Compare the student's letter with the derived key, in code.

    Returns None when there is nothing to compare. This is a comparison, not a
    mark: the key came from a model reading a question nobody validated, so it
    is reported as agreement or disagreement and never written to the attempt
    log.
    """
    if not chosen or not solution.mcq_key or not item.options:
        return None
    return chosen.strip().upper()[:1] == solution.mcq_key
