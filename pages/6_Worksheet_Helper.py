"""Worksheet Helper — upload what the school set, work through it here.

Two deliberate frictions in this screen, both worth defending.

**The answer box comes before the solution.** A button that prints worked
answers to a worksheet is a homework machine, and this app exists to make a
student better at economics, not faster at finishing sheets. So every item
shows a place to write an answer first, and the solution opens underneath.
Nothing stops a student clicking straight through — the point is that the
default path is attempt, then check, which is also the only order that tells
them anything about what they know.

**Solutions are labelled derived, everywhere.** A school worksheet has no mark
scheme attached. Everything on this page was worked out by a model reading the
question, which is a different kind of object from a marked answer, and it is
never written to the attempt log. The Progress and diagnosis on the AI Coach
page stay built from marks this app computed in code against validated keys.
Mixing the two would corrupt the one number the student is relying on.
"""

from __future__ import annotations

import streamlit as st

from src.config import settings
from src.llm.exceptions import LLMRateLimitError
from src.llm.provider import build_provider, transcribe_photo
from src.notes.generator import out_of_scope_terms
from src.store.db import Store
from src.syllabus.models import SyllabusSpine
from src.tutor.corpus import excluded_phrases, load_note_documents
from src.tutor.retriever import SpineRetriever
from src.worksheet.classify import classify_all, command_word_note
from src.worksheet.extract import (
    SUPPORTED_SUFFIXES,
    TRANSCRIBE_WORKSHEET_PROMPT,
    extract,
)
from src.worksheet.models import ESSAY, KIND_LABELS, MCQ
from src.worksheet.segment import segment
from src.worksheet.solve import SolveError, check_mcq, solve_item
from src.worksheet.topics import coverage_counts

st.set_page_config(page_title="Worksheet Helper · 9708", page_icon="📄", layout="wide")

KIND_ICON = {"mcq": "🔘", "short": "✏️", "structured": "🧩", "essay": "📝", "unknown": "❓"}


@st.cache_resource
def get_store() -> Store:
    store = Store(settings.db_path)
    if not store.is_initialised():
        store.initialise()
    return store


@st.cache_resource
def get_spine() -> SyllabusSpine | None:
    try:
        return SyllabusSpine.load(settings.spine_path)
    except (FileNotFoundError, ValueError):
        return None


@st.cache_resource
def get_retriever(_spine: SyllabusSpine) -> SpineRetriever:
    store = get_store()
    return SpineRetriever(
        _spine,
        documents=load_note_documents(store, _spine),
        excluded_phrases=excluded_phrases(_spine),
    )


st.title("📄 Worksheet Helper")
st.caption(
    "Upload a worksheet from school. It gets read, split into questions, and "
    "worked through one at a time."
)

spine = get_spine()
if spine is None:
    st.error(
        "The syllabus spine is missing. Run "
        "`python scripts/build_syllabus_spine.py` first — questions are matched "
        "against it to keep answers at AS level."
    )
    st.stop()

# ------------------------------------------------------------------ input

st.subheader("1 · Give me the worksheet")

tab_file, tab_paste = st.tabs(["Upload a file", "Paste the text"])

raw_text = ""
source_name = ""
source_kind = "text"
extraction_warnings: list[str] = []

