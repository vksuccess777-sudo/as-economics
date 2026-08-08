"""Mark a Paper 2 essay part in two passes.

Pass 1 EXTRACT  reads the question and the student's answer and returns a
                structured account of what the student actually said:
                definitions offered, chains of reasoning attempted, judgements
                made, and anything irrelevant or wrong.

Pass 2 JUDGE    sees the extracted object, the levels descriptors and the
                deterministic diagram verdict — and NOT the prose. It returns a
                level per assessment objective with a justification.

Why two passes rather than one call that returns a mark. A single-pass marker
rewards fluency: a confident, well-written answer with two broken chains reads
better than a plain answer with four complete ones, and the model marks what it
reads. Splitting the passes means the judgement is made against a list of
claims, where a missing link is visible as an absence rather than hidden by
good prose. Pass 2 physically cannot see the writing style — that is enforced
by the function signature, and by a test.

Marks are never emitted by a model. Pass 2 returns levels; `levels.py` turns
levels into marks by table lookup; `diagram.py` caps AO2 by comparison operator
when a required diagram is missing or wrong.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..llm.provider import LLMProvider
from .diagram import DiagramCheck, DiagramDeclaration, DiagramSpec, apply_cap, check_diagram
from .levels import AO_KEYS, Ladder, PartLadder

MARKER_VERSION = "essay-2pass-1"


class MarkingError(RuntimeError):
    """The marker could not produce a trustworthy mark. Never a silent zero."""


# ---------------------------------------------------------------- domain


@dataclass(frozen=True)
class EssayPart:
    """One part of a Section B/C essay — the unit that is marked."""

    question_id: str
    topic_code: str
    part: str                 # "a" | "b"
    prompt: str
    command_word: str | None
    max_marks: int
    diagram: DiagramSpec | None = None

    @classmethod
    def from_row(cls, row) -> "EssayPart":
        body = json.loads(row["body"])
        rubric = json.loads(row["rubric"]) if row["rubric"] else {}
        return cls(
            question_id=row["id"],
            topic_code=row["topic_code"],
            part=rubric.get("part", "a"),
            prompt=body.get("prompt", ""),
            command_word=row["command_word"],
            max_marks=int(row["max_marks"]),
            diagram=DiagramSpec.from_dict(rubric.get("diagram")),
        )


@dataclass
class ExtractedAnswer:
    """Pass 1 output. What the student said, stripped of how well they said it."""

    definitions: list[dict] = field(default_factory=list)
    chains: list[dict] = field(default_factory=list)
    judgements: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    word_count: int = 0

    @classmethod
    def from_dict(cls, raw: dict, word_count: int = 0) -> "ExtractedAnswer":
        if not isinstance(raw, dict):
            raise MarkingError("extraction pass did not return an object")
        return cls(
            definitions=list(raw.get("definitions") or []),
            chains=list(raw.get("chains") or []),
            judgements=list(raw.get("judgements") or []),
            problems=[str(p) for p in (raw.get("problems") or [])],
            word_count=word_count,
        )

    @property
    def complete_chains(self) -> int:
        return sum(1 for c in self.chains if c.get("complete") is True)

    @property
    def supported_judgements(self) -> int:
        return sum(1 for j in self.judgements if j.get("supported") is True)

    def as_dict(self) -> dict:
        return {
            "definitions": self.definitions,
            "chains": self.chains,
            "judgements": self.judgements,
            "problems": self.problems,
            "word_count": self.word_count,
        }

    def render(self) -> str:
        """The only view of the answer pass 2 ever gets."""
        lines: list[str] = [f"Answer length: {self.word_count} words.", ""]

        lines.append("TERMS THE STUDENT DEFINED OR USED:")
        if not self.definitions:
            lines.append("  (none)")
        for d in self.definitions:
            verdict = "accurate" if d.get("correct") else "inaccurate or vague"
            lines.append(f"  - {d.get('term', '?')} — {verdict}. {d.get('note', '')}".rstrip())

        lines.append("")
        lines.append("CHAINS OF REASONING ATTEMPTED:")
        if not self.chains:
            lines.append("  (none)")
        for c in self.chains:
            state = "complete" if c.get("complete") else "incomplete"
            steps = " -> ".join(str(s) for s in (c.get("steps") or []))
            lines.append(f"  - [{state}] {c.get('claim', '?')}")
            if steps:
                lines.append(f"      steps: {steps}")
            if c.get("break_point"):
                lines.append(f"      breaks at: {c['break_point']}")

        lines.append("")
        lines.append("JUDGEMENTS OFFERED:")
        if not self.judgements:
            lines.append("  (none)")
        for j in self.judgements:
            state = "supported" if j.get("supported") else "unsupported"
            lines.append(f"  - [{state}] {j.get('judgement', '?')}")
            if j.get("criteria"):
                lines.append(f"      decided on: {j['criteria']}")

        lines.append("")
        lines.append("IRRELEVANT OR INCORRECT MATERIAL:")
        if self.problems:
            lines.extend(f"  - {p}" for p in self.problems)
        else:
            lines.append("  (none)")
        return "\n".join(lines)


@dataclass
class MarkedEssay:
    question_id: str
    levels: dict[str, int]
    marks_by_ao: dict[str, int]
    awarded: int
    max_marks: int
    justifications: dict[str, str]
    next_steps: list[str]
    diagram: DiagramCheck
    extracted: ExtractedAnswer
    cap_note: str | None = None
    calibrated: bool = False
    marker_version: str = MARKER_VERSION

    @property
    def percent(self) -> float:
        return round(100.0 * self.awarded / self.max_marks, 1) if self.max_marks else 0.0

    def feedback_json(self) -> str:
        return json.dumps(
            {
                "levels": self.levels,
                "marks_by_ao": self.marks_by_ao,
                "justifications": self.justifications,
                "next_steps": self.next_steps,
                "diagram": self.diagram.summary(),
                "cap_note": self.cap_note,
                "calibrated": self.calibrated,
                "extracted": self.extracted.as_dict(),
            },
            ensure_ascii=False,
        )


# ---------------------------------------------------------------- prompts

EXTRACT_SYSTEM = """You are an assistant to a Cambridge AS Level Economics \
(9708) examiner. You do NOT award marks and you do NOT judge quality.

