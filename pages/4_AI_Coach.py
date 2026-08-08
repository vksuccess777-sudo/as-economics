"""AI Coach — where things stand, and what to do about it, in one place.

Progress and Coach used to be two separate pages reading the same attempt
log: one a scoreboard, the other a diagnosis with a plan. A student had to
visit both and mentally merge them. A proper edutech product doesn't make
them do that — this page is that merge. Nothing that was on either old page
is dropped; it's ordered so a student reads it top to bottom in the order
they actually need it: snapshot, target, what's wrong, then the plan. The
denser reference views (full topic table, AO/command-word breakdown, sitting
history) are still here, just folded into an expander so they don't compete
with the four things above them.

The reset control lives at the top of this page rather than buried in
settings, because the whole point of it is that a student testing the app
(or genuinely starting over) should be able to see it before they see a
diagnosis built on data they don't want counted.
"""

from __future__ import annotations

import streamlit as st

from src.coach.diagnosis import (
    APPLICATION,
    CONCEPT,
    EVALUATION,
    GAP_LABELS,
    RECALL,
    UNTESTED,
    diagnose,
)
from src.coach.grades import (
    AS_GRADES,
    default_grades,
    gap_to_target,
    resolve_grades_path,
)
from src.coach.plan import build_plan, narrate
from src.config import settings
from src.llm.provider import GroqProvider
from src.store.db import Store
from src.syllabus.models import SyllabusSpine

st.set_page_config(page_title="AI Coach · 9708", page_icon="🎯", layout="wide")

GAP_ICON = {
    CONCEPT: "🔴",
    APPLICATION: "🟠",
    EVALUATION: "🟡",
    RECALL: "🔵",
    UNTESTED: "⚪",
}

# What each AS grade actually represents, in plain terms — shown next to the
# letter so "target grade" is a decision, not a guess at what a letter means.
GRADE_DESCRIPTIONS = {
    "a": "Top band — strong command of theory, analysis and judgement throughout.",
    "b": "Very good — secure knowledge with mostly complete analysis.",
    "c": "Good — solid grasp of the core content, judgement still developing.",
    "d": "Reasonable — the basics are there; analysis needs more consistency.",
    "e": "Pass — foundational understanding, with real gaps still to close.",
}

# ---- milestones ---------------------------------------------------------
# Progress badges, computed from the same numbers already on this page —
# never a separate score, just a friendlier way of reading the one that
# exists. Thresholds are arbitrary and meant to feel reachable one after the
# other, not to model anything about grade boundaries.


def _score_medal(pct: float) -> tuple[str, str, str]:
    if pct >= 90:
        return "🏆", "Legend tier", "90%+ — this is exam-day form. Keep it there."
    if pct >= 75:
        return "🥇", "Gold", "75%+ — strong and consistent. Push for the podium."
    if pct >= 60:
        return "🥈", "Silver", "60%+ — solidly on track. A few more reps to gold."
    if pct >= 40:
        return "🥉", "Bronze", "40%+ — the foundations are holding. Keep stacking marks."
    return "🌱", "Sprouting", "Every economist starts here. First marks are the hardest."


def _mastery_medal(mastered: int, total: int) -> tuple[str, str, str]:
    ratio = mastered / total if total else 0.0
    if ratio >= 1:
        return "👑", "Syllabus cleared", "Every topic secure. Time to sharpen, not learn."
    if ratio >= 0.75:
        return "🎖️", "Home stretch", f"{mastered}/{total} topics secure — nearly the full set."
    if ratio >= 0.5:
        return "🏅", "Halfway hero", f"{mastered}/{total} topics secure — past the midpoint."
    if ratio >= 0.25:
        return "🚩", "Flag planted", f"{mastered}/{total} topics secure — good early ground."
    return "🧭", "Mapping it out", f"{mastered}/{total} topics secure — the map is opening up."


def _accuracy_medal(skipped: int) -> tuple[str, str, str] | None:
    if skipped == 0:
        return "🎯", "Sharpshooter", "Zero blanks — every question got a real answer."
    return None


MIN_EVIDENCE = 3  # answers on a topic before its percentage means anything


@st.cache_resource
def get_store() -> Store:
    store = Store(settings.db_path)
    if not store.is_initialised():
        store.initialise()
    return store


@st.cache_data
def get_spine() -> SyllabusSpine | None:
    if not settings.spine_path.exists():
        return None
    return SyllabusSpine.load(settings.spine_path)


store = get_store()
spine = get_spine()

