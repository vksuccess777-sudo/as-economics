"""The knowledge base: revision notes, one per syllabus topic.

Reading a note costs nothing — they are written in batch by
`scripts/build_notes.py` and stored. This page is a reader, not a generator.
If a topic has no note, it says which command writes it rather than quietly
producing one at read time and spending the daily budget on a page view.
"""

from __future__ import annotations

import streamlit as st

from src.config import settings
from src.notes.generator import Note
from src.diagrams import scope as diagram_scope
from src.diagrams import embed as diagram_embed
from src.diagrams.canvas import DiagramError
from src.store.db import Store
from src.syllabus.models import SyllabusSpine

st.set_page_config(page_title="Knowledge Base · 9708", page_icon="📚", layout="wide")


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
#
# This check lives in the page rather than in a helper module on purpose: a
# helper would be imported, and an imported helper can itself be the stale
# thing. Page scripts are re-read from disk on every rerun, so this always runs
# the current version.
REQUIRED_STORE_METHODS = ("note", "note_topics", "upsert_note",
                          "observed_mistakes")
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



st.title("Knowledge base")
st.caption(
    "Revision notes generated from the syllabus outcomes and stored. Reading "
    "them spends nothing."
)

if spine is None:
    st.error("No syllabus spine — run `python scripts/build_syllabus_spine.py` first.")
    st.stop()

have = set(store.note_topics())
all_topics = [(t.code, t.title) for t in spine.iter_topics()]

if not have:
    st.info(
        "No notes yet. Write them in one batch:\n\n"
        "```\npython scripts/build_notes.py --all\n```\n\n"
        "29 topics. Re-running a topic replaces its note rather than adding a "
        "second one."
    )
    st.stop()

st.progress(
    len(have) / len(all_topics),
    text=f"{len(have)} of {len(all_topics)} topics have notes",
)

# The Concept Tutor cites its sources and offers "Open the note" against each
# one; it leaves the topic here on its way through. Read once and cleared, so a
# later manual choice is not overridden on the next rerun. Resolved to an index
# rather than a widget key: a stale key holding a code that is not in the
# current unit's options is an exception, and this is navigation, not state.
_jump_unit = st.session_state.pop("kb_unit", None)
_jump_topic = st.session_state.pop("kb_topic", None)

with st.sidebar:
    st.header("Topic")
    unit_titles = {u.code: u.title for u in spine.units}
    unit_codes = list(unit_titles)
    unit = st.selectbox(
        "Chapter", unit_codes,
        format_func=lambda c: f"{c} · {unit_titles[c][:34]}",
        index=unit_codes.index(_jump_unit) if _jump_unit in unit_codes else 0,
    )
    in_unit = [(c, t) for c, t in all_topics if c.split(".")[0] == unit]
    _codes = [c for c, _ in in_unit]
    code = st.radio(
        "Topic",
        _codes,
        index=_codes.index(_jump_topic) if _jump_topic in _codes else 0,
        format_func=lambda c: (
            f"{'✓' if c in have else '·'} {c} {dict(all_topics)[c][:30]}"
        ),
    )

row = store.note(code)
title = dict(all_topics)[code]
st.subheader(f"{code} · {title}")

if row is None:
    st.warning(
        f"No note for {code} yet.\n\n"
        f"```\npython scripts/build_notes.py --topic {code}\n```"
    )
    st.stop()

note = Note.from_row(row)

tab_learn, tab_apply, tab_avoid = st.tabs(
    ["Understand", "Use in the exam", "What loses marks"]
)

with tab_learn:
    st.markdown("#### Definitions")
    for d in note.section("definitions"):
        st.markdown(f"**{d.get('term', '')}** — {d.get('meaning', '')}")

    st.markdown("#### Core chains")
    st.caption(
        "Each one ends in an effect on a named variable. That ending is where "
        "the analysis marks are."
    )
    for idea in note.section("core_ideas"):
        st.markdown(f"- {idea}")

