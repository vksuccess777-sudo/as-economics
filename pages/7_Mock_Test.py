"""Sit a full mock exam in the exact Cambridge 9708 pattern.

This is deliberately NOT another configurable practice screen — that already
exists on MCQ Practice and Essay Practice, where count, mode and which essay
to write are all up to the student. A mock test is the opposite exercise: the
shape is fixed to match the real thing, because the whole point is to
rehearse the real thing — Paper 1 exactly as long as Paper 1, Paper 2 with
the same three sections and the same "choose 1 of 2" essay format, one
compulsory Section A.

The ONE dial left in the student's hands is which chapters/units it draws
from. A school follows a lesson plan — Term 1 might only have reached
chapters 1-3 — so a mock sat mid-term needs to be answerable from what has
actually been taught, not the whole syllabus. Every other parameter (question
counts, timings, section structure, choice format) mirrors the real paper and
is not adjustable here.

Marks are not shown until the whole sitting is over, the same way a real exam
gives no feedback between papers. Session state (prefixed `mock_`) carries
the sitting; nothing is written to the database until each component is
submitted for marking, at which point it is recorded exactly like any other
attempt and feeds the same topic/AO performance the AI Coach reads.
"""

from __future__ import annotations

import json
import random
import time

import streamlit as st

from src.config import settings
from src.llm.exceptions import AllProvidersRateLimitedError, LLMRateLimitError
from src.llm.provider import build_provider, transcribe_photo
from src.marking.diagram import (
    CURVES,
    DIAGRAM_TYPES,
    DIRECTIONS,
    EFFECTS,
    DiagramDeclaration,
    Shift,
)
from src.marking.essay_marker import EssayMarker, EssayPart
from src.marking.essay_marker import MarkingError as EssayMarkingError
from src.marking.essay_marker import record_essay
from src.marking.levels import default_ladder, resolve_ladder_path
from src.marking.mcq_marker import mark_paper
from src.marking.mock_report import build_report, shortfall_notes
from src.marking.points_marker import PointsMarker
from src.marking.points_marker import PointsMarkingError as SectionAMarkingError
from src.marking.points_marker import PointsPart, record_part
from src.coach.grades import default_grades
from src.questions.models import OPTION_KEYS
from src.questions.paper_builder import PAPER_1_MINUTES, PAPER_1_QUESTION_COUNT, build_paper
from src.store.db import Store
from src.syllabus import assessment
from src.syllabus.models import SyllabusSpine

st.set_page_config(page_title="Mock Test · 9708", page_icon="🎓", layout="wide")

PAPER_1_MARKS = assessment.PAPER_1.marks              # 30
PAPER_2_MARKS = assessment.PAPER_2.marks              # 60
PAPER_2_MINUTES = assessment.PAPER_2.minutes          # 120
SECTION_A_MARKS = assessment.PAPER_2.sections[0].marks  # 20
SECTION_B_MARKS = assessment.PAPER_2.sections[1].marks  # 20
SECTION_C_MARKS = assessment.PAPER_2.sections[2].marks  # 20
SECTION_LABELS = {"A": "Section A — Data response", "B": "Section B — Micro essay", "C": "Section C — Macro essay"}

MOCK_KEYS = [k for k in st.session_state.keys() if k.startswith("mock_")]


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


@st.cache_resource
def get_ladder():
    return default_ladder()


store = get_store()
spine = get_spine()
ladder = get_ladder()

st.title("🎓 Mock Test")
st.caption(
    "A full sitting in the exact Cambridge 9708 pattern — same section "
    "structure, same timings, same 'choose 1 of 2' essay format as the real "
    "exam. The only thing you can change is which chapters it draws "
    "questions from, so a mock can match Term 1, Term 2, or a class test "
    "instead of the whole syllabus."
)

if spine is None:
    st.error("No syllabus spine — run `python scripts/build_syllabus_spine.py` first.")
    st.stop()


def reset_mock() -> None:
    for key in list(st.session_state.keys()):
        if key.startswith("mock_"):
            del st.session_state[key]


# =========================================================================
# SETUP
# =========================================================================

