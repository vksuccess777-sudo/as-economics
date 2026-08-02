"""AS Economics — foundation shell.

Deliberately plain. The visual identity is not designed yet: at this stage the
app's job is to prove the spine, the database and the provider are wired up
correctly, and to let you browse the parsed syllabus. Styling comes when the
first real feature (MCQ practice) lands, so it can be designed around actual
content rather than placeholders.
"""

from __future__ import annotations

import streamlit as st

from src.config import settings
from src.store.db import Store
from src.syllabus import assessment
from src.syllabus.models import SyllabusSpine

st.set_page_config(page_title="AS Economics 9708", page_icon="📘", layout="wide")


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

st.title("AS Level Economics 9708")
st.caption(
    f"Syllabus {settings.syllabus_version} · {settings.level} Level · "
    "built by Karthik Varadharajan"
)

if spine is None:
    st.error("No syllabus spine found.")
    st.markdown(
        f"""
        1. Download the 9708 syllabus PDF for your exam year from
           cambridgeinternational.org
        2. Save it as `{settings.syllabus_pdf}`
        3. Run `python scripts/build_syllabus_spine.py`
        4. Reload this page
        """
    )
    st.stop()

counts = spine.counts()
db_counts = store.counts()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Topics", counts["topics"])
col2.metric("Learning outcomes", counts["outcomes"])
col3.metric("Questions banked", db_counts["question"])
col4.metric("Answers marked", db_counts["response"])

tab_syllabus, tab_progress, tab_exam, tab_next = st.tabs(
    ["Syllabus", "Progress", "Exam structure", "What's not built yet"]
)

with tab_syllabus:
    st.caption(
        "Parsed from your local copy of the syllabus PDF. Every question and "
        "every mark in this app is tagged to one of these codes."
    )
    for unit in spine.units:
        with st.expander(f"{unit.code}. {unit.title}  ·  {len(unit.topics)} topics"):
            for topic in unit.topics:
                st.markdown(f"**{topic.code}  {topic.title}**")
                for outcome in topic.outcomes:
                    st.markdown(f"- `{outcome.code}` {outcome.text}")
                    for bullet in outcome.bullets:
                        st.markdown(f"    - {bullet}")

with tab_progress:
    performance = store.topic_performance()
    if not performance:
        st.info(
            "No marked answers yet. Progress appears here automatically once "
            "the MCQ engine starts writing to the attempt log."
        )
    else:
        st.dataframe(performance, use_container_width=True, hide_index=True)
        weakest = store.weakest_topics(limit=5)
        if weakest:
            st.subheader("Weakest topics")
            for row in weakest:
                topic = spine.topic(row["topic_code"])
                label = topic.title if topic else row["topic_code"]
                st.markdown(
                    f"- **{row['topic_code']} {label}** — {row['pct']}% "
                    f"over {row['answered']} answers"
                )

    untested = store.untested_topics(spine.topic_codes)
    st.subheader(f"Not yet tested ({len(untested)} of {counts['topics']} topics)")
    st.caption("Coverage gaps matter as much as low scores — an untested topic is unknown, not safe.")
    st.write(", ".join(untested) if untested else "Every topic has been tested.")

with tab_exam:
    for paper in assessment.PAPERS.values():
        st.subheader(f"{paper.label}")
        st.caption(
            f"{paper.minutes} minutes · {paper.marks} marks · "
            f"{paper.percent_of_as}% of the AS Level"
        )
        for section in paper.sections:
            levels = (
                " · levels-based mark scheme"
                if assessment.is_levels_based(paper.key, section.key)
                else ""
            )
            choice = (
                f"choose 1 of {section.choose_from}"
                if section.choose_from > 1
                else "compulsory"
            )
            st.markdown(
                f"- **{section.key}** — {section.label} · {section.marks} marks · "
                f"{choice}{levels}"
            )
    st.subheader("Assessment objectives")
    st.caption("Economics has three AOs. There is no separate 'Application' objective.")
    for ao, title in assessment.AO_TITLES.items():
        p1 = assessment.AO_WEIGHTS_BY_PAPER["paper_1"][ao]
        p2 = assessment.AO_WEIGHTS_BY_PAPER["paper_2"][ao]
        overall = assessment.AO_WEIGHTS_AS_LEVEL[ao]
        st.markdown(
            f"- **{ao} {title}** — {overall}% overall · Paper 1 {p1}% · Paper 2 {p2}%"
        )

with tab_next:
    st.markdown(
        """
        Built so far — the foundation only:

        - syllabus spine parsed from the official PDF, with sanity checks
        - attempt log schema (questions, attempts, responses, calibration cases)
        - per-topic performance view that the dashboard reads from
        - assessment structure and AO weightings
        - Groq provider with rate-limit handling, ready for the full fallback chain

        Not built yet, in intended order:

        1. **MCQ generator + timed test** — zero LLM tokens at marking time
        2. **Syllabus knowledge base Q&A** — refuses A Level content by design
        3. **Essay marker** — two-pass, levels-based, marks computed from levels
        4. **Weakness dashboard** — mostly falls out of the attempt log above

        Known gaps recorded deliberately: diagram marking (AD/AS, PPC) is not
        handled, and no past-paper material is ingested.
        """
    )