with tab_apply:
    # The note already SAID which diagram to draw and what to label. Now it
    # draws it. Which diagrams belong to this topic is decided by
    # diagrams.scope against the parsed spine, not by a hand-written list —
    # that is what keeps A Level diagrams (externalities, topic 7.4) off an
    # AS screen.
    drawable = diagram_scope.for_topic(spine, code) if spine else ()
    if drawable:
        st.markdown("#### Diagrams")
        size = st.radio(
            "Diagram size",
            list(diagram_embed.SIZES),
            index=list(diagram_embed.SIZES).index(diagram_embed.DEFAULT_SIZE),
            horizontal=True,
            key=f"kb_dgsize_{code}",
        )
        for entry in drawable:
            st.markdown(f"**{entry.label}**")
            choices = {}
            for name, values in entry.options.items():
                choices[name] = st.radio(
                    name.replace("_", " "),
                    list(values),
                    horizontal=True,
                    key=f"kb_dg_{code}_{entry.key}_{name}",
                )
            try:
                st.markdown(
                    diagram_embed.as_html(entry.render(**choices), size),
                    unsafe_allow_html=True,
                )
            except DiagramError as exc:
                st.caption(f"Could not draw that combination: {exc}")
        st.caption(
            "Drawn in code from the axes and curves, not generated — the "
            "intersection is always where the caption says it is."
        )

    diagrams = note.section("diagrams")
    if diagrams:
        st.markdown("#### What to label" if drawable else "#### Diagrams")
        for d in diagrams:
            st.markdown(f"**{d.get('name', '')}**")
            st.markdown(f"- Label: {d.get('what_to_label', '')}")
            st.markdown(f"- Shifts: {d.get('what_shifts', '')}")
    elif not drawable:
        st.caption("No diagram is required for this topic.")

    st.markdown("#### Evaluation lines")
    st.caption("AO3 is 25% of the AS mark. These are the lines that earn it.")
    for e in note.section("evaluation"):
        st.markdown(f"- {e}")

    st.markdown("#### How it is tested")
    for n in note.section("exam_notes"):
        st.markdown(f"- {n}")

with tab_avoid:
    # Two blocks, kept apart on purpose. The first is a model's reasoning about
    # what a student is likely to get wrong; the second is what examiners
    # reported candidates actually getting wrong across a whole cohort. They
    # are not the same kind of claim and must not read as though they are.
    st.markdown("#### Common mistakes")
    st.caption("Written from the syllabus outcomes — what tends to lose marks here.")
    for m in note.section("common_mistakes"):
        st.markdown(f"- {m}")
    st.caption(
        "The AI Coach page cross-checks these against the answers actually given, "
        "so a mistake made twice becomes a planned session."
    )

    observed = store.observed_mistakes(code)
    if observed:
        st.markdown("#### What examiners actually reported")
        st.caption(
            "Paraphrased from a Cambridge Principal Examiner Report — mistakes "
            "made by real candidates, not predictions."
        )
        for row in observed:
            st.markdown(f"- {row['text']}")
            st.caption(f"{row['paper']} · {row['ref']}")
    else:
        st.caption(
            "No examiner-reported mistakes are filed against this topic. Run "
            "`python scripts/ingest_examiner_report.py --dry-run` to see what "
            "a report you have downloaded would add."
        )

    general = store.observed_mistakes(None, kind="technique")
    if general:
        with st.expander("Examiner advice that applies to every topic"):
            for row in general:
                st.markdown(f"- {row['text']}")

st.divider()

# Link-out. Imported defensively: a server started before this upgrade has the
# old src/ in sys.modules and would raise ImportError here instead of saying so.
try:
    from src.reference.panel import go_deeper
except ImportError:
    go_deeper = None

if go_deeper is None:
    st.caption(
        "This Streamlit server predates the link-out upgrade — restart it "
        "(Ctrl+C, then `streamlit run Home.py`) to see other sites for this topic."
    )
else:
    go_deeper(spine, code, title)

st.caption(f"Written by {row.get('model') or 'unknown model'} · {row['created_at'][:10]}")
