"""Ask about a concept and get a syllabus-grounded explanation, with its sources.

Nothing here writes to the attempt log. Asking a question is not evidence of
what a student knows, and treating it as such would poison the weakness map.
"""

from __future__ import annotations

import streamlit as st

from src.config import settings
from src.llm.exceptions import AllProvidersRateLimitedError, LLMRateLimitError
from src.llm.provider import build_provider
from src.store.db import Store
from src.syllabus.models import SyllabusSpine
from src.llm.provider import build_provider as build_llm_provider
from src.marking.points_marker import (
    PointsMarker,
    PointsMarkingError,
    PointsPart,
)
from src.diagrams import scope as diagram_scope
from src.diagrams import embed as diagram_embed
from src.diagrams.canvas import DiagramError
from src.tutor.corpus import excluded_phrases, load_note_documents
from src.tutor.data_response_tutor import (
    ASSESS_CAPS,
    SECTION_A,
    SHAPES,
    cap_consequence,
    guidance_for,
    minutes_for,
    reading_the_stimulus,
)
from src.tutor.explainer import ConceptTutor
from src.tutor.retriever import SpineRetriever

st.set_page_config(page_title="Concept Tutor · 9708", page_icon="💡", layout="wide")


# ---- stale-server guard ------------------------------------------------
# Streamlit re-runs page scripts on every interaction but does NOT re-import
# modules under src/ — they stay cached in sys.modules. A server left running
# across an upgrade therefore executes the new page against the old classes and
# fails with an AttributeError deep inside a callback. Written inline on
# purpose: a shared helper module would itself be the stale thing.
_missing = [
    name
    for obj, name in (
        (ConceptTutor, "SUPPORTS_HISTORY"),
        (ConceptTutor, "SUPPORTS_DATA_RESPONSE"),
        (SpineRetriever, "resolve_query"),
        (SpineRetriever, "unit_of"),
        (Store, "mark_group_seen"),
        (Store, "seen_group_ids"),
    )
    if not hasattr(obj, name)
]
if _missing:
    st.error(
        "This Streamlit server is running code from before the last upgrade "
        f"(missing: {', '.join(_missing)}) — stop it with Ctrl+C and run "
        "`streamlit run Home.py` again."
    )
    st.stop()


@st.cache_data
def get_spine() -> SyllabusSpine | None:
    if not settings.spine_path.exists():
        return None
    return SyllabusSpine.load(settings.spine_path)


@st.cache_data
def get_a_level_spine() -> SyllabusSpine | None:
    path = settings.spine_path.with_name("syllabus_spine_a.json")
    return SyllabusSpine.load(path) if path.exists() else None


@st.cache_resource
def get_store() -> Store:
    store = Store(settings.db_path)
    if not store.is_initialised():
        store.initialise()
    return store


@st.cache_resource
def get_tutor() -> ConceptTutor | None:
    spine = get_spine()
    if spine is None:
        return None
    try:
        provider = build_provider(settings)
    except Exception:
        return None
    return ConceptTutor(
        provider,
        spine,
        a_level_spine=get_a_level_spine(),
        documents=load_note_documents(get_store(), spine),
        excluded_phrases=excluded_phrases(spine),
    )


spine = get_spine()
store = get_store()

st.title("Concept Tutor")
st.caption(
    "Every answer is built from your syllabus and your own revision notes, and "
    "says which chapter and topic it came from. If a question falls outside "
    "them, the tutor says which word it could not place rather than guessing."
)

if spine is None:
    st.error("No syllabus spine — run `python scripts/build_syllabus_spine.py` first.")
    st.stop()

if not (settings.groq_api_key or settings.gemini_api_key or settings.mistral_api_key):
    st.error("No LLM key set. Copy `.env.example` to `.env` and add at least one key.")
    st.stop()

tutor = get_tutor()
if tutor is None:
    st.error(
        "Could not build an LLM provider from your .env — run "
        "`python scripts/check_setup.py`."
    )
    st.stop()

if "tutor_history" not in st.session_state:
    st.session_state.tutor_history = []