Your only job is to report what the candidate actually wrote, as structured \
data, so that a separate marking step can judge it without being influenced by \
the candidate's writing style.

Rules:
- Report only what is in the answer. Never repair, complete or improve a chain \
of reasoning on the candidate's behalf. An implied step is not a written step.
- A chain is "complete" only if every link is stated AND it ends in a stated \
effect on the variable the question asks about. A chain that stops at "so \
demand changes" without a direction is incomplete.
- A judgement is "supported" only if the answer gives a reason for preferring \
one side, not merely a restatement of both sides followed by "it depends".
- Record economic errors and irrelevant material in "problems".
- Fluency, length and confidence are not your concern. A blunt answer with \
four complete chains and a polished answer with one are reported as exactly \
that.

Return ONLY a JSON object. No prose, no markdown fences."""

EXTRACT_SCHEMA = """The object must have exactly these keys:
  "definitions": array of {"term": string, "correct": boolean, "note": string}
  "chains":      array of {"claim": string, "steps": array of string,
                           "complete": boolean, "break_point": string}
  "judgements":  array of {"judgement": string, "supported": boolean,
                           "criteria": string}
  "problems":    array of string"""

JUDGE_SYSTEM = """You are a Cambridge AS Level Economics (9708) examiner \
marking one part of a Paper 2 essay against a levels-based mark scheme.

You will NOT see the candidate's prose. You will see a structured account of \
what they wrote, plus a verdict on the diagram. Mark what is there.

Rules:
- Award a LEVEL for each assessment objective listed. Never award marks; marks \
are computed from your levels by the system.
- Use only the level descriptors given. Do not invent intermediate levels.
- Absence is evidence. No judgements recorded means AO3 level 0, however \
strong the analysis.
- Do not credit an objective this part does not assess.
- Justify each level in one sentence naming the specific evidence you used.
- Then give at most three "next_steps": concrete, specific actions for this \
answer. "Add more evaluation" is useless; "state what your conclusion depends \
on — the time period, or the size of the elasticity" is useful.

Return ONLY a JSON object. No prose, no markdown fences."""


def build_extract_prompt(part: EssayPart, answer_text: str) -> str:
    return f"""Question ({part.max_marks} marks, command word: {part.command_word or 'not given'}):
{part.prompt}

Candidate's answer:
\"\"\"
{answer_text.strip()}
\"\"\"

{EXTRACT_SCHEMA}"""


def build_judge_prompt(
    part_ladder: PartLadder,
    part: EssayPart,
    extracted: ExtractedAnswer,
    diagram: DiagramCheck,
) -> str:
    """Note the signature: no answer text. Pass 2 cannot see the prose."""
    aos = part_ladder.assessed_aos()
    descriptor_block = []
    for ao in aos:
        band = part_ladder.band(ao)
        descriptor_block.append(f"{ao} (levels 0-{band.max_level}):")
        for level in sorted(band.descriptors):
            descriptor_block.append(f"  {level}: {band.descriptors[level]}")

    not_assessed = [ao for ao in AO_KEYS if ao not in aos]
    not_assessed_line = (
        f"\nThis part does not assess {', '.join(not_assessed)}. Ignore it entirely."
        if not_assessed else ""
    )

    keys = ", ".join(f'"{ao}": {{"level": int, "why": string}}' for ao in aos)

    return f"""Question ({part.max_marks} marks, command word: {part.command_word or 'not given'}):
{part.prompt}

