"""Generate Paper 2 Section B/C essay questions from the syllabus spine.

Same posture as the MCQ engine: generation is a batch job (`scripts/bank_essays.py`),
never part of the request path, and nothing generated is trusted. A Section B/C
essay is two parts — (a) 8 marks and (b) 12 marks — and each part is banked as
its own question row, linked by a `group_id` in the rubric. Marking a part is
the natural unit of work, per-topic performance stays meaningful, and the
existing schema needs no migration.

Part (a) carries the explanation and, where the economics needs one, a diagram
specification: which diagram, which curve moves, which way, and what happens to
each axis variable. That spec is what `marking/diagram.py` checks the student's
declaration against, so it is validated hard here — a spec written in invented
vocabulary would silently mark every correct diagram wrong.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..llm.provider import LLMProvider
from ..marking.diagram import CURVES, DIAGRAM_TYPES, DIRECTIONS, EFFECTS, DiagramSpec
from ..store.db import Store, new_id
from ..syllabus.assessment import section_focus_for_unit
from ..syllabus.models import SyllabusSpine, Topic

PART_A_MARKS = 8
PART_B_MARKS = 12

# Command words Cambridge uses for the two halves of a Section B/C essay.
PART_A_COMMAND_WORDS = {"explain", "analyse", "describe", "calculate", "define"}
PART_B_COMMAND_WORDS = {"discuss", "assess", "evaluate", "consider", "justify"}


class EssayValidationError(ValueError):
    """A generated essay was rejected. Reported with a reason, never repaired."""


SYSTEM_PROMPT = """You are an experienced Cambridge International AS Level \
Economics (9708) examiner writing a Paper 2 Section B or Section C essay.

Format rules you must follow:
- The essay has exactly two parts: (a) worth 8 marks and (b) worth 12 marks.
- Part (a) asks the candidate to explain or analyse. It never asks for judgement.
- Part (b) asks for judgement — discuss, assess or evaluate — and must be \
answerable from both sides. A part (b) with only one defensible answer is a \
defective question.
- Part (b) must follow on from part (a) without repeating it.
- Use British spelling and Cambridge terminology.
- Never mention the syllabus, topic numbers, units or assessment objectives.
- Do not write model answers. Write the question only.

If, and only if, part (a) genuinely requires a diagram, specify it in \
structured form so it can be checked mechanically.

Return ONLY a JSON object. No prose, no markdown fences."""

SCHEMA = """The object must have exactly these keys:
  "part_a":         string, the wording of part (a)
  "part_a_command": one of: explain, analyse, describe, calculate, define
  "part_b":         string, the wording of part (b)
  "part_b_command": one of: discuss, assess, evaluate, consider, justify
  "outcome_code":   string, the learning outcome code the essay is built on
  "diagram":        either null, or an object:
      {{"diagram_type": one of [{diagram_types}],
        "shifts": array of {{"curve": one of [{curves}],
                            "direction": one of [{directions}]}},
        "effects": object mapping an axis variable name to one of \
[{effects}],
        "required": true}}"""


def schema_text() -> str:
    return SCHEMA.format(
        diagram_types=", ".join(sorted(DIAGRAM_TYPES)),
        curves=", ".join(CURVES),
        directions=", ".join(DIRECTIONS),
        effects=", ".join(EFFECTS),
    )


@dataclass
class EssayItem:
    topic_code: str
    part_a: str
    part_a_command: str
    part_b: str
    part_b_command: str
    outcome_code: str | None = None
    diagram: DiagramSpec | None = None

    def group_id(self) -> str:
        return new_id("e")


@dataclass
class EssayReport:
    requested: int = 0
    banked: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"requested {self.requested}, banked {self.banked}, "
            f"rejected {len(self.rejected)}"
        )


def build_prompt(topic: Topic, focus: str) -> str:
    outcomes = "\n".join(f"- {o.code}: {o.searchable_text()}" for o in topic.outcomes)
    return f"""Write one Paper 2 Section {'B' if focus == 'micro' else 'C'} essay \
({focus}economics) on the topic below.

Topic {topic.code}: {topic.title}

Learning outcomes to draw from (use the codes exactly as given):
{outcomes}