corpus = tutor.retriever.counts()
if corpus["notes"] == 0:
    st.info(
        "The knowledge base is not loaded, so the tutor is matching against the "
        "syllabus lines only and will turn away more questions than it needs "
        "to. Run `python scripts/build_notes.py --all` to widen it."
    )


def show_sources(sources, slot: str) -> None:
    """Chapter and topic attribution, computed in code, with a way in.

    A source line the student cannot act on is decoration. Each one offers the
    note for that topic and a targeted set of questions on it, so reading turns
    into practice without a hunt through the sidebar.
    """
    if not sources:
        return
    # A one-line summary OUTSIDE the expander. The detail was hidden behind a
    # collapsed panel, so an answer read (or copied) at a glance showed the
    # heading "Where this comes from" with nothing under it — worse than no
    # attribution, because it looks like the tutor found nothing.
    chapters = []
    for source in sources:
        label = source.chapter
        if label not in chapters:
            chapters.append(label)
    st.caption("From " + " · ".join(chapters))

    with st.expander("Which topics exactly", expanded=True):
        for i, source in enumerate(sources):
            left, mid, right = st.columns([6, 2, 2])
            with left:
                if source.is_chapter:
                    st.markdown(f"**{source.chapter}** — whole chapter")
                else:
                    st.markdown(f"**{source.chapter}**  \n{source.topic}")
                    if source.detail():
                        st.caption(source.detail())
            if source.is_chapter:
                continue
            if mid.button("Open the note", key=f"note_{slot}_{i}", use_container_width=True):
                st.session_state["kb_unit"] = source.unit_code
                st.session_state["kb_topic"] = source.topic_code
                st.switch_page("pages/5_Knowledge_Base.py")
            if right.button("Practise it", key=f"prac_{slot}_{i}", use_container_width=True):
                st.session_state["practice_topic"] = source.topic_code
                st.switch_page("pages/1_MCQ_Practice.py")

    # A second explanation, elsewhere. Anchored to the top topic and searched
    # in the SYLLABUS's wording, not the student's phrasing, so the link goes
    # where the answer came from.
    first = next((s for s in sources if not s.is_chapter), None)
    if first is None:
        return
    try:
        from src.reference.panel import go_deeper
    except ImportError:
        st.caption(
            "This Streamlit server predates the link-out upgrade — restart it "
            "(Ctrl+C, then `streamlit run Home.py`) to see other sites."
        )
        return
    go_deeper(spine, first.topic_code, first.topic_title)


def _diagrams_for(result, question: str = "") -> tuple:
    """Diagrams for the topics an answer was actually built from.

    Keyed off the retrieved sources rather than the answer text, so a diagram
    only appears when the retriever grounded the answer in a topic that has
    one. Capped at two: three diagrams under one answer is wallpaper.
    """
    # `Source.topic_code`, not `.code`. The first version of this looked for
    # `.code`, matched nothing, and silently rendered no diagram at all — the
    # page still loaded, so a "page loads" test passed happily. Chapter-level
    # sources carry an empty topic_code and are skipped.
    codes = []
    for source in getattr(result, "sources", ()) or ():
        code = getattr(source, "topic_code", "")
        if code and code not in codes:
            codes.append(code)
    found: list = []
    for code in codes:
        for entry in diagram_scope.for_topic(spine, code):
            if entry not in found:
                found.append(entry)
    return diagram_scope.rank_for_question(tuple(found), question)[:2]


# ------------------------------------------------- learn the data response
# Paper 2 Section A is the one component a student can meet cold. The app
# could already generate one, serve it in a mock and mark it; it could not
# teach one. Everything on the left tab below costs ZERO tokens — the shapes,
# caps, timings and command word meanings are all read from code and from the
# parsed spine. Only "check this part" calls a model, and only for the part
# the student actually attempted.
#
# Nothing here writes to the attempt log, on purpose: being coached through a
# question is not evidence of what you can do unaided, and recording it would
# tell the AI Coach the opposite. The one thing that IS recorded is that the
# question has been seen, so a later mock does not hand back a data response
# this screen has already taken apart.


