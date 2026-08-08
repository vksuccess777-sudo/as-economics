"""Write one Paper 2 Section B/C essay and have it marked.

Two things are shown honestly on this page and should stay that way:

1. Whether the ladder is calibrated. Until the levels descriptors come from the
   Cambridge specimen mark scheme, every mark here is indicative, and the page
   says so above the score rather than in a footnote.

2. That the marker cannot see a drawing. The diagram is declared, not drawn.
   The page never implies the tool looked at the student's paper.
"""

from __future__ import annotations

import json
import time

import streamlit as st

from src.config import settings
from src.llm.exceptions import AllProvidersRateLimitedError, LLMRateLimitError
from src.llm.provider import build_provider, transcribe_photo
from src.marking.diagram import CURVES, DIAGRAM_TYPES, DIRECTIONS, EFFECTS, DiagramDeclaration, Shift
from src.marking.essay_marker import EssayMarker, EssayPart, MarkingError, record_essay
from src.marking.levels import default_ladder, resolve_ladder_path
from src.store.db import Store
from src.syllabus.models import SyllabusSpine

st.set_page_config(page_title="Essay Practice · 9708", page_icon="✍️", layout="wide")


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

st.title("Paper 2 essay practice")
st.caption(
    "Section B (micro) and Section C (macro). Each essay is part (a) 8 marks "
    "and part (b) 12 marks, marked separately."
)

if spine is None:
    st.error("No syllabus spine — run `python scripts/build_syllabus_spine.py` first.")
    st.stop()

if not ladder.is_calibrated:
    st.warning(
        f"**Indicative marking.** The levels ladder in use "
        f"(`{resolve_ladder_path().name}`) was not built from a Cambridge mark "
        "scheme. Marks below show whether an answer is improving; they are not "
        "a predicted grade. Replace it with `data/levels/paper2_levels.json` "
        "built from the specimen Paper 2 mark scheme to calibrate.",
        icon="⚠️",
    )

groups = store.essay_groups(exclude_answered=True)
if not groups:
    st.info(
        "No unanswered essays in the bank. Generate some:\n\n"
        "```\npython scripts/bank_essays.py --thin 1\n```"
    )
    st.stop()

topic_title = {t.code: t.title for t in spine.iter_topics()}

# ---- choose ---------------------------------------------------------

with st.sidebar:
    st.header("Choose an essay")
    section = st.radio(
        "Section", ["Any", "B — micro", "C — macro"], horizontal=False
    )
    filtered = [
        g for g in groups
        if section == "Any" or g["section_key"] == section.split(" ")[0]
    ]
    if not filtered:
        st.warning("Nothing banked in that section yet.")
        st.stop()
    labels = {
        g["group_id"]: f"{g['topic_code']} · {topic_title.get(g['topic_code'], '')[:38]}"
        for g in filtered
    }
    chosen = st.selectbox(
        "Essay", list(labels), format_func=lambda gid: labels[gid]
    )
    if st.button("Start this essay", type="primary", use_container_width=True):
        st.session_state.essay_group = chosen
        st.session_state.essay_started = time.time()
        st.session_state.pop("essay_marks", None)

group_id = st.session_state.get("essay_group") or chosen
rows = store.essay_parts(group_id)
if len(rows) != 2:
    st.error("That essay is incomplete in the bank.")
    st.stop()

parts = [EssayPart.from_row(r) for r in rows]
st.subheader(f"Topic {parts[0].topic_code} · {topic_title.get(parts[0].topic_code, '')}")

# ---- write ----------------------------------------------------------

answers: dict[str, str] = {}
declarations: dict[str, DiagramDeclaration | None] = {}

