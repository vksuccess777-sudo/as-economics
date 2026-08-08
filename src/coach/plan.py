"""Turn a diagnosis into a dated revision plan.

The plan is built by code. The ordering comes from `diagnosis.priority`, the
session count from the time actually available, and the activity from the gap
type. A model is not asked what to revise, in what order, or for how long —
those are arithmetic over evidence, and a model asked to do them will produce
something plausible and unfalsifiable instead.

The model's only job is the optional coaching paragraph at the top: a short
piece of prose explaining the shape of the plan. If it fails, is rate limited,
or is not configured, the plan is unchanged and still complete. That is the
test of whether an LLM feature is load-bearing where it should not be.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..llm.provider import LLMProvider
from .diagnosis import (
    APPLICATION,
    CONCEPT,
    EVALUATION,
    RECALL,
    UNTESTED,
    Diagnosis,
    Weakness,
)
from .grades import GradeGap

SESSION_MINUTES = 45

# What a session on each gap type actually consists of. Concrete enough to
# start without deciding anything, and each one ends in a check — a session
# with no check produces a feeling of progress rather than evidence of it.
ACTIVITIES = {
    CONCEPT: (
        "Read the topic note, then work the sticking point with the Concept "
        "Tutor until you can state the chain out loud without looking.",
        "Sit 10 targeted MCQs on this topic. Under 8/10 means go again.",
    ),
    APPLICATION: (
        "No reading. Do 15 targeted MCQs, then write one 8-mark part (a) on "
        "this topic and check every chain ends in a named effect.",
        "The 8-mark part scores AO2 level 2 or better.",
    ),
    EVALUATION: (
        "Write one 12-mark part (b). Force a judgement and state explicitly "
        "what it depends on — time period, elasticity, size of the effect.",
        "The part (b) scores AO3 level 2 or better.",
    ),
    RECALL: (
        "Skim the topic note only — do not re-teach it to yourself.",
        "Sit 10 MCQs. If it is above 80%, close the topic and move on.",
    ),
    UNTESTED: (
        "Sit 10 targeted MCQs cold, before revising anything. The result "
        "decides whether this topic needs a session at all.",
        "Any score is useful. Below 60% promotes it to a concept session.",
    ),
}

DRILL_DIAGRAM = (
    "Diagram drill",
    "For each of supply and demand, AD/AS, PPC, externalities: draw it from "
    "memory, then declare it in the essay page and check the declaration is "
    "accepted. A required diagram missing or wrong caps AO2 every time.",
    "Four diagrams declared correctly in a row.",
)

DRILL_TIMING = (
    "Timing drill",
    "Sit a full 30-question Paper 1 against the clock, answering every "
    "question even when unsure. A blank scores zero; a guess between two "
    "options does not.",
    "Zero questions left blank.",
)

DRILL_COMMAND_WORDS = (
    "Command word drill",
    "For each weak command word, write the first two sentences only of an "
    "answer — enough to prove you are doing what the word asks. 'Discuss' "
    "that begins by explaining has already lost the AO3 marks.",
    "Two sentences per command word that match its meaning in the syllabus.",
)


@dataclass
class Session:
    day: int
    topic_code: str | None
    title: str
    gap: str | None
    what_to_do: str
    check: str

    @property
    def is_drill(self) -> bool:
        return self.topic_code is None


@dataclass
class RevisionPlan:
    sessions: list[Session] = field(default_factory=list)
    days: int = 0
    sessions_per_day: int = 1
    target: str | None = None
    gap: GradeGap | None = None
    narrative: str = ""
    unplanned: list[Weakness] = field(default_factory=list)

    @property
    def total_sessions(self) -> int:
        return len(self.sessions)

    def by_day(self) -> dict[int, list[Session]]:
        out: dict[int, list[Session]] = {}
        for s in self.sessions:
            out.setdefault(s.day, []).append(s)
        return out

    def topics_covered(self) -> list[str]:
        return sorted({s.topic_code for s in self.sessions if s.topic_code})


def sessions_available(days: int, minutes_per_day: int) -> int:
    per_day = max(1, minutes_per_day // SESSION_MINUTES)
    return max(0, days) * per_day


def build_plan(
    diagnosis: Diagnosis,
    *,
    days: int,
    minutes_per_day: int,
    target: str | None = None,
    gap: GradeGap | None = None,
) -> RevisionPlan:
    per_day = max(1, minutes_per_day // SESSION_MINUTES)
    capacity = sessions_available(days, minutes_per_day)

    plan = RevisionPlan(days=days, sessions_per_day=per_day, target=target, gap=gap)
    if capacity == 0:
        return plan

    queue: list[tuple[str | None, str, str | None, str, str]] = []

    # Drills come first when the evidence demands them. A student losing marks
    # to blank answers or missing diagrams gains more from one drill than from
    # any amount of topic revision.
    if diagnosis.skipped:
        title, what, check = DRILL_TIMING
        queue.append((None, f"{title} ({diagnosis.skipped} blank answers so far)",
                      None, what, check))
    if diagnosis.diagram_failures:
        title, what, check = DRILL_DIAGRAM
        queue.append((None, f"{title} ({diagnosis.diagram_failures} capped parts)",
                      None, what, check))
    if diagnosis.command_word_gaps:
        words = ", ".join(r["command_word"] for r in diagnosis.command_word_gaps[:4])
        title, what, check = DRILL_COMMAND_WORDS
        queue.append((None, f"{title}: {words}", None, what, check))

    for weakness in diagnosis.ranked():
        what, check = ACTIVITIES[weakness.gap]
        queue.append(
            (
                weakness.topic_code,
                f"{weakness.topic_code} {weakness.topic_title}",
                weakness.gap,
                what,
                check,
            )
        )

    for index, (topic_code, title, gap_type, what, check) in enumerate(queue[:capacity]):
        plan.sessions.append(
            Session(
                day=index // per_day + 1,
                topic_code=topic_code,
                title=title,
                gap=gap_type,
                what_to_do=what,
                check=check,
            )
        )

    planned = {s.topic_code for s in plan.sessions}
    plan.unplanned = [w for w in diagnosis.ranked() if w.topic_code not in planned]
    return plan


# ------------------------------------------------------------- narrative

NARRATIVE_SYSTEM = """You are a Cambridge AS Level Economics (9708) tutor \
writing a short note to a student at the top of a revision plan that has \
already been decided.

