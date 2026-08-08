"""Take an MCQ test and review it.

State lives in st.session_state, not the database, until the test is submitted.
An abandoned test therefore leaves no trace — a half-finished paper is not
evidence about what the student knows.
"""

from __future__ import annotations

import time

import streamlit as st

from src.config import settings
from src.marking.mcq_marker import mark_paper
from src.questions.models import OPTION_KEYS
from src.questions.paper_builder import PAPER_1_QUESTION_COUNT, build_paper
from src.store.db import Store
from src.syllabus.models import SyllabusSpine

st.set_page_config(page_title="MCQ Practice · 9708", page_icon="📝", layout="wide")


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


spine = get_spine()
store = get_store()

st.title("MCQ Practice")

if spine is None:
    st.error("No syllabus spine — run `python scripts/build_syllabus_spine.py` first.")
    st.stop()

bank = store.bank_counts_by_topic()
banked_total = sum(bank.values())

if banked_total == 0:
    st.warning("The question bank is empty.")
    st.code("python scripts/bank_questions.py --all --per-topic 3", language="bash")
    st.caption(
        "Generation is a batch job so that taking a test never spends tokens "
        "or waits on a model."
    )
    st.stop()

# ---------------------------------------------------------------- setup

if "paper" not in st.session_state:
    st.caption(f"{banked_total} questions banked across {len(bank)} topics.")

    # The Concept Tutor's "Practise it" button leaves a topic code here, so a
    # student who has just read an explanation can be tested on it without
    # hunting for it. It seeds the pickers rather than locking them: arriving
    # focused on one topic and then wanting to widen is a normal thing to do,
    # and a disabled control makes that look impossible.
    handover = st.session_state.pop("practice_topic", None)
    if handover:
        st.session_state["mcq_chapters"] = [handover.split(".")[0]]
        st.session_state["mcq_topics"] = [handover]

    chapter_titles = {u.code: u.title for u in spine.units}
    topic_titles = {t.code: t.title for t in spine.iter_topics()}

    st.markdown("**Where the questions come from**")
    chapters = st.multiselect(
        "Chapters (leave empty for the whole syllabus)",
        options=list(chapter_titles),
        format_func=lambda c: (
            f"Chapter {c} · {chapter_titles[c]} "
            f"({sum(n for code, n in bank.items() if code.split('.')[0] == c)})"
        ),
        key="mcq_chapters",
    )

    # Topics inside the chosen chapters — or every topic when no chapter is
    # chosen, so a single topic can be picked without first finding its
    # chapter.
    topic_pool = [
        code for code in topic_titles
        if not chapters or code.split(".")[0] in chapters
    ]
    # A topic left selected after its chapter is deselected is not in the
    # options any more, and Streamlit raises on that rather than ignoring it.
    st.session_state["mcq_topics"] = [
        code for code in st.session_state.get("mcq_topics", []) if code in topic_pool
    ]
    topics = st.multiselect(
        "Topics (leave empty for every topic in those chapters)",
        options=topic_pool,
        format_func=lambda c: f"{c} {topic_titles[c]} ({bank.get(c, 0)})",
        key="mcq_topics",
    )
    st.caption("The number after each name is how many questions are banked for it.")

    topic_filter = topics or (topic_pool if chapters else None)

    available = len(
        store.candidate_questions(
            paper_key="paper_1", topic_codes=topic_filter, exclude_answered=True
        )
    )

    col1, col2 = st.columns(2)
    with col1:
        mode = st.radio(
            "Question selection",
            ["targeted", "balanced"],
            format_func=lambda m: {
                "targeted": "Targeted — weight toward weak and untested topics",
                "balanced": "Balanced — mirror the syllabus",
            }[m],
        )
    with col2:
        if available == 0:
            st.error(
                "No unanswered questions in that selection. Widen it, or bank "
                "more with `scripts/bank_questions.py`."
            )
            st.stop()
        ceiling = min(available, PAPER_1_QUESTION_COUNT)
        count = st.slider(
            "Number of questions", 1, max(ceiling, 1), min(10, ceiling)
        )
        timed = st.checkbox(
            "Timed (2 minutes per question, as in Paper 1)", value=False
        )
        st.caption(f"{available} unanswered questions available in this selection.")

    if st.button("Start test", type="primary"):
        paper = build_paper(
            store, spine, count=count, mode=mode, topic_codes=topic_filter,
        )
        if not paper.questions:
            st.error(
                "No unanswered questions match that selection. Bank more with "
                "`scripts/bank_questions.py`, or widen the chapter filter."
            )
            st.stop()
        st.session_state.paper = paper
        st.session_state.answers = {}
        st.session_state.started_at = time.time()
        st.session_state.timed = timed
        st.session_state.marked = None
        st.rerun()
    st.stop()