# A Streamlit server started before an upgrade keeps the old `src` modules in
# sys.modules — page scripts hot-reload, imported modules do not — and
# st.cache_resource keeps handing out a Store built from the old class. The
# result is an AttributeError traceback that looks like a missing file.
REQUIRED_STORE_METHODS = ("note", "wrong_mcq_selections", "skipped_count",
                           "diagram_failures", "ao_performance",
                           "reset_progress")
_stale = [name for name in REQUIRED_STORE_METHODS if not hasattr(Store, name)]
if _stale:
    st.error(
        "This Streamlit server is running code from before the last upgrade "
        f"(Store is missing: {', '.join(_stale)}).\n\n"
        "Stop it with Ctrl+C in the terminal and run `streamlit run Home.py` "
        "again. Reloading the page is not enough — Streamlit re-reads page "
        "scripts but not imported modules."
    )
    st.stop()

st.title("🎯 AI Coach")
st.caption(
    "Where things stand, and exactly what to do next — computed from your "
    "attempt log, not guessed."
)

if spine is None:
    st.error("No syllabus spine — run `python scripts/build_syllabus_spine.py` first.")
    st.stop()

# ---- start fresh -----------------------------------------------------

with st.expander("🔄 Start fresh — reset my progress"):
    st.caption(
        "Wipes every test you've sat and every answer you've given, so scores, "
        "weaknesses, and the target-grade projection all start from zero. "
        "The question bank and knowledge base are untouched — nothing needs "
        "regenerating, and no tokens are spent."
    )
    confirm = st.checkbox(
        "I understand this permanently deletes my attempt history and cannot be undone.",
        key="confirm_reset",
    )
    if st.button("Reset my progress", type="primary", disabled=not confirm):
        result = store.reset_progress()
        st.session_state.pop("confirm_reset", None)
        st.session_state.pop("coach_narrative", None)
        st.session_state.pop("legend_celebrated", None)
        st.success(
            f"Cleared {result['attempts_deleted']} sitting(s) and "
            f"{result['responses_deleted']} answer(s). Starting fresh."
        )
        st.rerun()

# ---- evidence gate ----------------------------------------------------

diagnosis = diagnose(store, spine)

if not diagnosis.has_evidence:
    st.info(
        "Nothing marked yet, so there's nothing to diagnose. Sit one "
        "30-question MCQ paper and this page fills itself."
    )
    st.stop()

titles = {t.code: t.title for t in spine.iter_topics()}
all_codes = spine.topic_codes

# ---- at a glance --------------------------------------------------------

st.subheader("At a glance")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Running score", f"{diagnosis.percent:g}%")
c2.metric("Marks", f"{diagnosis.marks_awarded:g} / {diagnosis.marks_available:g}")
c3.metric(
    "Topics covered",
    f"{diagnosis.topics_covered} / {diagnosis.topics_total}"
    if diagnosis.topics_total else str(diagnosis.topics_covered),
)
c4.metric("Blank answers", diagnosis.skipped)

st.caption(
    "Essay marks are indicative unless the levels ladder has been built from "
    "a Cambridge mark scheme."
)

# ---- milestones --------------------------------------------------------

LEGEND_CSS = """
<style>
@keyframes legend-pulse {
  0%, 100% { transform: scale(1); filter: drop-shadow(0 0 3px #FFD700); }
  50%      { transform: scale(1.14);
             filter: drop-shadow(0 0 16px #FFD700) drop-shadow(0 0 26px #FFA500); }
}
@keyframes legend-shine {
  0%   { background-position: 0% center; }
  100% { background-position: 200% center; }
}
.legend-badge {
  display: inline-block;
  font-size: 1.6rem;
  font-weight: 800;
  line-height: 1.3;
  background: linear-gradient(
    90deg, #B8860B, #FFD700, #FFF8DC, #FFD700, #B8860B
  );
  background-size: 300% auto;
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  animation: legend-pulse 1.5s ease-in-out infinite,
             legend-shine 3s linear infinite;
}
</style>
"""

mastered_topics = max(0, diagnosis.topics_total - len(diagnosis.weaknesses))
badges = [
    _score_medal(diagnosis.percent),
    _mastery_medal(mastered_topics, diagnosis.topics_total),
]
accuracy_badge = _accuracy_medal(diagnosis.skipped)
if accuracy_badge:
    badges.append(accuracy_badge)