if "mock_flow" not in st.session_state:

    chapter_titles = {u.code: u.title for u in spine.units}
    topic_titles = {t.code: t.title for t in spine.iter_topics()}
    mcq_bank = store.bank_counts_by_topic(paper_key="paper_1")

    st.markdown("### 1 · What to sit")
    exam_type = st.radio(
        "Exam",
        ["full", "paper1", "paper2"],
        format_func=lambda k: {
            "full": "Full mock — Paper 1 + Paper 2 (3 hours)",
            "paper1": "Paper 1 only — Multiple Choice (1 hour)",
            "paper2": "Paper 2 only — Data Response & Essays (2 hours)",
        }[k],
        horizontal=False,
    )

    st.markdown("### 2 · Coverage")
    st.caption(
        "Leave both empty to draw on the whole syllabus. Choose chapters to "
        "match a term's lesson plan, or narrow to specific topics for a "
        "class test."
    )
    chapters = st.multiselect(
        "Chapters / units (leave empty for the whole syllabus)",
        options=list(chapter_titles),
        format_func=lambda c: f"Chapter {c} · {chapter_titles[c]}",
        key="mock_setup_chapters",
    )
    topic_pool = [
        code for code in topic_titles
        if not chapters or code.split(".")[0] in chapters
    ]
    topics = st.multiselect(
        "Topics (leave empty for every topic in those chapters)",
        options=topic_pool,
        format_func=lambda c: f"{c} {topic_titles[c]} ({mcq_bank.get(c, 0)} MCQs banked)",
        key="mock_setup_topics",
    )
    topic_filter = topics or (topic_pool if chapters else None)

    # ---- availability, computed against the chosen filter -------------
    mcq_available = len(
        store.candidate_questions(paper_key="paper_1", topic_codes=topic_filter, exclude_answered=True)
    )
    a_groups = store.data_response_groups(topic_codes=topic_filter, exclude_answered=True)
    b_groups = store.essay_groups(section_key="B", topic_codes=topic_filter, exclude_answered=True)
    c_groups = store.essay_groups(section_key="C", topic_codes=topic_filter, exclude_answered=True)

    st.markdown("### 3 · What this mock will contain")
    st.caption(
        "Marks below are what Cambridge sets. Anything the bank cannot supply "
        "is still counted in the paper total — a paper you only half sat is "
        "not a paper you scored well on."
    )
    rows = []
    if exam_type in ("full", "paper1"):
        got = min(mcq_available, PAPER_1_QUESTION_COUNT)
        rows.append((
            f"Paper 1 — Multiple Choice · {PAPER_1_MARKS} marks · {PAPER_1_MINUTES} min",
            f"{got} / {PAPER_1_QUESTION_COUNT} questions ({got} of "
            f"{PAPER_1_MARKS} marks)",
            got > 0,
        ))
    if exam_type in ("full", "paper2"):
        for section_label, marks, groups, note in (
            ("Section A — Data response (compulsory)", SECTION_A_MARKS, a_groups, ""),
            ("Section B — Micro essay (choose 1 of 2)", SECTION_B_MARKS, b_groups, ""),
            ("Section C — Macro essay (choose 1 of 2)", SECTION_C_MARKS, c_groups, ""),
        ):
            rows.append((
                f"Paper 2 {section_label} · {marks} marks",
                f"{len(groups)} available{note}" if groups
                else f"none banked — {marks} marks will be skipped",
                bool(groups),
            ))

    for label, status, ok in rows:
        st.markdown(f"{'✅' if ok else '⚠️'} **{label}** — {status}")

    if exam_type in ("full", "paper2"):
        st.caption(f"Paper 2 is {PAPER_2_MARKS} marks in {PAPER_2_MINUTES} minutes.")
    if exam_type == "full":
        st.caption(
            f"A full mock is {PAPER_1_MARKS} + {PAPER_2_MARKS} = "
            f"{PAPER_1_MARKS + PAPER_2_MARKS} marks — the whole AS aggregate."
        )

    if not any(ok for _, _, ok in rows):
        st.error(
            "Nothing is available for that selection. Widen the chapter/"
            "topic filter, or bank more questions first."
        )
        st.stop()

    if st.button("Begin mock test", type="primary"):
        flow: list[str] = []
        if exam_type in ("full", "paper1") and mcq_available > 0:
            flow.append("paper1")
        if exam_type in ("full", "paper2"):
            if a_groups:
                flow.append("section_a")
            if b_groups:
                flow.append("section_b")
            if c_groups:
                flow.append("section_c")

        st.session_state.mock_topic_filter = topic_filter
        st.session_state.mock_exam_type = exam_type
        st.session_state.mock_flow = flow
        st.session_state.mock_flow_idx = 0
        st.session_state.mock_results = {}  # component -> marked result, revealed only in the report
        # Marks actually put in front of the student, per component. Kept
        # separately from the results because a paper the bank could not fill
        # still has to be reported against the marks Cambridge sets.
        st.session_state.mock_set_marks = {}
        st.session_state.mock_paper2_started_at = None
        st.rerun()
    st.stop()

