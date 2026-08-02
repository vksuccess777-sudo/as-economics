"""Mark an MCQ attempt. No LLM is involved and none ever should be.

The rationales shown in feedback were written when the question was banked, so
reviewing a completed test costs nothing and works offline. This is the whole
reason MCQ is the first capability built: it fills the attempt log without
touching the token budget.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..questions.paper_builder import Paper
from ..store.db import Store


@dataclass
class MarkedAnswer:
    ordinal: int
    question_id: str
    topic_code: str
    stem: str
    selected: str | None
    correct: str
    is_correct: bool
    awarded: int
    rationale_selected: str
    rationale_correct: str

    @property
    def was_skipped(self) -> bool:
        return self.selected is None


@dataclass
class MarkedPaper:
    attempt_id: str
    answers: list[MarkedAnswer]

    @property
    def score(self) -> int:
        return sum(a.awarded for a in self.answers)

    @property
    def total(self) -> int:
        return len(self.answers)

    @property
    def percent(self) -> float:
        return round(100.0 * self.score / self.total, 1) if self.total else 0.0

    def by_topic(self) -> dict[str, tuple[int, int]]:
        """{topic_code: (correct, answered)}"""
        out: dict[str, tuple[int, int]] = {}
        for a in self.answers:
            correct, answered = out.get(a.topic_code, (0, 0))
            out[a.topic_code] = (correct + a.awarded, answered + 1)
        return out

    def wrong_answers(self) -> list[MarkedAnswer]:
        return [a for a in self.answers if not a.is_correct]


def mark_paper(
    store: Store,
    paper: Paper,
    responses: dict[int, str | None],
    *,
    attempt_id: str,
    seconds_taken: dict[int, int] | None = None,
) -> MarkedPaper:
    """Mark every question in `paper` against `responses` keyed by ordinal.

    An unanswered question scores zero and is still recorded — a skipped
    question is evidence about a topic, not missing data.
    """
    seconds_taken = seconds_taken or {}
    marked: list[MarkedAnswer] = []

    for ordinal, selected in enumerate(
        (responses.get(i + 1) for i in range(len(paper.questions))), start=1
    ):
        chosen = paper.questions[ordinal - 1]
        item = chosen.item
        is_correct = selected is not None and selected == item.answer_key
        awarded = 1 if is_correct else 0

        answer = MarkedAnswer(
            ordinal=ordinal,
            question_id=chosen.question_id,
            topic_code=item.topic_code,
            stem=item.stem,
            selected=selected,
            correct=item.answer_key,
            is_correct=is_correct,
            awarded=awarded,
            rationale_selected=item.rationale_for(selected) if selected else "",
            rationale_correct=item.rationale_for(item.answer_key),
        )
        marked.append(answer)

        store.record_response(
            attempt_id=attempt_id,
            question_id=chosen.question_id,
            ordinal=ordinal,
            max_marks=1,
            answer_text=selected,
            awarded=awarded,
            marker_version="mcq-key-v1",
            feedback=json.dumps(
                {
                    "correct": item.answer_key,
                    "rationale": answer.rationale_correct,
                },
                ensure_ascii=False,
            ),
            seconds_taken=seconds_taken.get(ordinal),
        )

    store.finish_attempt(attempt_id)
    return MarkedPaper(attempt_id=attempt_id, answers=marked)