Rules:
- Do NOT propose a different plan, reorder it, add topics or change timings. \
The plan is fixed; you are explaining it.
- Say what the evidence shows, what the plan does about it, and what would \
count as it working.
- Be direct and specific. No motivational filler, no praise for effort not yet \
made.
- If the evidence is thin, say so plainly rather than projecting confidence.
- 120 words maximum. British spelling."""


def build_narrative_prompt(diagnosis: Diagnosis, plan: RevisionPlan) -> str:
    top = plan.sessions[:5]
    lines = [f"- {s.title}" + (f" [{s.gap}]" if s.gap else " [drill]") for s in top]
    grade_line = ""
    if plan.gap:
        grade_line = (
            f"\nTarget grade {plan.gap.target} needs about "
            f"{plan.gap.target_percent:g}%. Current running score "
            f"{plan.gap.current_percent:g}%. {plan.gap.confidence_note}"
        )
    return f"""Evidence so far: {diagnosis.percent:g}% across \
{diagnosis.marks_available:g} marks, covering {diagnosis.topics_covered} of \
{diagnosis.topics_total} topics. {diagnosis.skipped} questions left blank. \
{len(diagnosis.misconceptions)} wrong answers traced to a named misconception.\
{grade_line}

The plan runs {plan.days} day(s), {plan.sessions_per_day} session(s) a day. \
First sessions:
{chr(10).join(lines)}

Write the note."""


def narrate(
    provider: LLMProvider, diagnosis: Diagnosis, plan: RevisionPlan
) -> RevisionPlan:
    """Add a coaching paragraph. Failure here must never lose the plan."""
    if not plan.sessions:
        return plan
    try:
        response = provider.generate(
            build_narrative_prompt(diagnosis, plan),
            system=NARRATIVE_SYSTEM,
            max_tokens=350,
            temperature=0.3,
        )
        plan.narrative = response.text.strip()
    except Exception:  # noqa: BLE001 — commentary is optional by design
        plan.narrative = ""
    return plan