# =========================================================================
# ROUTER
# =========================================================================

flow = st.session_state.mock_flow
idx = st.session_state.mock_flow_idx
topic_filter = st.session_state.mock_topic_filter
stage = flow[idx] if idx < len(flow) else "report"

if stage != "report":
    left, right = st.columns([5, 1])
    with left:
        step_labels = {
            "paper1": "Paper 1 · Multiple Choice",
            "section_a": "Paper 2 · Section A",
            "section_b": "Paper 2 · Section B",
            "section_c": "Paper 2 · Section C",
        }
        st.progress(
            idx / len(flow) if flow else 0.0,
            text=f"Step {idx + 1} of {len(flow)} — {step_labels.get(stage, stage)}",
        )
    with right:
        if st.button("🚪 Exit"):
            reset_mock()
            st.rerun()
    st.divider()


def advance() -> None:
    st.session_state.mock_flow_idx += 1
    st.rerun()


# -------------------------------------------------------------------
# STAGE: Paper 1 — Multiple Choice
# -------------------------------------------------------------------

if stage == "paper1":
    if "mock_paper1_paper" not in st.session_state:
        paper = build_paper(
            store, spine, count=PAPER_1_QUESTION_COUNT, mode="balanced", topic_codes=topic_filter,
        )
        st.session_state.mock_paper1_paper = paper
        st.session_state.mock_paper1_answers = {}
        st.session_state.mock_paper1_started_at = time.time()

    paper = st.session_state.mock_paper1_paper
    st.subheader(f"Paper 1 — Multiple Choice · {PAPER_1_MARKS} marks")
    st.caption(
        f"{len(paper.questions)} questions · {PAPER_1_MINUTES} minutes · "
        f"1 mark each · {assessment.PAPER_1.percent_of_as}% of the AS award"
    )
    if paper.shortfall:
        st.info(
            f"The bank could only supply {len(paper.questions)} of "
            f"{PAPER_1_QUESTION_COUNT} in this selection."
        )

    elapsed = time.time() - st.session_state.mock_paper1_started_at
    limit = PAPER_1_MINUTES * 60
    remaining = max(0, limit - elapsed)
    c1, c2 = st.columns(2)
    c1.metric("Elapsed", f"{int(elapsed // 60)}m {int(elapsed % 60)}s")
    c2.metric("Remaining", f"{int(remaining // 60)}m {int(remaining % 60)}s")
    if remaining == 0:
        st.warning("Time is up — submit now, exactly as you would in the exam hall.")

    st.divider()
    for ordinal, chosen in enumerate(paper.questions, start=1):
        item = chosen.item
        st.markdown(f"**Q{ordinal}.** {item.stem}")
        choice = st.radio(
            "Select one",
            options=OPTION_KEYS,
            format_func=lambda k, opts=item.options: f"{k}.  {opts[k]}",
            index=None,
            key=f"mock_p1_q_{ordinal}",
            label_visibility="collapsed",
        )
        if choice:
            st.session_state.mock_paper1_answers[ordinal] = choice
        st.divider()

    unanswered = len(paper.questions) - len(st.session_state.mock_paper1_answers)
    if unanswered:
        st.caption(f"{unanswered} question(s) still unanswered — they will score zero.")

    if st.button("Submit Paper 1", type="primary"):
        attempt_id = store.start_attempt(
            mode="full_paper", paper_key="paper_1", time_limit_secs=limit,
        )
        marked = mark_paper(store, paper, st.session_state.mock_paper1_answers, attempt_id=attempt_id)
        st.session_state.mock_results["paper1"] = marked
        st.session_state.mock_set_marks["paper1"] = len(paper.questions)
        st.cache_data.clear()
        advance()
    st.stop()