st.markdown("**🏅 Milestones**")
badge_cols = st.columns(len(badges))
for col, (emoji, title, message) in zip(badge_cols, badges):
    with col:
        if title == "Legend tier":
            # The one badge that earns a bit of theatre: a shimmering,
            # pulsing title plus a one-off balloon drop. `legend_celebrated`
            # keeps the balloons to once per session rather than firing on
            # every rerun while the score stays above 90% — the badge itself
            # (which animates continuously) carries the ongoing feeling, the
            # balloons mark the moment of arrival.
            st.markdown(LEGEND_CSS, unsafe_allow_html=True)
            st.markdown(
                f'<div class="legend-badge">{emoji} {title}</div>',
                unsafe_allow_html=True,
            )
            if not st.session_state.get("legend_celebrated"):
                st.balloons()
                st.session_state["legend_celebrated"] = True
        else:
            st.markdown(f"### {emoji} {title}")
        st.caption(message)

# ---- target grade ----------------------------------------------------

st.subheader("Target")

grades = default_grades()
col_a, col_b, col_c = st.columns(3)
target = col_a.selectbox(
    "Target grade",
    AS_GRADES,
    index=0,
    format_func=lambda g: f"{g.upper()} — {GRADE_DESCRIPTIONS.get(g, '')}",
)
days = col_b.number_input("Days until the exam", 1, 400, 60)
minutes = col_c.number_input("Minutes a day", 15, 360, 90, step=15)

gap = gap_to_target(grades, diagnosis.percent, target, diagnosis.marks_available)

if not grades.is_official:
    st.caption(
        f"Thresholds from `{resolve_grades_path().name}` are estimates. Cambridge "
        "sets the real ones per session, after the exam."
    )

g1, g2, g3 = st.columns(3)
g1.metric("Grade at this rate", gap.projected_grade.upper() if gap.projected_grade else "Below E")
g2.metric(f"Grade {target.upper()} needs", f"{gap.target_percent:g}%")
g3.metric(
    "Gap",
    "on target" if gap.already_there else f"{gap.gap_percentage_points:g} points",
)

if gap.already_there:
    st.success(
        f"At the current rate this is already at grade {target.upper()}. The risk now is "
        f"coverage, not accuracy — {diagnosis.coverage_percent:g}% of topics have "
        "any evidence at all."
    )
else:
    st.markdown(
        f"**In exam terms:** about **{gap.marks_per_paper_1} more MCQs out of 30** "
        f"on Paper 1 and **{gap.marks_per_paper_2} more marks out of 60** on "
        f"Paper 2. {gap.confidence_note}"
    )

# ---- diagnosis -------------------------------------------------------

st.subheader("What is actually going wrong")
st.caption(
    "Each weakness is classified by the kind of gap, because the remedy differs. "
    "Re-reading notes on a topic where the economics is understood but the "
    "chain does not complete is wasted time."
)

school_counts = store.worksheet_topic_frequency()

ranked = diagnosis.ranked(limit=12)
for w in ranked:
    with st.expander(
        f"{GAP_ICON[w.gap]} {w.topic_code} {w.topic_title} — {w.label}"
        + (f" · {w.pct:g}%" if w.pct is not None else ""),
        expanded=False,
    ):
        for line in w.evidence:
            st.markdown(f"- {line}")
        recent = school_counts.get(w.topic_code, 0)
        if recent:
            st.caption(
                f"Bumped up: {recent} worksheet question(s) on this topic from "
                "school in the last 30 days."
            )
        if w.is_thin and w.answered:
            st.caption(
                f"Only {w.answered} answer(s) here — a hint, not a verdict."
            )
        st.markdown(f"**Do this:** {w.remedy}")

        note = store.note(w.topic_code)
        if note:
            from src.notes.generator import Note

            mistakes = Note.from_row(note).mistakes_text()
            if mistakes:
                st.markdown("**Known traps on this topic**")
                for m in mistakes[:3]:
                    st.markdown(f"- {m}")

gap_counts = {g: len(diagnosis.by_gap(g)) for g in GAP_LABELS}
st.caption(
    " · ".join(
        f"{GAP_ICON[g]} {GAP_LABELS[g]}: {n}" for g, n in gap_counts.items() if n
    )
)

if diagnosis.misconceptions:
    with st.expander(
        f"Specific misconceptions picked ({len(diagnosis.misconceptions)})",
        expanded=False,
    ):
        st.caption(
            "Taken from the wrong option actually chosen. The rationale was "
            "written when the question was banked, so this is what the choice "
            "means, not a guess at it."
        )
        for m in diagnosis.misconceptions[:20]:
            st.markdown(f"- **{m['topic_code']}** — {m['misconception']}")