with tab_file:
    upload = st.file_uploader(
        "PDF, Word, or a photo of the page",
        type=[s.lstrip(".") for s in sorted(SUPPORTED_SUFFIXES)],
        help=(
            "A photo works for handwritten or photocopied sheets and needs "
            "GEMINI_API_KEY set. PDFs and .docx are read directly and cost "
            "nothing."
        ),
    )
    if upload is not None:
        transcriber = None
        if getattr(settings, "gemini_api_key", None):
            def transcriber(data: bytes, mime: str) -> str:  # noqa: E306
                from src.llm.provider import GeminiProvider

                provider = GeminiProvider(settings.gemini_api_key, settings.gemini_model)
                return provider.transcribe_image(
                    data, mime, prompt=TRANSCRIBE_WORKSHEET_PROMPT
                ).text

        with st.spinner("Reading the worksheet…"):
            try:
                result = extract(
                    upload.name,
                    upload.getvalue(),
                    transcriber=transcriber,
                    mime_type=upload.type,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
                result = None
                st.error(f"Could not read that file: {exc}")

        if result is not None:
            raw_text = result.text
            source_name = upload.name
            source_kind = result.kind
            extraction_warnings = result.warnings

with tab_paste:
    pasted = st.text_area(
        "Type or paste the questions",
        height=220,
        placeholder=(
            "1. Identify, in each case, a government policy measure that could "
            "correct the following examples of market failure.\n"
            "(a) Air pollution from a power station. [2]\n"
            "(b) Under-consumption of vaccinations. [2]"
        ),
        help="Keep the question numbers and any [marks] — they are used to work "
             "out what each question is asking for.",
    )
    if pasted.strip() and not raw_text:
        raw_text = pasted
        source_name = "pasted text"
        source_kind = "text"

for warning in extraction_warnings:
    st.warning(warning)

if not raw_text.strip():
    st.info(
        "Nothing loaded yet. Upload a file above, or paste the questions in the "
        "other tab."
    )
    st.stop()

# ------------------------------------------------------------- segmenting

sheet = segment(raw_text, source_name=source_name, source_kind=source_kind)
classify_all(sheet.items, spine)

# A new worksheet invalidates solutions held for the old one.
sheet_key = f"{source_name}:{len(raw_text)}:{len(sheet.items)}"
if st.session_state.get("ws_key") != sheet_key:
    st.session_state["ws_key"] = sheet_key
    st.session_state["ws_solutions"] = {}

    # Topic-coverage signal for the AI Coach: which topics this worksheet
    # touches, logged once per sheet (not per Streamlit rerun) — never the
    # question text, an answer, or a mark. See src/worksheet/topics.py and
    # Store.record_worksheet_topics for what is and is not kept.
    counts = coverage_counts(sheet.items, get_retriever(spine))
    if counts:
        get_store().record_worksheet_topics(counts)

solutions: dict[str, object] = st.session_state.setdefault("ws_solutions", {})

st.subheader("2 · What I found")

counts = sheet.counts_by_kind()
columns = st.columns(4)
columns[0].metric("Questions", len(sheet.items))
columns[1].metric("Marks printed", sheet.total_printed_marks or "—")
columns[2].metric(
    "Types", ", ".join(KIND_LABELS[k].split()[0] for k in counts) or "—"
)
columns[3].metric("Text read", f"{sheet.coverage:.0%}")

for warning in sheet.warnings:
    st.warning(warning)

if not sheet.items:
    with st.expander("What was read"):
        st.text(raw_text[:4000])
    st.stop()

with st.expander("The text I read, exactly as extracted"):
    st.text(raw_text[:8000])

st.caption(
    "Answers below are worked out by the app from the AS syllabus. They are not "
    "a mark scheme and nothing here is added to your progress — sit a mock or "
    "write an essay for that."
)

# ---------------------------------------------------------------- solving

retriever = get_retriever(spine)
excluded = out_of_scope_terms(spine)


def solve(item) -> None:
    provider = build_provider(settings)
    try:
        solutions[item.label] = solve_item(
            item,
            provider=provider,
            spine=spine,
            retriever=retriever,
            excluded=excluded,
            stimulus=sheet.preamble,
        )
    except LLMRateLimitError as exc:
        st.session_state["ws_rate_limited"] = str(exc)
    except SolveError as exc:
        solutions[item.label] = exc


st.subheader("3 · Work through it")

top = st.columns([1, 1, 2])
with top[0]:
    if st.button("Solve every question", type="primary"):
        st.session_state.pop("ws_rate_limited", None)
        progress = st.progress(0.0)
        for index, item in enumerate(sheet.items, start=1):
            if st.session_state.get("ws_rate_limited"):
                break
            if item.label not in solutions:
                solve(item)
            progress.progress(index / len(sheet.items))
        progress.empty()
with top[1]:
    if st.button("Clear solutions"):
        st.session_state["ws_solutions"] = {}
        st.rerun()

limit_message = st.session_state.get("ws_rate_limited")
if limit_message:
    st.warning(
        "The free tier ran out of requests partway through. Everything already "
        f"solved is kept below — try the rest in a few minutes. ({limit_message})"
    )

for item in sheet.items:
    icon = KIND_ICON.get(item.kind, "❓")
    marks = f" · [{item.marks}]" if item.marks else ""
    header = f"{icon}  **{item.label}**{marks} — {KIND_LABELS.get(item.kind, '')}"

    with st.container(border=True):
        st.markdown(header)
        if item.context.strip():
            st.caption(item.context.strip())
        st.markdown(item.text)

        if item.options:
            st.markdown(
                "\n".join(f"- **{k}** {v}" for k, v in sorted(item.options.items()))
            )

        note = command_word_note(item, spine)
        if note:
            st.caption(f"Command word — {note}")
        if item.requires_diagram:
            st.caption("This question asks for a diagram — draw it on paper as you go.")

        answer_key = f"ws_answer_{item.label}"
        if item.kind == MCQ:
            st.radio(
                "Your answer",
                sorted(item.options),
                index=None,
                horizontal=True,
                key=answer_key,
            )
        else:
            st.text_area("Your answer", key=answer_key, height=90,
                         placeholder="Have a go first — then check.")

        solution = solutions.get(item.label)
        if solution is None:
            if st.button("Check this one", key=f"ws_solve_{item.label}"):
                with st.spinner("Working it out…"):
                    solve(item)
                st.rerun()
            continue

        if isinstance(solution, SolveError):
            st.error(f"Could not produce a usable answer: {solution}")
            if st.button("Try again", key=f"ws_retry_{item.label}"):
                solutions.pop(item.label, None)
                st.rerun()
            continue

        st.divider()

        if solution.scope_note:
            st.warning(solution.scope_note)

        if item.kind == MCQ:
            chosen = st.session_state.get(answer_key)
            verdict = check_mcq(item, solution, chosen or "")
            if verdict is True:
                st.success(f"You picked {chosen} — that matches.")
            elif verdict is False:
                st.info(f"You picked {chosen}; this works out as {solution.mcq_key}.")

        if solution.is_plan:
            st.markdown("**What the question is asking**")
            st.markdown(solution.answer)
            st.info(
                "This is a plan, not an essay. Write it yourself, then paste it "
                "into Essay Practice to get it marked against the levels."
            )
        else:
            st.markdown("**Answer**")
            st.markdown(solution.answer)

        if solution.working:
            st.markdown("**Plan**" if solution.is_plan else "**How you get there**")
            for step in solution.working:
                st.markdown(f"- {step}")

        if solution.evaluation:
            st.markdown("**Evaluation you could bring in**")
            for line in solution.evaluation:
                st.markdown(f"- {line}")

        if solution.option_notes:
            with st.expander("Why the other options are wrong"):
                for letter in sorted(solution.option_notes):
                    st.markdown(f"**{letter}** — {solution.option_notes[letter]}")

        if solution.diagram:
            st.markdown("**Diagram to draw**")
            st.markdown(solution.diagram)

        if solution.marks_guidance:
            st.markdown("**How the marks go**")
            st.markdown(solution.marks_guidance)

        if solution.common_error:
            st.markdown("**Where people lose marks**")
            st.markdown(solution.common_error)

        # Named as the CLOSEST match, not the topic. Retrieval is lexical, and
        # an incidental word can pull a question sideways — "make housing
        # affordable for low income families" matches "national income
        # statistics" on the word income. Saying "closest match" keeps the
        # buttons below honest: the student can see where they lead first.
        bits = []
        if solution.topic_code:
            bits.append(
                f"Closest syllabus match: chapter {solution.unit_code} · "
                f"{solution.topic_code} {solution.topic_title}"
            )
        if solution.syllabus_refs:
            bits.append("outcomes " + ", ".join(solution.syllabus_refs[:4]))
        if bits:
            st.caption(" · ".join(bits) + " — worked out by the app, not a mark scheme")

        if solution.topic_code:
            actions = st.columns(2)
            if actions[0].button(
                f"Open the note for {solution.topic_code}", key=f"ws_note_{item.label}"
            ):
                st.session_state["kb_topic"] = solution.topic_code
                st.switch_page("pages/5_Knowledge_Base.py")
            if actions[1].button(
                f"Practise {solution.topic_code}", key=f"ws_practise_{item.label}"
            ):
                st.session_state["practice_topic"] = solution.topic_code
                st.switch_page("pages/1_MCQ_Practice.py")