paper = st.session_state.paper

# --------------------------------------------------------------- review

if st.session_state.get("marked"):
    result = st.session_state.marked
    st.metric("Score", f"{result.score} / {result.total}", f"{result.percent}%")

    wrong = result.wrong_answers()
    if not wrong:
        st.success("Every question correct.")
    else:
        st.subheader(f"Review — {len(wrong)} to look at")

    for answer in result.answers:
        icon = "✅" if answer.is_correct else ("⬜" if answer.was_skipped else "❌")
        topic = spine.topic(answer.topic_code)
        label = f"{icon}  Q{answer.ordinal} · {answer.topic_code} {topic.title if topic else ''}"
        with st.expander(label, expanded=not answer.is_correct):
            st.markdown(answer.stem)
            if answer.was_skipped:
                st.info("Not answered.")
            elif not answer.is_correct:
                st.markdown(f"**You chose {answer.selected}.** {answer.rationale_selected}")
            st.markdown(f"**Correct answer: {answer.correct}.** {answer.rationale_correct}")

    st.divider()
    by_topic = result.by_topic()
    st.subheader("This test, by topic")
    for code, (correct, answered) in sorted(by_topic.items()):
        topic = spine.topic(code)
        st.markdown(
            f"- **{code} {topic.title if topic else ''}** — {correct}/{answered}"
        )

    if st.button("New test"):
        for key in ("paper", "answers", "started_at", "marked", "timed"):
            st.session_state.pop(key, None)
        st.rerun()
    st.stop()

# ----------------------------------------------------------- taking it

elapsed = time.time() - st.session_state.started_at
answered = len(st.session_state.answers)

header = st.container()
with header:
    cols = st.columns([2, 1, 1])
    cols[0].progress(answered / len(paper.questions), text=f"{answered} of {len(paper.questions)} answered")
    cols[1].metric("Elapsed", f"{int(elapsed // 60)}m {int(elapsed % 60)}s")
    if st.session_state.timed:
        limit = len(paper.questions) * 120
        remaining = max(0, limit - elapsed)
        cols[2].metric("Remaining", f"{int(remaining // 60)}m {int(remaining % 60)}s")
        if remaining == 0:
            st.warning("Time is up — submit now.")

if paper.shortfall:
    st.info(
        f"The bank could only supply {len(paper.questions)} questions "
        f"({paper.shortfall} short). Generate more to sit a full paper."
    )

st.divider()

for ordinal, chosen in enumerate(paper.questions, start=1):
    item = chosen.item
    st.markdown(f"**Q{ordinal}.** {item.stem}")
    choice = st.radio(
        "Select one",
        options=OPTION_KEYS,
        format_func=lambda k, opts=item.options: f"{k}.  {opts[k]}",
        index=None,
        key=f"q_{ordinal}",
        label_visibility="collapsed",
    )
    if choice:
        st.session_state.answers[ordinal] = choice
    st.divider()

unanswered = len(paper.questions) - len(st.session_state.answers)
if unanswered:
    st.caption(f"{unanswered} question(s) still unanswered — they will score zero.")

if st.button("Submit and mark", type="primary"):
    attempt_id = store.start_attempt(
        mode="mcq_test",
        paper_key="paper_1",
        time_limit_secs=len(paper.questions) * 120 if st.session_state.timed else None,
    )
    st.session_state.marked = mark_paper(
        store, paper, st.session_state.answers, attempt_id=attempt_id
    )
    st.cache_data.clear()
    st.rerun()