# -------------------------------------------------------------------
# STAGE: Paper 2 header (shown once, on the way into Section A)
# -------------------------------------------------------------------

if stage in ("section_a", "section_b", "section_c"):
    if st.session_state.mock_paper2_started_at is None:
        st.session_state.mock_paper2_started_at = time.time()
    p2_elapsed = time.time() - st.session_state.mock_paper2_started_at
    p2_remaining = max(0, PAPER_2_MINUTES * 60 - p2_elapsed)
    st.subheader(f"Paper 2 — Data Response and Essays · {PAPER_2_MARKS} marks")
    st.caption(
        f"Section A {SECTION_A_MARKS} + Section B {SECTION_B_MARKS} + "
        f"Section C {SECTION_C_MARKS} = {PAPER_2_MARKS} marks in "
        f"{PAPER_2_MINUTES} minutes · {assessment.PAPER_2.percent_of_as}% of "
        "the AS award"
    )
    c1, c2 = st.columns(2)
    c1.metric("Paper 2 elapsed", f"{int(p2_elapsed // 60)}m {int(p2_elapsed % 60)}s")
    c2.metric("Paper 2 remaining", f"{int(p2_remaining // 60)}m {int(p2_remaining % 60)}s")
    if p2_remaining == 0:
        st.warning("Time is up for Paper 2 — submit your current section now.")
    if not ladder.is_calibrated:
        st.caption(
            f"⚠️ Indicative marking — the levels ladder "
            f"(`{resolve_ladder_path().name}`) is not yet built from a "
            "Cambridge mark scheme. Essay marks below are provisional."
        )
    st.divider()

topic_title = {t.code: t.title for t in spine.iter_topics()}


def _diagram_declare_ui(part, key_prefix: str):
    """Same declaration UI as Essay Practice — reused verbatim for parity."""
    if part.diagram is None or not part.diagram.required:
        return None
    with st.expander(f"Declare your diagram for part ({part.part})", expanded=True):
        st.caption(
            "Draw the diagram on paper as normal, then declare it here. The "
            "marker cannot see your drawing — this checks exactly what the "
            "mark scheme rewards: the shift, its direction, and the effect "
            "on each variable."
        )
        dtype = st.selectbox(
            "Which diagram did you draw?",
            ["(none)"] + list(DIAGRAM_TYPES),
            format_func=lambda k: DIAGRAM_TYPES[k]["label"] if k in DIAGRAM_TYPES else k,
            key=f"{key_prefix}_dtype",
        )
        if dtype == "(none)":
            return None
        n_shifts = st.number_input(
            "How many curves shifted?", 0, 3, 1, key=f"{key_prefix}_nshift"
        )
        shifts = []
        for i in range(int(n_shifts)):
            c1, c2 = st.columns(2)
            curve = c1.selectbox(f"Curve {i + 1}", CURVES, key=f"{key_prefix}_curve_{i}")
            direction = c2.selectbox(f"Direction {i + 1}", DIRECTIONS, key=f"{key_prefix}_dir_{i}")
            shifts.append(Shift(curve, direction))
        meta = DIAGRAM_TYPES[dtype]
        effects = {}
        c1, c2 = st.columns(2)
        effects[meta["y_axis"]] = c1.selectbox(
            f"What happens to {meta['y_axis']}?", EFFECTS, key=f"{key_prefix}_eff_y"
        )
        effects[meta["x_axis"]] = c2.selectbox(
            f"What happens to {meta['x_axis']}?", EFFECTS, key=f"{key_prefix}_eff_x"
        )
        return DiagramDeclaration(diagram_type=dtype, shifts=tuple(shifts), effects=effects)


