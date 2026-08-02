"""Ask about a concept and get a syllabus-grounded explanation.

Nothing here writes to the attempt log. Asking a question is not evidence of
what a student knows, and treating it as such would poison the weakness map.
"""

from __future__ import annotations

import streamlit as st

from src.config import settings
from src.llm.exceptions import LLMRateLimitError
from src.llm.provider import GroqProvider
from src.syllabus.models import SyllabusSpine
from src.tutor.explainer import ConceptTutor

st.set_page_config(page_title="Concept Tutor · 9708", page_icon="💡", layout="wide")


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
def get_tutor() -> ConceptTutor | None:
    spine = get_spine()
    if spine is None or not settings.groq_api_key:
        return None
    provider = GroqProvider(settings.groq_api_key, settings.groq_model)
    return ConceptTutor(provider, spine, a_level_spine=get_a_level_spine())


spine = get_spine()

st.title("Concept Tutor")
st.caption(
    "Explanations are grounded in the AS syllabus content only. If a question "
    "falls outside it, the tutor says so rather than guessing."
)

if spine is None:
    st.error("No syllabus spine — run `python scripts/build_syllabus_spine.py` first.")
    st.stop()

if not settings.groq_api_key:
    st.error("GROQ_API_KEY is not set. Copy `.env.example` to `.env` and add your key.")
    st.stop()

tutor = get_tutor()

if "tutor_history" not in st.session_state:
    st.session_state.tutor_history = []

# ---------------------------------------------------------- starters

if not st.session_state.tutor_history:
    st.subheader("Try one of these")
    starters = [
        "Why does the AD curve slope downwards?",
        "What is the difference between a movement along and a shift in demand?",
        "Explain price elasticity of supply and what affects it",
        "How does a specific tax differ from an ad valorem tax?",
        "What causes a floating exchange rate to depreciate?",
        "Explain the difference between cost-push and demand-pull inflation",
    ]
    cols = st.columns(2)
    for i, starter in enumerate(starters):
        if cols[i % 2].button(starter, use_container_width=True, key=f"s_{i}"):
            st.session_state.pending = starter
            st.rerun()

# ------------------------------------------------------------ history

for entry in st.session_state.tutor_history:
    with st.chat_message("user"):
        st.markdown(entry["question"])
    with st.chat_message("assistant"):
        st.markdown(entry["answer"])
        if entry.get("topics"):
            labels = ", ".join(f"{code} {title}" for code, title in entry["topics"])
            st.caption(f"Syllabus coverage: {labels}")

# -------------------------------------------------------------- input

question = st.chat_input("Ask about any AS Economics concept")
if "pending" in st.session_state:
    question = st.session_state.pop("pending")

if question:
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Checking the syllabus..."):
                result = tutor.explain(question)
        except LLMRateLimitError as exc:
            st.warning(
                f"Groq's rate limit has been reached. Try again in about "
                f"{exc.friendly_wait()}. Nothing was lost."
            )
            st.stop()

        if result.is_refusal:
            st.info(result.text)
        else:
            st.markdown(result.text)
            if result.topics:
                labels = ", ".join(f"{code} {title}" for code, title in result.topics)
                st.caption(f"Syllabus coverage: {labels}")

        st.session_state.tutor_history.append(
            {
                "question": question,
                "answer": result.text,
                "topics": result.topics,
            }
        )

if st.session_state.tutor_history:
    if st.sidebar.button("Clear conversation"):
        st.session_state.tutor_history = []
        st.rerun()