for part in parts:
    st.markdown(f"### ({part.part})  {part.prompt}")
    st.caption(f"{part.max_marks} marks · command word: {part.command_word or '—'}")

    input_mode = st.radio(
        "How are you answering this part?",
        ["⌨️ Type", "📷 Upload a photo"],
        key=f"mode_{part.part}",
        horizontal=True,
    )

    if input_mode == "⌨️ Type":
        answers[part.part] = st.text_area(
            f"Your answer to ({part.part})",
            key=f"answer_{part.part}",
            height=260,
            placeholder="Write as you would in the exam.",
        )
    else:
        if not settings.gemini_api_key:
            st.warning(
                "Photo mode needs GEMINI_API_KEY set in `.env` — that's the "
                "model that reads photos. It isn't set right now, so this "
                "part can't be transcribed. Switch back to **⌨️ Type** above "
                "and write your answer directly instead.",
                icon="📷",
            )
            answers[part.part] = ""
        else:
            photo = st.file_uploader(
                f"Photo of your handwritten answer to ({part.part})",
                type=["jpg", "jpeg", "png", "webp"],
                key=f"photo_{part.part}",
                help="Single image only — JPEG, PNG or WebP. If your answer "
                     "runs onto a second page, fit it into one photo for now.",
            )

            transcribed_key = f"transcribed_{part.part}"

            if photo is not None:
                st.image(photo, caption="Preview", width=420)

                if st.button("Transcribe this photo", key=f"transcribe_btn_{part.part}"):
                    with st.spinner("Reading the photo…"):
                        try:
                            text = transcribe_photo(settings, photo.getvalue(), photo.type)
                            st.session_state[transcribed_key] = text
                        except LLMRateLimitError as exc:
                            st.error(
                                f"Gemini is rate limited. Try again in "
                                f"{exc.friendly_wait()}."
                            )
                        except Exception as exc:  # noqa: BLE001 - surfaced to the student
                            st.error(f"Couldn't transcribe that photo: {exc}")

            st.caption(
                "⚠️ **This text box — not the photo — is what actually gets "
                "marked.** Check it over and fix any misreads before you "
                "submit; a transcription slip here costs marks just like a "
                "wrong answer would."
            )
            answers[part.part] = st.text_area(
                f"Transcribed answer to ({part.part}) — edit as needed",
                value=st.session_state.get(transcribed_key, ""),
                key=f"answer_photo_{part.part}",
                height=260,
                placeholder="Upload a photo and click \"Transcribe this photo\" "
                            "to fill this in, or type directly here.",
            )

    if part.diagram is not None and part.diagram.required:
        with st.expander(f"Declare your diagram for part ({part.part})", expanded=True):
            st.caption(
                "Draw the diagram on paper as normal, then declare it here. "
                "The marker cannot see your drawing — this is what it checks, "
                "and it is exactly what the mark scheme rewards: the shift, its "
                "direction, and what happens to each variable."
            )
            dtype = st.selectbox(
                "Which diagram did you draw?",
                ["(none)"] + list(DIAGRAM_TYPES),
                format_func=lambda k: DIAGRAM_TYPES[k]["label"] if k in DIAGRAM_TYPES else k,
                key=f"dtype_{part.part}",
            )
            if dtype == "(none)":
                declarations[part.part] = None
            else:
                n_shifts = st.number_input(
                    "How many curves shifted?", 0, 3, 1, key=f"nshift_{part.part}"
                )
                shifts = []
                for i in range(int(n_shifts)):
                    c1, c2 = st.columns(2)
                    curve = c1.selectbox(
                        f"Curve {i + 1}", CURVES, key=f"curve_{part.part}_{i}"
                    )
                    direction = c2.selectbox(
                        f"Direction {i + 1}", DIRECTIONS, key=f"dir_{part.part}_{i}"
                    )
                    shifts.append(Shift(curve, direction))

                meta = DIAGRAM_TYPES[dtype]
                effects = {}
                c1, c2 = st.columns(2)
                effects[meta["y_axis"]] = c1.selectbox(
                    f"What happens to {meta['y_axis']}?", EFFECTS,
                    key=f"eff_y_{part.part}",
                )
                effects[meta["x_axis"]] = c2.selectbox(
                    f"What happens to {meta['x_axis']}?", EFFECTS,
                    key=f"eff_x_{part.part}",
                )
                declarations[part.part] = DiagramDeclaration(
                    diagram_type=dtype, shifts=tuple(shifts), effects=effects
                )
    else:
        declarations[part.part] = None

    st.divider()

# ---- mark -----------------------------------------------------------

if st.button("Submit for marking", type="primary"):
    try:
        provider = build_provider(settings)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    marker = EssayMarker(provider, ladder)
    attempt_id = store.start_attempt(mode="single_question", paper_key="paper_2")
    seconds = int(time.time() - st.session_state.get("essay_started", time.time()))

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
            except MarkingError as exc:
                st.error(
                    f"Part ({part.part}) could not be marked reliably: {exc}. "
                    "Nothing was recorded for it — a guessed mark is worse than none."
                )
                continue
            record_essay(
                store,
                attempt_id=attempt_id,
                ordinal=ordinal,
                marked=marked,
                answer_text=answers[part.part],
                seconds_taken=seconds,
            )
            results.append((part, marked))
    store.finish_attempt(attempt_id)
    st.session_state.essay_marks = [
        (p.part, p.max_marks, m.awarded, m.feedback_json()) for p, m in results
    ]

# ---- feedback -------------------------------------------------------

if st.session_state.get("essay_marks"):
    total = sum(a for _, _, a, _ in st.session_state.essay_marks)
    out_of = sum(m for _, m, _, _ in st.session_state.essay_marks)
    label = "Indicative mark" if not ladder.is_calibrated else "Mark"
    st.metric(label, f"{total} / {out_of}")

    for part_key, max_marks, awarded, feedback_json in st.session_state.essay_marks:
        fb = json.loads(feedback_json)
        with st.expander(f"Part ({part_key}) — {awarded} / {max_marks}", expanded=True):
            cols = st.columns(len(fb["levels"]) or 1)
            for col, (ao, level) in zip(cols, fb["levels"].items()):
                col.metric(
                    f"{ao} level {level}", f"{fb['marks_by_ao'].get(ao, 0)} marks"
                )
            for ao, why in fb["justifications"].items():
                st.markdown(f"**{ao}** — {why}")
            if fb.get("cap_note"):
                st.warning(fb["cap_note"], icon="📐")
            st.caption(fb["diagram"])
            if fb.get("next_steps"):
                st.markdown("**Do this next time**")
                for step in fb["next_steps"]:
                    st.markdown(f"- {step}")