def _render_section_a_reference() -> None:
    """How Section A works. All of it arithmetic, none of it a model call."""
    c1, c2, c3 = st.columns(3)
    c1.metric("Section A", f"{SECTION_A.marks} marks")
    c2.metric("Of a Paper 2 worth", "60 marks")
    c3.metric("Worth about", f"{minutes_for(SECTION_A.marks)} min")
    st.caption(
        "Compulsory — there is no choice in Section A. One extract plus one "
        f"table, then about {SECTION_A.parts} parts of increasing demand."
    )

    st.markdown("**The shapes recent papers actually used**")
    for shape in SHAPES:
        st.caption(f"{shape.name} — {shape.source}")
        st.table(
            {
                "Part": [p.label for p in shape.parts],
                "Marks": [p.marks for p in shape.parts],
                "Asks for": [p.kind.replace("_", " ") for p in shape.parts],
                "Time": [f"{minutes_for(p.marks)} min" for p in shape.parts],
            }
        )
    st.caption(
        "Both total 20, both open with data handling and both end with two "
        "six-mark parts asking for judgement. Cambridge does not publish a "
        "fixed structure — these were read off the mark schemes in "
        "`data/papers/`."
    )

    st.markdown("**Where the marks are lost**")
    st.info(cap_consequence(ASSESS_CAPS, 6), icon="⚖️")
    st.markdown(
        "- The low-mark parts are **point-marked** — one mark per creditable "
        "point. Writing one point at length earns one mark.\n"
        "- A **percentage change** is not a difference. Subtracting two "
        "percentage rates gives percentage *points*, which is a different "
        "quantity.\n"
        "- A data-handling part wants a **trend or a comparison**, not the "
        "value in a single year.\n"
        "- Section A is **not** levels-marked. Sections B and C are."
    )
    if st.button("Ask the tutor about Section A technique", key="dr_ask_technique"):
        st.session_state.pending = (
            "How should I answer the Paper 2 Section A data response?"
        )
        st.rerun()