# ---- deeper breakdown (full scoreboard, AO, command words, history) ----

with st.expander("📊 Deeper breakdown — full scoreboard, AOs, command words, history"):
    rows = store.topic_performance()
    solid = [r for r in rows if r["answered"] >= MIN_EVIDENCE]
    thin = [r for r in rows if r["answered"] < MIN_EVIDENCE]

    st.markdown("**Every topic tested**")
    if solid:
        st.dataframe(
            [
                {
                    "Topic": f"{r['topic_code']} {titles.get(r['topic_code'], '')}",
                    "Score %": r["pct"],
                    "Answered": r["answered"],
                    "Marks": f"{r['marks_awarded']:g}/{r['marks_available']:g}",
                    "Last": (r["last_answered"] or "")[:10],
                }
                for r in sorted(solid, key=lambda r: r["pct"] or 0)
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption(f"No topic has {MIN_EVIDENCE} answers yet.")

    if thin:
        st.caption(
            "Too little evidence to score: "
            + ", ".join(sorted(r["topic_code"] for r in thin))
        )

    if all_codes:
        untested = store.untested_topics(all_codes)
        if untested:
            st.markdown(f"**Never tested — {len(untested)} topics**")
            st.write(
                ", ".join(
                    f"{code} {titles.get(code, '')}".strip() for code in untested
                )
            )
            st.caption(
                "Run an MCQ test in **targeted** mode — it weights selection "
                "toward these before anything else."
            )

    ao_rows = [r for r in store.ao_performance() if r["answered"]]
    if ao_rows:
        st.markdown("**Assessment objectives**")
        st.caption(
            "Average level reached per objective across marked essay parts. "
            "AO1 knowledge, AO2 analysis, AO3 evaluation."
        )
        cols = st.columns(len(ao_rows))
        for col, r in zip(cols, ao_rows):
            col.metric(r["ao"], r["avg_level"], help=f"{r['answered']} parts marked")

    cw_rows = store.command_word_performance()
    if cw_rows:
        st.markdown("**Command words**")
        st.caption(
            "Misreading the command word loses marks the student's knowledge "
            "would otherwise have earned — invisible in a topic-only view."
        )
        st.dataframe(
            [
                {
                    "Command word": r["command_word"],
                    "Score %": r["pct"],
                    "Answered": r["answered"],
                }
                for r in cw_rows
            ],
            use_container_width=True,
            hide_index=True,
        )

    history = store.attempt_history(limit=15)
    if history:
        st.markdown("**Recent sittings**")
        st.dataframe(
            [
                {
                    "When": (h["started_at"] or "")[:16].replace("T", " "),
                    "Type": h["mode"],
                    "Paper": h["paper_key"] or "—",
                    "Score": (
                        f"{h['marks_awarded']:g}/{h['marks_available']:g}"
                        if h["marks_available"] else "—"
                    ),
                    "%": h["pct"],
                }
                for h in history
            ],
            use_container_width=True,
            hide_index=True,
        )

# ---- the plan --------------------------------------------------------

st.subheader("Plan")

plan = build_plan(
    diagnosis, days=int(days), minutes_per_day=int(minutes), target=target, gap=gap
)

if not plan.sessions:
    st.warning("No time available to plan against.")
    st.stop()

st.caption(
    f"{plan.total_sessions} sessions of 45 minutes over {plan.days} days, "
    f"{plan.sessions_per_day} a day. Order is computed from the evidence, not "
    "chosen by a model."
)

if st.button("Add a coaching note", help="Optional. The plan is complete without it."):
    if settings.groq_api_key:
        with st.spinner("Writing…"):
            plan = narrate(
                GroqProvider(settings.groq_api_key, settings.groq_model),
                diagnosis, plan,
            )
        st.session_state.coach_narrative = plan.narrative
    else:
        st.warning("GROQ_API_KEY is not set — the plan below is unaffected.")

if st.session_state.get("coach_narrative"):
    st.info(st.session_state.coach_narrative)

for day, sessions in plan.by_day().items():
    st.markdown(f"**Day {day}**")
    for s in sessions:
        icon = GAP_ICON.get(s.gap, "🏋️") if s.gap else "🏋️"
        st.markdown(f"{icon} **{s.title}**")
        st.markdown(f"   {s.what_to_do}")
        st.caption(f"   Done when: {s.check}")

if plan.unplanned:
    st.caption(
        f"{len(plan.unplanned)} weaker area(s) did not fit in the time given. "
        "Increase the days or minutes to see them scheduled."
    )