Level descriptors for this part:
{chr(10).join(descriptor_block)}{not_assessed_line}

Diagram: {diagram.summary()}

Structured account of the candidate's answer:
{extracted.render()}

Return a JSON object with exactly these keys:
  {keys}
  "next_steps": array of at most 3 strings"""


# ---------------------------------------------------------------- parsing


def parse_json_object(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise MarkingError("model response contained no JSON object")
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise MarkingError(f"model response was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise MarkingError("expected a JSON object")
    return payload


def parse_levels(payload: dict, part_ladder: PartLadder) -> tuple[dict[str, int], dict[str, str]]:
    levels: dict[str, int] = {}
    why: dict[str, str] = {}
    for ao in part_ladder.assessed_aos():
        block = payload.get(ao)
        if not isinstance(block, dict) or "level" not in block:
            raise MarkingError(f"judging pass returned no level for {ao}")
        try:
            level = int(block["level"])
        except (TypeError, ValueError) as exc:
            raise MarkingError(f"{ao} level was not an integer") from exc
        band = part_ladder.band(ao)
        if level not in band.marks_by_level:
            raise MarkingError(
                f"{ao} level {level} is off the ladder (0-{band.max_level})"
            )
        levels[ao] = level
        why[ao] = str(block.get("why", "")).strip()
    return levels, why


# ---------------------------------------------------------------- marker


class EssayMarker:
    def __init__(self, provider: LLMProvider, ladder: Ladder):
        self.provider = provider
        self.ladder = ladder

    def mark(
        self,
        part: EssayPart,
        answer_text: str,
        declaration: DiagramDeclaration | None = None,
    ) -> MarkedEssay:
        part_ladder = self.ladder.part(part.max_marks)
        diagram = check_diagram(part.diagram, declaration)

        if not (answer_text or "").strip():
            # A blank answer is zero. Spending tokens to discover that is waste,
            # and letting a model "mark" nothing invites a sympathy level.
            zero = {ao: 0 for ao in part_ladder.assessed_aos()}
            return MarkedEssay(
                question_id=part.question_id,
                levels=zero,
                marks_by_ao={ao: 0 for ao in zero},
                awarded=0,
                max_marks=part.max_marks,
                justifications={ao: "No answer was written." for ao in zero},
                next_steps=["Write an answer, even a short one — a blank scores zero."],
                diagram=diagram,
                extracted=ExtractedAnswer(),
                calibrated=self.ladder.is_calibrated,
            )

        word_count = len(answer_text.split())

        extract_response = self.provider.generate(
            build_extract_prompt(part, answer_text),
            system=EXTRACT_SYSTEM,
            max_tokens=1200,
            temperature=0.0,  # extraction is a reading task, not a creative one
        )
        extracted = ExtractedAnswer.from_dict(
            parse_json_object(extract_response.text), word_count=word_count
        )

        judge_response = self.provider.generate(
            build_judge_prompt(part_ladder, part, extracted, diagram),
            system=JUDGE_SYSTEM,
            max_tokens=800,
            temperature=0.0,
        )
        payload = parse_json_object(judge_response.text)
        levels, why = parse_levels(payload, part_ladder)

        levels, cap_note = apply_cap(levels, diagram)
        marks_by_ao = {
            ao: part_ladder.band(ao).marks_for(level) for ao, level in levels.items()
        }
        awarded = sum(marks_by_ao.values())
        if awarded > part.max_marks:  # unreachable if the ladder validates; assert anyway
            raise MarkingError(
                f"computed {awarded} marks for a {part.max_marks}-mark part"
            )

        next_steps = [str(s) for s in (payload.get("next_steps") or [])][:3]

        return MarkedEssay(
            question_id=part.question_id,
            levels=levels,
            marks_by_ao=marks_by_ao,
            awarded=awarded,
            max_marks=part.max_marks,
            justifications=why,
            next_steps=next_steps,
            diagram=diagram,
            extracted=extracted,
            cap_note=cap_note,
            calibrated=self.ladder.is_calibrated,
        )


def record_essay(
    store,
    *,
    attempt_id: str,
    ordinal: int,
    marked: MarkedEssay,
    answer_text: str,
    seconds_taken: int | None = None,
) -> None:
    """Write one marked essay part into the attempt log."""
    store.record_response(
        attempt_id=attempt_id,
        question_id=marked.question_id,
        ordinal=ordinal,
        max_marks=marked.max_marks,
        answer_text=answer_text,
        awarded=marked.awarded,
        ao_levels=marked.levels,
        marker_version=marked.marker_version,
        feedback=marked.feedback_json(),
        seconds_taken=seconds_taken,
    )