def _answer_input_ui(label: str, key_prefix: str) -> str:
    """Type-or-photo answer capture, identical pattern to Essay Practice.

    Takes a plain label rather than an EssayPart so both essay parts
    (Section B/C) and data response parts (Section A, which have `.label`
    not `.part` and no diagram) can share the same upload + transcribe
    flow instead of duplicating it.
    """
    mode = st.radio(
        "How are you answering this part?",
        ["⌨️ Type", "📷 Upload a photo"],
        key=f"{key_prefix}_mode",
        horizontal=True,
    )
    if mode == "⌨️ Type":
        return st.text_area(
            f"Your answer to ({label})", key=f"{key_prefix}_answer", height=220,
            placeholder="Write as you would in the exam.",
        )
    if not settings.gemini_api_key:
        st.warning(
            "Photo mode needs GEMINI_API_KEY set in `.env`. Switch back to "
            "**⌨️ Type** and write your answer directly instead.", icon="📷",
        )
        return ""
    photo = st.file_uploader(
        f"Photo of your handwritten answer to ({label})",
        type=["jpg", "jpeg", "png", "webp"], key=f"{key_prefix}_photo",
    )
    transcribed_key = f"{key_prefix}_transcribed"
    if photo is not None:
        st.image(photo, caption="Preview", width=420)
        if st.button("Transcribe this photo", key=f"{key_prefix}_transcribe_btn"):
            with st.spinner("Reading the photo…"):
                try:
                    st.session_state[transcribed_key] = transcribe_photo(
                        settings, photo.getvalue(), photo.type
                    )
                except LLMRateLimitError as exc:
                    st.error(f"Gemini is rate limited. Try again in {exc.friendly_wait()}.")
                except Exception as exc:  # noqa: BLE001 - surfaced to the student
                    st.error(f"Couldn't transcribe that photo: {exc}")
    st.caption(
        "⚠️ **This text box — not the photo — is what gets marked.** Check "
        "it over and fix any misreads before you submit."
    )
    return st.text_area(
        f"Transcribed answer to ({label}) — edit as needed",
        value=st.session_state.get(transcribed_key, ""),
        key=f"{key_prefix}_answer_photo", height=220,
    )


# -------------------------------------------------------------------
# STAGE: Paper 2 Section A — data response (compulsory, one question)
# -------------------------------------------------------------------

if stage == "section_a":
    if "mock_a_group" not in st.session_state:
        groups = store.data_response_groups(topic_codes=topic_filter, exclude_answered=True)
        # A data response the Concept Tutor has already coached the student
        # through part by part is not a mock question any more. Prefer an
        # unseen one; fall back rather than block, and say so if we have to.
        seen = store.seen_group_ids()
        unseen = [g for g in groups if g["group_id"] not in seen]
        st.session_state.mock_a_seen_before = not unseen
        st.session_state.mock_a_group = random.choice(unseen or groups)["group_id"]

    group_id = st.session_state.mock_a_group
    rows = store.data_response_parts(group_id)
    if len(rows) != 6:
        st.error("That data response is incomplete in the bank — skipping Section A.")
        advance()
    parts = [PointsPart.from_row(r) for r in rows]
    stimulus = store.data_response_stimulus(group_id) or {}

    st.markdown(f"### Section A · {SECTION_A_MARKS} marks, compulsory")
    if st.session_state.get("mock_a_seen_before"):
        st.warning(
            "Every banked data response has already been walked through in "
            "the Concept Tutor, so this one is not new to you. Bank another "
            "with `scripts/bank_data_response.py` for a clean sitting.",
            icon="👀",
        )
    st.markdown(f"**{stimulus.get('title', '')}**")
    if stimulus.get("extract"):
        st.markdown(stimulus["extract"])
    if stimulus.get("table_headers") and stimulus.get("table_rows"):
        st.caption(stimulus.get("table_caption", ""))
        st.table(
            {h: [row[i] for row in stimulus["table_rows"]] for i, h in enumerate(stimulus["table_headers"])}
        )
    if stimulus.get("attribution"):
        st.caption(f"Source: {stimulus['attribution']}")
    st.caption(
        "Indicative mark scheme — written by the generator from the syllabus, "
        "not lifted from a Cambridge examiner report."
    )
    st.divider()

    answers: dict[str, str] = {}
    for part in parts:
        st.markdown(f"**{part.label}**  {part.prompt}")
        st.caption(f"{part.max_marks} mark(s)")
        answers[part.label] = _answer_input_ui(part.label, f"mock_a_{part.label}")
        st.divider()

    if st.button("Submit Section A", type="primary"):
        try:
            provider = build_provider(settings)
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
        marker = PointsMarker(provider)
        attempt_id = store.start_attempt(mode="full_paper", paper_key="paper_2")
        results = []
        with st.spinner("Marking Section A — six parts…"):
            for ordinal, part in enumerate(parts, start=1):
                try:
                    marked = marker.mark(part, answers[part.label])
                except LLMRateLimitError as exc:
                    st.error(f"Rate limited. Try again in {exc.friendly_wait()}.")
                    st.stop()
                except AllProvidersRateLimitedError as exc:
                    st.error(f"Every LLM provider is currently rate limited: {exc}")
                    st.stop()
                except SectionAMarkingError as exc:
                    st.error(f"{part.label} could not be marked reliably: {exc}. Nothing recorded.")
                    continue
                record_part(store, attempt_id=attempt_id, ordinal=ordinal, marked=marked,
                            answer_text=answers[part.label])
                results.append(marked)
        store.finish_attempt(attempt_id)
        st.session_state.mock_results["section_a"] = results
        st.session_state.mock_set_marks["section_a"] = sum(p.max_marks for p in parts)
        st.cache_data.clear()
        advance()
    st.stop()

