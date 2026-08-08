"""Diagnose weaknesses from the attempt log. No model is involved.

The question a student actually needs answered is not "which topics scored
badly" — the dashboard already shows that. It is **why** marks were lost, and
therefore what kind of work fixes it. Re-reading notes on a topic where the
economics is understood but the command word was misread is wasted revision.

So every weakness here is classified into a gap type, and the gap type decides
the remedy:

  CONCEPT      the underlying economics is wrong. Evidence: wrong MCQ options
               whose rationales name a misconception, or a low AO1 level.
               Remedy: read the note, use the Concept Tutor, then re-test.
  APPLICATION  the economics is known but the chain of reasoning does not
               complete. Evidence: low AO2, or diagram caps.
               Remedy: targeted MCQ practice and 8-mark parts, not re-reading.
  EVALUATION   analysis is fine, judgement is absent or unsupported.
               Evidence: low AO3.
               Remedy: 12-mark part (b) practice only.
  RECALL       the topic was once known and has decayed. Evidence: a decent
               score long ago with nothing since.
               Remedy: a short revisit, not re-teaching.
  UNTESTED     no evidence at all. This is the biggest risk in the whole
               system and the easiest to mistake for strength.

Everything is computed from rows already in the database. The most valuable
input is the rationale attached to the distractor the student actually chose,
written at banking time: it names the specific misconception held. A topic
percentage says where marks went; that rationale says why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..store.db import Store
from ..syllabus.models import SyllabusSpine

# Thresholds. Deliberately explicit and in one place: every one of them is a
# judgement call, and a reader should be able to disagree with it precisely.
MIN_EVIDENCE = 3            # answers before a percentage means anything
WEAK_PCT = 60.0             # at or below this, the topic is a weakness
STRONG_PCT = 85.0
LOW_AO_LEVEL = 1.5          # average level at or below this is a gap
STALE_DAYS = 21             # untouched this long and a good score is stale

CONCEPT = "CONCEPT"
APPLICATION = "APPLICATION"
EVALUATION = "EVALUATION"
RECALL = "RECALL"
UNTESTED = "UNTESTED"

GAP_LABELS = {
    CONCEPT: "Concept not secure",
    APPLICATION: "Concept known, analysis incomplete",
    EVALUATION: "Analysis fine, judgement missing",
    RECALL: "Known but stale",
    UNTESTED: "No evidence yet",
}

GAP_REMEDIES = {
    CONCEPT: "Read the topic note, work through it with the Concept Tutor, "
             "then re-test with a targeted MCQ set.",
    APPLICATION: "Skip the reading. Do targeted MCQs and 8-mark parts until "
                 "the chains complete on their own.",
    EVALUATION: "Write 12-mark part (b) answers only. Force a judgement and "
                "state what it depends on.",
    RECALL: "One short revisit of the note, then a 10-question check. Do not "
            "spend a full session here.",
    UNTESTED: "Sit a targeted MCQ set on this topic before deciding anything "
              "about it.",
}


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


@dataclass
class Weakness:
    topic_code: str
    topic_title: str
    gap: str
    pct: float | None
    answered: int
    evidence: list[str] = field(default_factory=list)
    priority: float = 0.0

    @property
    def label(self) -> str:
        return GAP_LABELS[self.gap]

    @property
    def remedy(self) -> str:
        return GAP_REMEDIES[self.gap]

    @property
    def is_thin(self) -> bool:
        return self.answered < MIN_EVIDENCE


@dataclass
class Diagnosis:
    weaknesses: list[Weakness] = field(default_factory=list)
    command_word_gaps: list[dict] = field(default_factory=list)
    ao_gaps: list[dict] = field(default_factory=list)
    misconceptions: list[dict] = field(default_factory=list)
    skipped: int = 0
    diagram_failures: int = 0
    topics_total: int = 0
    topics_covered: int = 0
    marks_awarded: float = 0.0
    marks_available: float = 0.0

    @property
    def has_evidence(self) -> bool:
        return self.marks_available > 0

    @property
    def percent(self) -> float:
        if not self.marks_available:
            return 0.0
        return round(100.0 * self.marks_awarded / self.marks_available, 1)

    @property
    def coverage_percent(self) -> float:
        if not self.topics_total:
            return 0.0
        return round(100.0 * self.topics_covered / self.topics_total, 1)

    def by_gap(self, gap: str) -> list[Weakness]:
        return [w for w in self.weaknesses if w.gap == gap]

    def ranked(self, limit: int | None = None) -> list[Weakness]:
        ordered = sorted(self.weaknesses, key=lambda w: -w.priority)
        return ordered[:limit] if limit else ordered


def _ao_averages(store: Store, subject: str) -> dict[str, float | None]:
    return {r["ao"]: r["avg_level"] for r in store.ao_performance(subject)}


def diagnose(
    store: Store,
    spine: SyllabusSpine,
    *,
    subject: str = "economics",
    now: datetime | None = None,
) -> Diagnosis:
    now = now or datetime.now(timezone.utc)
    titles = {t.code: t.title for t in spine.iter_topics()}
    outcome_count = {t.code: len(t.outcomes) for t in spine.iter_topics()}

    performance = {r["topic_code"]: r for r in store.topic_performance(subject)}
    misconceptions = store.wrong_mcq_selections(subject)
    ao_avg = _ao_averages(store, subject)
    school_counts = store.worksheet_topic_frequency(subject=subject)

    # Misconceptions grouped by topic — the strongest signal available.
    by_topic: dict[str, list[str]] = {}
    for m in misconceptions:
        by_topic.setdefault(m["topic_code"], []).append(m["misconception"])

    diagnosis = Diagnosis(
        misconceptions=misconceptions,
        skipped=store.skipped_count(subject),
        diagram_failures=store.diagram_failures(subject),
        topics_total=len(titles),
        topics_covered=len(performance),
        marks_awarded=sum((r["marks_awarded"] or 0) for r in performance.values()),
        marks_available=sum((r["marks_available"] or 0) for r in performance.values()),
    )

    low_ao1 = (ao_avg.get("AO1") or 99) <= LOW_AO_LEVEL
    low_ao2 = (ao_avg.get("AO2") or 99) <= LOW_AO_LEVEL
    low_ao3 = (ao_avg.get("AO3") or 99) <= LOW_AO_LEVEL

    for code, title in titles.items():
        row = performance.get(code)
        topic_misconceptions = by_topic.get(code, [])

        if row is None:
            weakness = Weakness(
                topic_code=code, topic_title=title, gap=UNTESTED,
                pct=None, answered=0,
                evidence=["Never tested — no evidence either way."],
            )
        else:
            pct = row["pct"] or 0.0
            answered = row["answered"]
            last = _parse_ts(row["last_answered"])
            stale = last is not None and (now - last).days >= STALE_DAYS

            if pct > WEAK_PCT and not stale:
                continue  # not a weakness
            if pct > WEAK_PCT and stale:
                gap = RECALL
                evidence = [
                    f"{pct}% when last tested, but nothing on this topic for "
                    f"{(now - last).days} days."
                ]
            elif topic_misconceptions or low_ao1:
                gap = CONCEPT
                evidence = [
                    f"{pct}% across {answered} answers.",
                    *(f"Chose an option that means: {m}" for m in topic_misconceptions[:3]),
                ]
                if low_ao1:
                    evidence.append(
                        f"AO1 knowledge is averaging level {ao_avg.get('AO1')}."
                    )
            elif low_ao3 and not low_ao2:
                gap = EVALUATION
                evidence = [
                    f"{pct}% across {answered} answers.",
                    f"AO3 evaluation is averaging level {ao_avg.get('AO3')} while "
                    f"AO2 analysis is at {ao_avg.get('AO2')}.",
                ]
            else:
                gap = APPLICATION
                evidence = [f"{pct}% across {answered} answers."]
                if low_ao2:
                    evidence.append(
                        f"AO2 analysis is averaging level {ao_avg.get('AO2')}."
                    )

            weakness = Weakness(
                topic_code=code, topic_title=title, gap=gap,
                pct=pct, answered=answered, evidence=evidence,
            )

        weakness.priority = _priority(
            weakness, outcome_count.get(code, 1), school_counts
        )
        diagnosis.weaknesses.append(weakness)

    diagnosis.command_word_gaps = [
        r for r in store.command_word_performance(subject, min_answered=2)
        if (r["pct"] or 0) <= WEAK_PCT
    ]
    diagnosis.ao_gaps = [
        {"ao": ao, "avg_level": avg}
        for ao, avg in ao_avg.items()
        if avg is not None and avg <= LOW_AO_LEVEL
    ]
    return diagnosis


# Priority weights. A topic that carries more syllabus content is worth more
# exam marks, so two topics at the same score are not equally urgent.
GAP_WEIGHT = {
    CONCEPT: 1.0,
    APPLICATION: 0.8,
    EVALUATION: 0.8,
    UNTESTED: 0.6,
    RECALL: 0.3,
}

# What the school is testing right now is a fourth input, on top of how badly
# it is going, how much of the syllabus it covers, and how confident the score
# is: a topic six worksheet items just landed on is more urgent than an
# equally-weak topic nobody at school has touched this term. Capped so a
# flood of worksheet items on one topic cannot swamp the gap-type weighting
# that everything above is built on.
SCHOOL_BOOST_PER_ITEM = 0.08
SCHOOL_BOOST_CAP = 0.4


def _school_weight(topic_code: str, school_counts: dict[str, int]) -> float:
    count = school_counts.get(topic_code, 0)
    return 1.0 + min(count * SCHOOL_BOOST_PER_ITEM, SCHOOL_BOOST_CAP)


def _priority(
    weakness: Weakness, outcomes: int, school_counts: dict[str, int] | None = None
) -> float:
    """Priority is computed, never chosen by a model.

    Four inputs: how badly it is going, how much of the syllabus it covers,
    how confident we are that the score is real, and whether school is
    currently testing it. Thin evidence is damped rather than ignored — one
    bad answer is a hint, not a verdict. `school_counts` defaults to empty, so
    a deployment with no worksheet history behaves exactly as before.
    """
    shortfall = 1.0 if weakness.pct is None else max(0.0, (100.0 - weakness.pct) / 100.0)
    size = min(outcomes, 12) / 12.0
    confidence = min(weakness.answered, MIN_EVIDENCE) / MIN_EVIDENCE if weakness.answered else 0.5
    school = _school_weight(weakness.topic_code, school_counts or {})
    return round(
        GAP_WEIGHT[weakness.gap]
        * (0.5 + shortfall)
        * (0.5 + size)
        * (0.4 + 0.6 * confidence)
        * school,
        4,
    )
