"""Domain model for a parsed Cambridge syllabus spine.

The spine is the taxonomy every other part of the system hangs off:
every question, every answer and every mark is tagged to an outcome code.

NOTE ON COPYRIGHT: these objects are containers only. No Cambridge text is
committed to this repository. The spine JSON is generated locally from the
user's own copy of the syllabus PDF and is git-ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class LearningOutcome:
    """A leaf node, e.g. code "4.3.8"."""

    code: str
    text: str
    bullets: tuple[str, ...] = ()

    @property
    def topic_code(self) -> str:
        return ".".join(self.code.split(".")[:2])

    @property
    def unit_code(self) -> str:
        return self.code.split(".")[0]

    def searchable_text(self) -> str:
        """Outcome text plus its bullets — used to build the topic lexicon."""
        return " ".join((self.text, *self.bullets)).strip()


@dataclass
class Topic:
    """A sub-topic, e.g. code "4.3"."""

    code: str
    title: str
    outcomes: list[LearningOutcome] = field(default_factory=list)

    @property
    def unit_code(self) -> str:
        return self.code.split(".")[0]


@dataclass
class Unit:
    """A top-level unit, e.g. code "4"."""

    code: str
    title: str
    topics: list[Topic] = field(default_factory=list)


@dataclass
class SyllabusSpine:
    """The whole parsed spine for one level of one syllabus version."""

    syllabus_code: str
    syllabus_version: str
    level: str
    units: list[Unit] = field(default_factory=list)
    command_words: dict[str, str] = field(default_factory=dict)
    source_file: str = ""
    generated_at: str = ""

    # ---- traversal -------------------------------------------------

    def iter_topics(self) -> Iterator[Topic]:
        for unit in self.units:
            yield from unit.topics

    def iter_outcomes(self) -> Iterator[LearningOutcome]:
        for topic in self.iter_topics():
            yield from topic.outcomes

    def topic(self, code: str) -> Topic | None:
        return next((t for t in self.iter_topics() if t.code == code), None)

    def outcome(self, code: str) -> LearningOutcome | None:
        return next((o for o in self.iter_outcomes() if o.code == code), None)

    @property
    def topic_codes(self) -> list[str]:
        return [t.code for t in self.iter_topics()]

    def counts(self) -> dict[str, int]:
        return {
            "units": len(self.units),
            "topics": sum(len(u.topics) for u in self.units),
            "outcomes": sum(len(t.outcomes) for t in self.iter_topics()),
            "command_words": len(self.command_words),
        }

    # ---- persistence -----------------------------------------------

    def to_json(self) -> str:
        payload = asdict(self)
        payload["generated_at"] = self.generated_at or datetime.now(
            timezone.utc
        ).isoformat()
        return json.dumps(payload, indent=2, ensure_ascii=False)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "SyllabusSpine":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        units = [
            Unit(
                code=u["code"],
                title=u["title"],
                topics=[
                    Topic(
                        code=t["code"],
                        title=t["title"],
                        outcomes=[
                            LearningOutcome(
                                code=o["code"],
                                text=o["text"],
                                bullets=tuple(o.get("bullets", ())),
                            )
                            for o in t["outcomes"]
                        ],
                    )
                    for t in u["topics"]
                ],
            )
            for u in raw["units"]
        ]
        return cls(
            syllabus_code=raw["syllabus_code"],
            syllabus_version=raw["syllabus_version"],
            level=raw["level"],
            units=units,
            command_words=raw.get("command_words", {}),
            source_file=raw.get("source_file", ""),
            generated_at=raw.get("generated_at", ""),
        )