# -------------------------------------------------------------------
# STAGE: Paper 2 Section B / C — essay, choose 1 of 2
# -------------------------------------------------------------------

if stage in ("section_b", "section_c"):
    section_key = "B" if stage == "section_b" else "C"
    offered_key = f"mock_{stage}_offered"
    chosen_key = f"mock_{stage}_chosen"
    marks_label = SECTION_B_MARKS if section_key == "B" else SECTION_C_MARKS

    if offered_key not in st.session_state:
        groups = store.essay_groups(section_key=section_key, topic_codes=topic_filter, exclude_answered=True)
        st.session_state[offered_key] = random.sample(groups, k=min(2, len(groups)))

    offered = st.session_state[offered_key]
    st.markdown(
        f"### {SECTION_LABELS[section_key]} · {marks_label} marks · "
        f"choose 1 of {len(offered)}"
    )

    if chosen_key not in st.session_state:
        labels = {
            g["group_id"]: f"{g['topic_code']} · {topic_title.get(g['topic_code'], '')}"
            for g in offered
        }
        pick = st.radio(
            "Which essay will you answer?", list(labels), format_func=lambda gid: labels[gid],
            key=f"mock_{stage}_pick",
        )
        if st.button("Answer this essay", type="primary"):
            st.session_state[chosen_key] = pick
            st.session_state[f"mock_{stage}_started_at"] = time.time()
            st.rerun()
        st.stop()

    group_id = st.session_state[chosen_key]
    rows = store.essay_parts(group_id)
    if len(rows) != 2:
        st.error("That essay is incomplete in the bank — skipping this section.")
        advance()
    parts = [EssayPart.from_row(r) for r in rows]
    st.subheader(f"Topic {parts[0].topic_code} · {topic_title.get(parts[0].topic_code, '')}")

    answers: dict[str, str] = {}
    declarations: dict[str, DiagramDeclaration | None] = {}
    for part in parts:
        st.markdown(f"### ({part.part})  {part.prompt}")
        st.caption(f"{part.max_marks} marks · command word: {part.command_word or '—'}")
        answers[part.part] = _answer_input_ui(part.part, f"mock_{stage}_{part.part}")
        declarations[part.part] = _diagram_declare_ui(part, f"mock_{stage}_{part.part}")
        st.divider()

    if st.button(f"Submit Section {section_key}", type="primary"):
        try:
            provider = build_provider(settings)
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
        marker = EssayMarker(provider, ladder)
        attempt_id = store.start_attempt(mode="full_paper", paper_key="paper_2")
        seconds = int(time.time() - st.session_state.get(f"mock_{stage}_started_at", time.time()))
        results = []
        with st.spinner("Marking — two passes per part…"):
            for ordinal, part in enumerate(parts, start=1):
                try:
                    marked = marker.mark(part, answers[part.part], declarations.get(part.part))
                except LLMRateLimitError as exc:
                    st.error(f"Rate limited. Try again in {exc.friendly_wait()}.")
                    st.stop()
                except AllProvidersRateLimitedError as exc:
                    st.error(f"Every LLM provider is currently rate limited: {exc}")
                    st.stop()
                except EssayMarkingError as exc:
                    st.error(f"Part ({part.part}) could not be marked reliably: {exc}. Nothing recorded.")
                    continue
                record_essay(store, attempt_id=attempt_id, ordinal=ordinal, marked=marked,
                              answer_text=answers[part.part], seconds_taken=seconds)
                results.append((part, marked))
        store.finish_attempt(attempt_id)
        st.session_state.mock_results[stage] = results
        st.session_state.mock_set_marks[stage] = sum(p.max_marks for p in parts)
        st.cache_data.clear()
        advance()
    st.stop()