def _render_walkthrough() -> None:
    groups = store.data_response_groups(exclude_answered=False)
    if not groups:
        st.info(
            "No data response is banked yet. Register a dataset with "
            "`python scripts/add_dataset.py`, then run "
            "`python scripts/bank_data_response.py --dataset <slug> --topic "
            "<code> --shape june_2024 --count 1`."
        )
        return

    seen = store.seen_group_ids()
    titles = {t.code: t.title for t in spine.iter_topics()}

    def label(group) -> str:
        code = group["topic_code"]
        mark = " · already walked through" if group["group_id"] in seen else ""
        return f"{code} {titles.get(code, '')}{mark}"

    default = next(
        (i for i, g in enumerate(groups) if g["group_id"] not in seen), 0
    )
    idx = st.selectbox(
        "Which data response?",
        options=range(len(groups)),
        index=default,
        format_func=lambda i: label(groups[i]),
        key="dr_learn_pick",
    )
    group_id = groups[idx]["group_id"]

    # Opening the walkthrough is what marks the question as seen, so it sits
    # behind an explicit button rather than happening on render. Two reasons:
    # a student browsing the picker has not seen anything yet, and a screen
    # that writes to the database merely by being displayed is a screen that
    # writes every time Streamlit reruns it.
    if group_id in seen:
        st.caption(
            "You have already walked through this one, so a Mock Test will "
            "reach for a different data response."
        )
    else:
        st.caption(
            "Opening this marks it as seen, so a Mock Test will reach for a "
            "different data response. Nothing here is recorded as a mark and "
            "none of it reaches the AI Coach."
        )
    if st.session_state.get("dr_open_group") != group_id:
        if not st.button("Open this walkthrough", key="dr_open", type="primary"):
            return
        store.mark_group_seen(group_id)
        st.session_state.dr_open_group = group_id

    rows = store.data_response_parts(group_id)
    if len(rows) != 6:
        st.warning("That data response is incomplete in the bank.")
        return
    parts = [PointsPart.from_row(r) for r in rows]
    stimulus = store.data_response_stimulus(group_id) or {}

    st.markdown(f"#### {stimulus.get('title', 'Stimulus')}")
    if stimulus.get("extract"):
        st.markdown(stimulus["extract"])
    if stimulus.get("table_headers") and stimulus.get("table_rows"):
        st.caption(stimulus.get("table_caption", ""))
        st.table(
            {
                h: [row[i] for row in stimulus["table_rows"]]
                for i, h in enumerate(stimulus["table_headers"])
            }
        )
    if stimulus.get("attribution"):
        st.caption(f"Source: {stimulus['attribution']}")
    st.caption(
        "⚠️ Generated from open data around a real table. The figures are "
        "real; the wording and the mark scheme are not Cambridge's."
    )

    with st.expander("Before you write anything", expanded=True):
        for step in reading_the_stimulus(stimulus):
            st.markdown(f"- {step}")

    st.divider()
    for part in parts:
        guide = guidance_for(part, spine)
        st.markdown(f"##### {guide.headline()}")
        st.markdown(f"**{part.label}**  {part.prompt}")

        if guide.command_meaning:
            st.caption(
                f"Command word **{guide.command_word}** — Cambridge's own "
                f"definition: {guide.command_meaning}"
            )
        if guide.demand:
            st.caption(f"This kind of part {guide.demand}.")
        for step in guide.steps:
            st.markdown(f"- {step}")
        for note in guide.notes:
            st.caption(note)
        if guide.cap_note:
            st.info(guide.cap_note, icon="⚖️")

        answer = st.text_area(
            f"Your attempt at ({part.label})",
            key=f"dr_answer_{part.question_id}",
            height=140,
            placeholder="Write it as you would in the exam, then check it.",
        )
        left, right = st.columns(2)
        checked_key = f"dr_checked_{part.question_id}"
        if left.button(
            "Check this part", key=f"dr_check_{part.question_id}",
            use_container_width=True,
        ):
            try:
                provider = build_llm_provider(settings)
            except Exception as exc:  # noqa: BLE001 — surfaced to the student
                st.error(f"No LLM provider available: {exc}")
            else:
                try:
                    with st.spinner("Checking against the mark scheme…"):
                        st.session_state[checked_key] = PointsMarker(provider).mark(
                            part, answer
                        )
                except (LLMRateLimitError, AllProvidersRateLimitedError) as exc:
                    wait = getattr(exc, "friendly_wait", lambda: "a minute")()
                    st.warning(f"Rate limited — try again in about {wait}.")
                except PointsMarkingError as exc:
                    st.error(f"Could not check that reliably: {exc}")
        if right.button(
            "Show what a marker credits", key=f"dr_reveal_{part.question_id}",
            use_container_width=True,
        ):
            st.session_state[f"dr_reveal_on_{part.question_id}"] = True

        marked = st.session_state.get(checked_key)
        if marked is not None:
            st.markdown(
                f"**{marked.awarded} of {marked.max_marks}** — practice only, "
                "not recorded."
            )
            for point in marked.per_point:
                icon = "✅" if point["met"] else "⬜"
                st.markdown(f"{icon} {point['text']}")
                if not point["met"] and point.get("why"):
                    st.caption(point["why"])
            if marked.missed_advice:
                st.caption(f"Next time: {marked.missed_advice}")
        elif st.session_state.get(f"dr_reveal_on_{part.question_id}"):
            st.caption("What this part credits, one mark each:")
            for point in part.points:
                st.markdown(f"- _{point.get('band', '')}_ — {point.get('text', '')}")
        st.divider()


with st.expander("Learn the data response — Paper 2 Section A", expanded=False):
    st.caption(
        "Section A is compulsory and it is the part of the exam a student is "
        "most likely to meet cold. Read how it works, then walk through a "
        "banked one part by part."
    )
    how, walk = st.tabs(["How Section A works", "Walk through a real one"])
    with how:
        _render_section_a_reference()
    with walk:
        _render_walkthrough()


# ---------------------------------------------------------- browse panel
# Kept available for the whole session. In v1 this disappeared the moment the
# first question was asked, which left the student with a text box and no clue
# what it would accept.

