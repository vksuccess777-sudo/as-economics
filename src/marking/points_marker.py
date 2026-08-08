"""Marking a Section A part.

Section A is NOT levels-marked. The mark scheme is a list of creditable
points worth one mark each, with caps on the six-mark parts ("up to 4 marks
for explanation/analysis ... up to 2 marks for evaluation"). So the marker
here is a different shape from the essay marker, and deliberately simpler.

The invariant is the same one that holds everywhere in this project: the
model makes a judgement, the code does the arithmetic. The model is asked
one question per indicative point — was this point made, yes or no — and
never sees a mark, a total or a cap. `award()` counts, applies the caps and
clamps to the part maximum. A model that returns "met" on every point still
cannot award more than the part is worth.

PROVENANCE. The indicative points were written by the generator, not by
Cambridge. Every result records `indicative: true`, and the screens say so.
That is the same posture the essay ladder had before the specimen mark
scheme calibrated it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..llm.provider import LLMProvider

MARKER_VERSION = "section-a-points-1"
MIN_ANSWER_CHARS = 12
BAND_TO_AO = {"knowledge": "AO1", "analysis": "AO2", "evaluation": "AO3"}


class PointsMarkingError(RuntimeError):
    pass


@dataclass(frozen=True)
class PointsPart:
    question_id: str
    label: str
    prompt: str
    max_marks: int
    points: tuple[dict, ...]
    caps: dict[str, int] | None = None
    topic_code: str | None = None
    # `kind` (data_read | calculate | explain | assess) is written by the
    # generator and was being dropped on the way back out. The marker does not
    # need it — it asks the same question of every point — but the Concept
    # Tutor coaches differently on a calculation than on a six-mark judgement,
    # and re-deriving the kind from the wording would be guessing at something
    # already recorded.
    kind: str = ""
    command_word: str = ""

    @classmethod
    def from_row(cls, row) -> "PointsPart":
        rubric = json.loads(row["rubric"] or "{}")
        body = json.loads(row["body"] or "{}")
        keys = row.keys() if hasattr(row, "keys") else ()
        return cls(
            question_id=row["id"],
            label=rubric.get("part", "?"),
            prompt=body.get("prompt", ""),
            max_marks=int(row["max_marks"]),
            points=tuple(rubric.get("points") or ()),
            caps=rubric.get("caps") or None,
            topic_code=row["topic_code"],
            kind=str(rubric.get("kind") or ""),
            command_word=str(row["command_word"] or "") if "command_word" in keys else "",
        )


@dataclass
class MarkedPart:
    question_id: str
    label: str
    max_marks: int
    awarded: int
    met: list[int]
    per_point: list[dict]
    missed_advice: str = ""
    marker_version: str = MARKER_VERSION
    band_marks: dict[str, int] = field(default_factory=dict)

    @property
    def percent(self) -> float:
        return 100.0 * self.awarded / self.max_marks if self.max_marks else 0.0

    def feedback_json(self) -> str:
        return json.dumps(
            {
                "part": self.label,
                "points": self.per_point,
                "band_marks": self.band_marks,
                "advice": self.missed_advice,
                "indicative": True,
            },
            ensure_ascii=False,
        )


def award(part: PointsPart, met_indexes: list[int]) -> tuple[int, dict[str, int]]:
    """Marks from a set of met points. Pure arithmetic, no model in sight."""
    valid = sorted({i for i in met_indexes if 0 <= i < len(part.points)})
    band_counts: dict[str, int] = {}
    for i in valid:
        band = str(part.points[i].get("band", "knowledge"))
        band_counts[band] = band_counts.get(band, 0) + 1

    if part.caps:
        band_marks = {
            band: min(count, part.caps.get(band, part.max_marks))
            for band, count in band_counts.items()
        }
    else:
        band_marks = dict(band_counts)

    total = min(sum(band_marks.values()), part.max_marks)
    return total, band_marks


SYSTEM = """You are assisting a Cambridge AS Level Economics examiner marking \
one part of a Section A data response.

You are given the question, the candidate's answer, and the numbered list of \
points the mark scheme credits. For each point, decide ONE thing: did the \
candidate make it?

