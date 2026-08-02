"""Assemble a Paper 1 style MCQ test from the bank.

Two selection modes:

  balanced    mirror the syllabus — questions spread across all topics in
              proportion to how much content each topic holds
  targeted    weight toward weak and untested topics

Targeted is what makes the tool worth more than a question bank: after a few
sittings it stops asking what the student already knows.

Selection is seeded so a paper is reproducible.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ..store.db import Store
from ..syllabus.models import SyllabusSpine
from .models import MCQItem

PAPER_1_QUESTION_COUNT = 30
PAPER_1_MINUTES = 60

# Weight multipliers used in targeted mode.
UNTESTED_WEIGHT = 3.0
WEAK_WEIGHT = 4.0          # below WEAK_THRESHOLD_PCT
WEAK_THRESHOLD_PCT = 60.0
STRONG_WEIGHT = 0.5        # at or above STRONG_THRESHOLD_PCT
STRONG_THRESHOLD_PCT = 85.0


@dataclass
class SelectedQuestion:
    question_id: str
    item: MCQItem


@dataclass
class Paper:
    questions: list[SelectedQuestion]
    mode: str
    minutes: int
    shortfall: int = 0  # how many fewer than requested the bank could supply

    @property
    def marks(self) -> int:
        return len(self.questions)

    def topic_spread(self) -> dict[str, int]:
        spread: dict[str, int] = {}
        for q in self.questions:
            spread[q.item.topic_code] = spread.get(q.item.topic_code, 0) + 1
        return spread


def topic_weights(
    spine: SyllabusSpine,
    store: Store,
    *,
    mode: str = "balanced",
    subject: str = "economics",
) -> dict[str, float]:
    """Relative weight per topic code.

    Balanced mode weights by outcome count, so 4.3 (12 outcomes) gets asked
    about more than 5.1 (1 outcome) — which is how the real paper behaves.
    """
    base = {t.code: max(len(t.outcomes), 1) for t in spine.iter_topics()}
    if mode == "balanced":
        return {code: float(n) for code, n in base.items()}

    if mode != "targeted":
        raise ValueError(f"mode must be 'balanced' or 'targeted', got {mode!r}")

    performance = {
        row["topic_code"]: row for row in store.topic_performance(subject)
    }
    weights: dict[str, float] = {}
    for code, outcome_count in base.items():
        row = performance.get(code)
        if row is None:
            multiplier = UNTESTED_WEIGHT
        elif (row["pct"] or 0) < WEAK_THRESHOLD_PCT:
            multiplier = WEAK_WEIGHT
        elif (row["pct"] or 0) >= STRONG_THRESHOLD_PCT:
            multiplier = STRONG_WEIGHT
        else:
            multiplier = 1.0
        weights[code] = outcome_count * multiplier
    return weights


def build_paper(
    store: Store,
    spine: SyllabusSpine,
    *,
    count: int = PAPER_1_QUESTION_COUNT,
    mode: str = "balanced",
    topic_codes: list[str] | None = None,
    exclude_answered: bool = True,
    seed: int | None = None,
    subject: str = "economics",
) -> Paper:
    rng = random.Random(seed)

    available = store.candidate_questions(
        paper_key="paper_1",
        subject=subject,
        topic_codes=topic_codes,
        exclude_answered=exclude_answered,
    )
    by_topic: dict[str, list[dict]] = {}
    for row in available:
        by_topic.setdefault(row["topic_code"], []).append(row)
    for rows in by_topic.values():
        rng.shuffle(rows)

    weights = topic_weights(spine, store, mode=mode, subject=subject)
    weights = {c: w for c, w in weights.items() if by_topic.get(c)}

    chosen: list[dict] = []
    while len(chosen) < count and weights:
        codes = list(weights)
        picked = rng.choices(codes, weights=[weights[c] for c in codes], k=1)[0]
        pool = by_topic.get(picked) or []
        if not pool:
            weights.pop(picked, None)
            continue
        chosen.append(pool.pop())
        if not pool:
            weights.pop(picked, None)

    rng.shuffle(chosen)
    questions = [
        SelectedQuestion(question_id=row["id"], item=MCQItem.from_row(row))
        for row in chosen
    ]
    return Paper(
        questions=questions,
        mode=mode,
        minutes=PAPER_1_MINUTES,
        shortfall=max(0, count - len(questions)),
    )