with st.expander("Browse the syllabus", expanded=not st.session_state.tutor_history):
    st.caption(
        "Pick a chapter, then a topic — each opens with three questions that "
        "go from recall to evaluation. Or just type your own question below, "
        "in your own words; spelling does not have to be perfect."
    )
    unit_labels = [f"{u.code}  {u.title}" for u in spine.units]
    unit_idx = st.selectbox(
        "Chapter", options=range(len(spine.units)),
        format_func=lambda i: unit_labels[i], key="tutor_unit_idx",
    )
    unit = spine.units[unit_idx]

    for topic in unit.topics:
        st.markdown(f"**{topic.code}  {topic.title}**")
        lede = topic.title[0].lower() + topic.title[1:]
        first_outcome = topic.outcomes[0].text.strip() if topic.outcomes else lede
        layered = [
            ("Define", f"What is meant by {lede}?"),
            ("Explain", f"Explain {first_outcome}."),
            ("Evaluate", f"Evaluate the extent to which {lede} matters in AS Economics."),
        ]
        cols = st.columns(3)
        for col, (label, prompt) in zip(cols, layered):
            if col.button(label, use_container_width=True, key=f"starter_{topic.code}_{label}"):
                st.session_state.pending = prompt
                st.rerun()

# ------------------------------------------------------------ history

for turn, entry in enumerate(st.session_state.tutor_history):
    with st.chat_message("user"):
        st.markdown(entry["question"])
    with st.chat_message("assistant"):
        st.markdown(entry["answer"])
        show_sources(entry.get("sources") or [], slot=f"h{turn}")

# -------------------------------------------------------------- input

typed = st.chat_input("Ask about any AS Economics concept, or how the exam is marked")
question = st.session_state.pop("pending", None) or typed

if question:
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        result = None
        try:
            with st.spinner("Checking the syllabus..."):
                result = tutor.explain(question, history=st.session_state.tutor_history)
        except (LLMRateLimitError, AllProvidersRateLimitedError) as exc:
            wait = getattr(exc, "friendly_wait", lambda: "a minute")()
            st.warning(
                f"Every configured provider is rate-limited. Try again in about "
                f"{wait}. Nothing was lost."
            )

        if result is not None:
            if result.unsupported_terms:
                missing = ", ".join(f"“{t}”" for t in result.unsupported_terms)
                st.caption(
                    f"{missing} is not in the AS syllabus — answering the rest "
                    "of the question from what is."
                )

            if result.resolved:
                reading = ", ".join(
                    f"“{typed_word}” as “{matched}”"
                    for typed_word, matched in result.resolved.items()
                )
                st.caption(f"Reading {reading}.")

            if result.is_refusal:
                st.info(result.text)
                if result.suggestions:
                    st.caption("Closest AS topics — try one of these instead:")
                    cols = st.columns(min(len(result.suggestions), 4))
                    for col, (code, title) in zip(cols, result.suggestions):
                        if col.button(
                            f"{code} {title}",
                            use_container_width=True,
                            key=f"suggest_{code}_{len(st.session_state.tutor_history)}",
                        ):
                            st.session_state.pending = f"Explain {title.lower()}."
                            st.rerun()
            else:
                st.markdown(result.text)
                if result.kind == "exam":
                    st.caption(
                        "Answered from Cambridge's own command words and the "
                        "paper structure — not from the model's memory."
                    )
                for entry in _diagrams_for(result, question):
                    st.markdown(f"**{entry.label}**")
                    try:
                        st.markdown(
                            diagram_embed.as_html(entry.render()),
                            unsafe_allow_html=True,
                        )
                    except DiagramError:
                        pass
                if result.kind == "exam":
                    pass
                elif result.kind == "data_response":
                    st.caption(
                        "Answered from the Section A shapes read off the 2023 "
                        "specimen and June 2024 mark schemes, the marker's own "
                        "caps, and Cambridge's command words — not from the "
                        "model's memory."
                    )
                else:
                    show_sources(result.sources, slot="live")

            st.session_state.tutor_history.append(
                {
                    "unsupported": result.unsupported_terms,
                    "question": question,
                    "answer": result.text,
                    "topics": result.topics,
                    "in_scope": result.in_scope,
                    "sources": result.sources,
                }
            )

if st.session_state.tutor_history:
    st.sidebar.caption(
        f"Corpus: {corpus['chapters']} chapters + {corpus['syllabus']} syllabus "
        f"lines + {corpus['notes']} note sections, {corpus['vocabulary']} terms."
    )
    if st.sidebar.button("Clear conversation"):
        st.session_state.tutor_history = []
        st.rerun()