# =========================================================================
# REPORT — nothing shown until the whole sitting is over, same as results
# day rather than mid-exam feedback.
# =========================================================================

st.header("📋 Mock test report")

results = st.session_state.mock_results
set_marks = st.session_state.get("mock_set_marks", {})


def _awarded(component: str) -> float:
    """Marks awarded in a component, whatever shape its result object is."""
    payload = results[component]
    if component == "paper1":
        return float(payload.score)
    if component == "section_a":
        return float(sum(m.awarded for m in payload))
    return float(sum(m.awarded for _, m in payload))


def _marked_marks(component: str) -> int:
    """Marks that actually reached a marker.

    Lower than the marks set when a part failed to mark and was skipped with
    an error. Those marks were asked for and scored nothing, so they belong in
    the total — but the student should be told which they were.
    """
    payload = results[component]
    if component == "paper1":
        return int(payload.total)
    if component == "section_a":
        return int(sum(m.max_marks for m in payload))
    return int(sum(m.max_marks for _, m in payload))


mock = build_report(
    st.session_state.mock_exam_type,
    {
        key: (_awarded(key), int(set_marks.get(key, _marked_marks(key))))
        for key in results
    },
)

# ---- Paper 1 ------------------------------------------------------------
if "paper1" in results:
    marked = results["paper1"]
    p1 = mock.component("paper1")
    st.subheader(f"Paper 1 — Multiple Choice · {p1.official_marks} marks")
    st.metric(
        "Paper 1 mark",
        f"{p1.awarded:g} / {p1.official_marks}",
        f"{p1.percent}%",
    )
    if p1.not_set:
        st.caption(
            f"Only {p1.set_marks} of the {p1.official_marks} marks were set — "
            f"the bank was {p1.not_set} questions short for this selection. "
            f"Against what was actually asked that is {p1.percent_of_set}%."
        )
    wrong = marked.wrong_answers()
    if not wrong:
        st.success("Every question correct.")
    for answer in marked.answers:
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

# ---- Paper 2 Section A ---------------------------------------------------
if "section_a" in results:
    marked_parts = results["section_a"]
    sa = mock.component("section_a")
    st.subheader(f"Paper 2 · Section A — Data response · {sa.official_marks} marks")
    st.metric(
        "Indicative mark", f"{sa.awarded:g} / {sa.official_marks}", f"{sa.percent}%"
    )
    unmarked = sa.set_marks - sum(m.max_marks for m in marked_parts)
    if unmarked > 0:
        st.caption(
            f"{unmarked} mark(s) could not be marked and count as zero — see "
            "the error shown when the section was submitted."
        )
    for m in marked_parts:
        with st.expander(f"Part {m.label} — {m.awarded} / {m.max_marks}"):
            for p in m.per_point:
                st.markdown(f"{'✅' if p['met'] else '⬜'} {p['text']}")
            if m.missed_advice:
                st.caption(f"Advice: {m.missed_advice}")
    st.divider()

