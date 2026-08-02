"""Generate Paper 1 style MCQs from the syllabus spine.

Generation is a BATCH job, never part of serving a test. `scripts/bank_questions.py`
fills the bank; the app reads from it. That keeps the request path free of LLM
calls entirely, which matters on a free tier with a daily token ceiling.

Nothing generated is trusted: every item passes the deterministic validator
before it is banked, and options are reshuffled so the model's positional bias
does not become the student's answering strategy.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass

from ..llm.provider import LLMProvider
from ..store.db import Store
from ..syllabus.models import SyllabusSpine, Topic
from .models import OPTION_KEYS, MCQItem
from .validator import ValidationError, validate

SYSTEM_PROMPT = """You are an experienced Cambridge International AS Level \
Economics (9708) examiner writing Paper 1 multiple-choice questions.

Paper 1 rules you must follow:
- Exactly four options, labelled A, B, C, D. Exactly one is correct.
- Never use "all of the above", "none of the above", or "both A and B" forms.
- Distractors must be plausible to a student who holds a specific, nameable \
misconception — not obviously wrong, and not joke answers.
- Keep all four options similar in length. A correct answer that is visibly \
longer than the distractors is a defective question.
- Test economic understanding, not recall of syllabus wording. Never mention \
the syllabus, topic numbers, or units in the question.
- Use British spelling and Cambridge terminology.
- Some questions should require a short calculation or the reading of a small \
data set stated inside the stem.

Return ONLY a JSON array. No prose, no markdown fences, no explanation."""

ITEM_SCHEMA = """Each array element must be an object with exactly these keys:
  "stem":        string, the question
  "options":     object with keys "A","B","C","D", each a string
  "answer_key":  one of "A","B","C","D"
  "outcome_code": string, the specific learning outcome code tested
  "rationales":  object with keys "A","B","C","D". For the correct option
                 explain why it is right; for each distractor name the specific
                 misconception a student would hold to choose it."""


@dataclass
class GenerationReport:
    """What happened in one batch. Rejections are surfaced, never swallowed."""

    requested: int = 0
    parsed: int = 0
    banked: int = 0
    rejected: list[tuple[str, str]] = None  # (stem preview, reason)

    def __post_init__(self):
        if self.rejected is None:
            self.rejected = []

    @property
    def rejection_rate(self) -> float:
        return len(self.rejected) / self.parsed if self.parsed else 0.0

    def summary(self) -> str:
        return (
            f"requested {self.requested}, parsed {self.parsed}, "
            f"banked {self.banked}, rejected {len(self.rejected)}"
        )


def build_prompt(topic: Topic, count: int) -> str:
    outcomes = "\n".join(
        f"- {o.code}: {o.searchable_text()}" for o in topic.outcomes
    )
    return f"""Write {count} AS Level Economics Paper 1 multiple-choice questions \
on the topic below.

Topic {topic.code}: {topic.title}

Learning outcomes to draw from (use the codes exactly as given):
{outcomes}

Spread the questions across different outcomes rather than clustering on one.

{ITEM_SCHEMA}"""


def parse_response(text: str) -> list[dict]:
    """Extract the JSON array from a model response.

    Models add fences and preamble despite instructions, so strip them rather
    than failing the whole batch.
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not match:
            raise ValidationError("response contained no JSON array")
        payload = json.loads(match.group(0))

    if isinstance(payload, dict):
        payload = payload.get("questions") or payload.get("items") or [payload]
    if not isinstance(payload, list):
        raise ValidationError("expected a JSON array of questions")
    return payload


def to_item(raw: dict, topic_code: str) -> MCQItem:
    options = raw.get("options") or {}
    if isinstance(options, list):  # some models return a list despite the schema
        options = dict(zip(OPTION_KEYS, options))
    return MCQItem(
        stem=str(raw.get("stem", "")).strip(),
        options={k: str(v).strip() for k, v in options.items()},
        answer_key=str(raw.get("answer_key", "")).strip().upper()[:1],
        topic_code=topic_code,
        outcome_code=(raw.get("outcome_code") or None),
        command_word=(raw.get("command_word") or None),
        rationales={k: str(v).strip() for k, v in (raw.get("rationales") or {}).items()},
    )


class MCQGenerator:
    def __init__(
        self,
        provider: LLMProvider,
        store: Store,
        spine: SyllabusSpine,
        *,
        seed: int | None = None,
    ):
        self.provider = provider
        self.store = store
        self.spine = spine
        self.rng = random.Random(seed)
        self._topic_codes = set(spine.topic_codes)

    def generate_for_topic(self, topic_code: str, count: int = 5) -> GenerationReport:
        topic = self.spine.topic(topic_code)
        if topic is None:
            raise ValueError(f"topic {topic_code!r} is not in the spine")

        report = GenerationReport(requested=count)
        response = self.provider.generate(
            build_prompt(topic, count),
            system=SYSTEM_PROMPT,
            max_tokens=400 * count,
            temperature=0.7,  # higher than usual: identical questions are useless
        )
        raw_items = parse_response(response.text)
        report.parsed = len(raw_items)

        for raw in raw_items:
            try:
                item = to_item(raw, topic.code)
                validate(item, known_topic_codes=self._topic_codes)
            except (ValidationError, ValueError, AttributeError, TypeError) as exc:
                preview = str(raw.get("stem", ""))[:60] if isinstance(raw, dict) else str(raw)[:60]
                report.rejected.append((preview, str(exc)))
                continue

            item = item.shuffled(self.rng)
            self.store.add_question(
                paper_key="paper_1",
                section_key="mcq",
                topic_code=item.topic_code,
                outcome_code=item.outcome_code,
                command_word=item.command_word,
                max_marks=1,
                body=item.body_json(),
                answer_key=item.answer_key,
                origin="generated",
                syllabus_code=self.spine.syllabus_code,
                syllabus_version=self.spine.syllabus_version,
            )
            report.banked += 1

        return report