Rules:
- Judge the economics, not the writing. Credit a point made in different \
words. Do not credit a point the candidate gestured at but did not make.
- A confident, fluent answer that does not make the point has not made it.
- Do not award marks, totals or grades. You are not told what anything is \
worth, and any number you write will be ignored.

Return ONLY a JSON object. No prose, no markdown fences."""

SCHEMA = """The object must have exactly these keys:
  "judgements": array, one object per numbered point, in order:
      {"index": integer, "met": true or false, "why": string, one short \
sentence}
  "advice": string — one sentence telling the candidate what to add next \
time. No praise."""


def build_prompt(part: PointsPart, answer_text: str) -> str:
    points = "\n".join(
        f"{i}. {p.get('text', '')}" for i, p in enumerate(part.points)
    )
    return f"""Question part {part.label}:
{part.prompt}

Candidate's answer:
\"\"\"
{answer_text.strip()}
\"\"\"

Points the mark scheme credits:
{points}

{SCHEMA}"""


def parse_judgements(text: str, part: PointsPart) -> tuple[list[dict], str]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise PointsMarkingError("marker returned no JSON object")
        payload = json.loads(match.group(0))

    raw = payload.get("judgements")
    if not isinstance(raw, list) or not raw:
        raise PointsMarkingError("marker returned no judgements")

    seen: dict[int, dict] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < len(part.points):
            continue
        seen[index] = {
            "index": index,
            "text": part.points[index].get("text", ""),
            "band": part.points[index].get("band", "knowledge"),
            "met": bool(entry.get("met")),
            "why": str(entry.get("why", "")).strip(),
        }

    # A point the marker skipped is NOT met. Silence is not credit.
    per_point = [
        seen.get(
            i,
            {
                "index": i,
                "text": p.get("text", ""),
                "band": p.get("band", "knowledge"),
                "met": False,
                "why": "not addressed",
            },
        )
        for i, p in enumerate(part.points)
    ]
    return per_point, str(payload.get("advice", "")).strip()


class PointsMarker:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def mark(self, part: PointsPart, answer_text: str) -> MarkedPart:
        answer_text = (answer_text or "").strip()
        if len(answer_text) < MIN_ANSWER_CHARS:
            # No model call: an empty answer is zero by inspection, and a
            # blank is evidence, not missing data.
            return MarkedPart(
                question_id=part.question_id,
                label=part.label,
                max_marks=part.max_marks,
                awarded=0,
                met=[],
                per_point=[
                    {
                        "index": i,
                        "text": p.get("text", ""),
                        "band": p.get("band", "knowledge"),
                        "met": False,
                        "why": "no answer given",
                    }
                    for i, p in enumerate(part.points)
                ],
                missed_advice="Nothing was written for this part.",
            )

        response = self.provider.generate(
            build_prompt(part, answer_text),
            system=SYSTEM,
            max_tokens=900,
            temperature=0.0,
        )
        per_point, advice = parse_judgements(response.text, part)
        met = [p["index"] for p in per_point if p["met"]]
        awarded, band_marks = award(part, met)
        return MarkedPart(
            question_id=part.question_id,
            label=part.label,
            max_marks=part.max_marks,
            awarded=awarded,
            met=met,
            per_point=per_point,
            missed_advice=advice,
            band_marks=band_marks,
        )


def record_part(
    store,
    *,
    attempt_id: str,
    ordinal: int,
    marked: MarkedPart,
    answer_text: str,
    seconds_taken: int | None = None,
) -> None:
    """Write one marked Section A part into the attempt log.

    AO levels stay NULL: Section A is point-marked, so there is no level to
    record, and inventing one would corrupt the AO table on the Coach.
    """
    store.record_response(
        attempt_id=attempt_id,
        question_id=marked.question_id,
        ordinal=ordinal,
        max_marks=marked.max_marks,
        answer_text=answer_text,
        awarded=float(marked.awarded),
        ao_levels=None,
        marker_version=marked.marker_version,
        feedback=marked.feedback_json(),
        seconds_taken=seconds_taken,
    )