# ---- Paper 2 Section B / C -----------------------------------------------
for stage_key, section_key, label in (
    ("section_b", "B", "Micro essay"), ("section_c", "C", "Macro essay"),
):
    if stage_key not in results:
        continue
    parts_marked = results[stage_key]
    sc = mock.component(stage_key)
    st.subheader(
        f"Paper 2 · Section {section_key} — {label} · {sc.official_marks} marks"
    )
    st.metric(
        "Mark" if ladder.is_calibrated else "Indicative mark",
        f"{sc.awarded:g} / {sc.official_marks}",
        f"{sc.percent}%",
    )
    for part, marked in parts_marked:
        fb = json.loads(marked.feedback_json())
        with st.expander(f"Part ({part.part}) — {marked.awarded} / {marked.max_marks}"):
            cols = st.columns(len(fb["levels"]) or 1)
            for col, (ao, level) in zip(cols, fb["levels"].items()):
                col.metric(f"{ao} level {level}", f"{fb['marks_by_ao'].get(ao, 0)} marks")
            for ao, why in fb["justifications"].items():
                st.markdown(f"**{ao}** — {why}")
            if fb.get("cap_note"):
                st.warning(fb["cap_note"], icon="📐")
            st.caption(fb["diagram"])
            if fb.get("next_steps"):
                st.markdown("**Do this next time**")
                for step in fb["next_steps"]:
                    st.markdown(f"- {step}")
    st.divider()

# ---- paper totals, then the sitting --------------------------------------
# Paper 1 always reported as a paper. Paper 2 did not, so a sitting that
# skipped Section A showed three tidy section metrics and no statement that a
# third of the paper had never been asked. Both papers now report the same
# way, against the marks Cambridge sets.

for paper in mock.papers:
    if len(paper.components) < 2:
        continue  # Paper 1 is its own subtotal; do not print it twice
    st.subheader(f"{paper.label} — total")
    st.metric(
        "Paper 2 mark",
        f"{paper.awarded:g} / {paper.official_marks}",
        f"{paper.percent}%",
    )
    cols = st.columns(len(paper.components))
    for col, component in zip(cols, paper.components):
        col.metric(
            component.label.split("—")[0].strip(),
            f"{component.awarded:g} / {component.official_marks}",
            "not sat" if not component.sat else f"{component.percent}%",
            delta_color="off" if not component.sat else "normal",
        )
    st.divider()

st.subheader("Overall")
st.metric(
    "Mock test total",
    f"{mock.awarded:g} / {mock.official_marks}",
    f"{mock.percent}%",
)
if mock.covers_whole_as:
    st.caption(
        f"Paper 1 is {assessment.PAPER_1.percent_of_as}% of the AS award and "
        f"Paper 2 the other {assessment.PAPER_2.percent_of_as}%, and the raw "
        f"marks are already in that ratio — so {mock.official_marks} marks is "
        "the whole AS aggregate and no weighting is applied."
    )
else:
    sat_paper = mock.papers[0]
    st.caption(
        f"This sitting covered {sat_paper.label} only — "
        f"{sat_paper.percent_of_as}% of the AS award."
    )

notes = shortfall_notes(mock)
if notes:
    st.warning(
        "This was not a full paper:\n\n"
        + "\n".join(f"- {note}" for note in notes),
        icon="⚠️",
    )
    st.caption(
        f"Against only what was set, the sitting scored {mock.percent_of_set}%. "
        "That is the fairer number for the student and the wrong one for the "
        "paper — bank more questions and sit it again for a mark that means "
        "something."
    )

# ---- estimated grade ------------------------------------------------------
# Only off a complete sitting of both papers. A grade is awarded on the AS
# aggregate, so putting a letter on one paper — or on a paper the bank could
# only half fill — would label something that is not the thing the letter
# describes.
if mock.gradeable:
    try:
        grades = default_grades()
    except Exception:  # noqa: BLE001 — a missing thresholds file is not fatal
        grades = None
    if grades is not None:
        grade = grades.grade_for(mock.percent)
        st.metric(
            "Estimated grade", grade or "below e",
        )
        st.caption(
            ("Thresholds are an estimate, not Cambridge's. "
             if not grades.is_official else f"Thresholds from {grades.source}. ")
            + "Cambridge sets real thresholds per session, after the exam, and "
            "they move with the difficulty of the paper."
        )
elif mock.covers_whole_as:
    st.caption(
        "No grade estimate: a grade is awarded on the whole AS aggregate and "
        "this sitting was not a complete one."
    )

if st.button("Start a new mock test", type="primary"):
    reset_mock()
    st.rerun()