{schema_text()}"""


def parse_response(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise EssayValidationError("response contained no JSON object")
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise EssayValidationError("expected a JSON object")
    return payload


SYLLABUS_LEAK = re.compile(
    r"\b(syllabus|assessment objective|AO[123]\b|topic \d+\.\d+|unit \d+)\b",
    re.IGNORECASE,
)


def validate_diagram_spec(raw: dict) -> DiagramSpec:
    """Reject a spec written in vocabulary the checker does not know.

    This is the rule that matters most in this file. A diagram spec using an
    invented curve name would pass silently at generation time and then mark
    every correct student declaration as wrong, because the comparison is exact.
    """
    diagram_type = str(raw.get("diagram_type", "")).strip()
    if diagram_type not in DIAGRAM_TYPES:
        raise EssayValidationError(f"unknown diagram type {diagram_type!r}")

    shifts = raw.get("shifts") or []
    if not isinstance(shifts, list):
        raise EssayValidationError("shifts must be a list")
    known_curves = {c.upper() for c in CURVES}
    for s in shifts:
        curve = str(s.get("curve", "")).strip().upper()
        direction = str(s.get("direction", "")).strip().lower()
        if curve not in known_curves:
            raise EssayValidationError(f"unknown curve {curve!r} in diagram spec")
        if direction not in DIRECTIONS:
            raise EssayValidationError(f"unknown shift direction {direction!r}")

    effects = raw.get("effects") or {}
    if not isinstance(effects, dict):
        raise EssayValidationError("effects must be an object")
    for var, effect in effects.items():
        if str(effect).strip().lower() not in EFFECTS:
            raise EssayValidationError(f"unknown effect {effect!r} for {var!r}")
    if not shifts and not effects:
        raise EssayValidationError("diagram spec states nothing to check")

    return DiagramSpec.from_dict({**raw, "required": True})


def validate(item: EssayItem, *, known_topic_codes: set[str] | None = None) -> None:
    if known_topic_codes is not None and item.topic_code not in known_topic_codes:
        raise EssayValidationError(f"topic {item.topic_code!r} is not in the spine")

    for label, text in (("part (a)", item.part_a), ("part (b)", item.part_b)):
        if len(text.strip()) < 20:
            raise EssayValidationError(f"{label} is too short to be a real question")
        if SYLLABUS_LEAK.search(text):
            raise EssayValidationError(f"{label} refers to the syllabus, not the economics")

    if item.part_a_command.lower() not in PART_A_COMMAND_WORDS:
        raise EssayValidationError(
            f"part (a) command word {item.part_a_command!r} is not an "
            "explanation command word"
        )
    if item.part_b_command.lower() not in PART_B_COMMAND_WORDS:
        raise EssayValidationError(
            f"part (b) command word {item.part_b_command!r} carries no judgement — "
            "a 12-mark part that asks only for explanation cannot reach AO3"
        )
    # A part (b) that repeats part (a) wastes half the essay.
    if _overlap(item.part_a, item.part_b) > 0.8:
        raise EssayValidationError("part (b) largely repeats part (a)")


def _overlap(a: str, b: str) -> float:
    wa = {w for w in re.findall(r"[a-z]+", a.lower()) if len(w) > 3}
    wb = {w for w in re.findall(r"[a-z]+", b.lower()) if len(w) > 3}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def to_item(raw: dict, topic_code: str) -> EssayItem:
    diagram_raw = raw.get("diagram")
    diagram = validate_diagram_spec(diagram_raw) if isinstance(diagram_raw, dict) else None
    return EssayItem(
        topic_code=topic_code,
        part_a=str(raw.get("part_a", "")).strip(),
        part_a_command=str(raw.get("part_a_command", "")).strip().lower(),
        part_b=str(raw.get("part_b", "")).strip(),
        part_b_command=str(raw.get("part_b_command", "")).strip().lower(),
        outcome_code=(raw.get("outcome_code") or None),
        diagram=diagram,
    )


class EssayGenerator:
    def __init__(self, provider: LLMProvider, store: Store, spine: SyllabusSpine):
        self.provider = provider
        self.store = store
        self.spine = spine
        self._topic_codes = set(spine.topic_codes)

    def generate_for_topic(self, topic_code: str, count: int = 1) -> EssayReport:
        topic = self.spine.topic(topic_code)
        if topic is None:
            raise ValueError(f"topic {topic_code!r} is not in the spine")

        focus = section_focus_for_unit(topic.unit_code)
        section_key = "B" if focus == "micro" else "C"
        report = EssayReport(requested=count)

        for _ in range(count):
            response = self.provider.generate(
                build_prompt(topic, focus),
                system=SYSTEM_PROMPT,
                max_tokens=900,
                temperature=0.7,
            )
            try:
                item = to_item(parse_response(response.text), topic.code)
                validate(item, known_topic_codes=self._topic_codes)
            except (EssayValidationError, ValueError, TypeError, AttributeError) as exc:
                report.rejected.append((topic.code, str(exc)))
                continue

            self._bank(item, section_key)
            report.banked += 1

        return report

    def _bank(self, item: EssayItem, section_key: str) -> tuple[str, str]:
        group_id = item.group_id()
        common = dict(
            paper_key="paper_2",
            section_key=section_key,
            topic_code=item.topic_code,
            outcome_code=item.outcome_code,
            origin="generated",
            syllabus_code=self.spine.syllabus_code,
            syllabus_version=self.spine.syllabus_version,
        )
        a_id = self.store.add_question(
            **common,
            command_word=item.part_a_command,
            max_marks=PART_A_MARKS,
            body=json.dumps({"prompt": item.part_a}, ensure_ascii=False),
            rubric=json.dumps(
                {
                    "group_id": group_id,
                    "part": "a",
                    "diagram": item.diagram.as_dict() if item.diagram else None,
                },
                ensure_ascii=False,
            ),
        )
        b_id = self.store.add_question(
            **common,
            command_word=item.part_b_command,
            max_marks=PART_B_MARKS,
            body=json.dumps({"prompt": item.part_b}, ensure_ascii=False),
            rubric=json.dumps({"group_id": group_id, "part": "b", "diagram": None},
                              ensure_ascii=False),
        )
        return a_id, b_id
