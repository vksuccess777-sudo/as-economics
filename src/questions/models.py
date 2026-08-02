"""MCQ domain objects.

An MCQItem is only ever created through the validator, so an item that exists
in the bank has already passed every structural check.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field

OPTION_KEYS = ("A", "B", "C", "D")


@dataclass(frozen=True)
class MCQItem:
    stem: str
    options: dict[str, str]          # {"A": "...", ..., "D": "..."}
    answer_key: str                  # "A" | "B" | "C" | "D"
    topic_code: str
    outcome_code: str | None = None
    command_word: str | None = None
    rationales: dict[str, str] = field(default_factory=dict)

    @property
    def correct_option(self) -> str:
        return self.options[self.answer_key]

    def rationale_for(self, option: str) -> str:
        return self.rationales.get(option, "")

    def shuffled(self, rng: random.Random) -> "MCQItem":
        """Redistribute options so the key is not biased toward one position.

        Models place the correct answer at a favourite position far more often
        than chance. Left alone, a student learns the position rather than the
        economics.
        """
        texts = [self.options[k] for k in OPTION_KEYS]
        correct_text = self.options[self.answer_key]
        rationale_by_text = {
            self.options[k]: self.rationales.get(k, "") for k in OPTION_KEYS
        }

        rng.shuffle(texts)
        options = dict(zip(OPTION_KEYS, texts))
        answer_key = next(k for k, v in options.items() if v == correct_text)
        rationales = {k: rationale_by_text[v] for k, v in options.items()}

        return MCQItem(
            stem=self.stem,
            options=options,
            answer_key=answer_key,
            topic_code=self.topic_code,
            outcome_code=self.outcome_code,
            command_word=self.command_word,
            rationales=rationales,
        )

    # ---- persistence ------------------------------------------------

    def body_json(self) -> str:
        """What goes in question.body. The answer key is stored separately."""
        return json.dumps(
            {
                "stem": self.stem,
                "options": self.options,
                "rationales": self.rationales,
            },
            ensure_ascii=False,
        )

    @classmethod
    def from_row(cls, row) -> "MCQItem":
        body = json.loads(row["body"])
        return cls(
            stem=body["stem"],
            options=body["options"],
            answer_key=row["answer_key"],
            topic_code=row["topic_code"],
            outcome_code=row["outcome_code"],
            command_word=row["command_word"],
            rationales=body.get("rationales", {}),
        )
