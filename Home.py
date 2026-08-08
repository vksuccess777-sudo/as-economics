"""AS Economics 9708 — Welcome / Home.

This is the front door. It used to double as a spine browser, a progress
dump and a developer roadmap; all three were useful while the app was being
built but do not belong on a page a student lands on first. That content has
moved:

- topic-level progress lives on the AI Coach page, alongside the diagnosis
  and plan it now feeds — it already had a proper "thin evidence" treatment
- the full syllabus spine and paper structure are still here, but folded
  into expanders under "Reference", not forced on every visitor
- the internal build roadmap ("what's not built yet") has been removed from
  the UI entirely — it belongs in README.md / START_HERE.md for maintainers,
  not in front of a learner

The filename is `Home.py` rather than `app.py` on purpose: Streamlit derives
the sidebar's first nav label from the entry script's filename, so this is
the only way to make it read "Home" instead of "App" without moving to the
newer st.navigation API (which would mean rewriting page discovery — see
tests/test_app_entrypoints.py for why that is deliberately not done here).
Run it exactly as before, just with the new name:

    streamlit run Home.py
"""

from __future__ import annotations

import streamlit as st

from src import config as config_module
from src.config import settings
from src.store.db import Store
from src.syllabus import assessment
from src.syllabus.models import SyllabusSpine

st.set_page_config(page_title="Welcome · AS Economics 9708", page_icon="🎉", layout="wide")

STUDENT_NAME = "Arjit K"

st.markdown(
    """
    <style>
    .welcome-banner {
        background: linear-gradient(120deg, #6C63FF 0%, #FF6FA5 50%, #FFB86C 100%);
        border-radius: 20px;
        padding: 1.6rem 2rem;
        margin-bottom: 1.2rem;
        box-shadow: 0 8px 24px rgba(108, 99, 255, 0.25);
    }
    .welcome-banner h1 {
        color: #ffffff;
        font-size: 2.1rem;
        margin: 0;
        text-shadow: 0 2px 6px rgba(0,0,0,0.15);
    }
    .welcome-banner p {
        color: #fdfdfd;
        font-size: 1.05rem;
        margin: 0.4rem 0 0 0;
        opacity: 0.95;
    }
    div[data-testid="stContainer"] > div[data-testid="stVerticalBlockBorderWrapper"] {
        transition: transform 0.15s ease, box-shadow 0.15s ease;
        border-radius: 16px !important;
    }
    div[data-testid="stContainer"] > div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        transform: translateY(-3px);
        box-shadow: 0 10px 20px rgba(0,0,0,0.08);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div class="welcome-banner">
        <h1>🎉 Welcome back, {STUDENT_NAME}! 🚀📘✨</h1>
        <p>Ready to level up your Economics today? Let's turn practice into progress — one topic at a time! 🌟</p>
    </div>
    """,
    unsafe_allow_html=True,
)


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

with st.sidebar.expander("🔧 Debug info (temporary — remove once fixed)"):
    try:
        import streamlit as _st_check
        spine_secret_present = "SYLLABUS_SPINE_B64" in _st_check.secrets
        spine_secret_len = len(_st_check.secrets.get("SYLLABUS_SPINE_B64", "")) if spine_secret_present else 0
        db_secret_present = "DB_SQLITE_B64" in _st_check.secrets
        db_secret_len = len(_st_check.secrets.get("DB_SQLITE_B64", "")) if db_secret_present else 0
    except Exception as exc:  # noqa: BLE001
        spine_secret_present = spine_secret_len = db_secret_present = db_secret_len = f"error: {exc}"
    st.write("spine_path exists:", settings.spine_path.exists())
    st.write("SYLLABUS_SPINE_B64 present / length:", spine_secret_present, spine_secret_len)
    st.write("db_path:", str(settings.db_path))
    st.write("db_path exists:", settings.db_path.exists())
    if settings.db_path.exists():
        st.write("db_path size (bytes):", settings.db_path.stat().st_size)
    st.write("DB_SQLITE_B64 present / length:", db_secret_present, db_secret_len)
    st.write("bootstrap attempted:", getattr(config_module, "_bootstrap_attempted", "n/a"))
    st.write("bootstrap errors:", getattr(config_module, "_bootstrap_errors", "n/a"))

# ---------------------------------------------------------------------------
# Hero
# ---------------------------------------------------------------------------

st.title("📘 AS Level Economics 9708")
st.markdown(
    f"##### A syllabus-accurate practice environment for Cambridge AS Economics "
    f"({settings.syllabus_version})"
)
st.caption("Designed and Implemented by **Karthik Varadharajan**")

st.divider()

if spine is None:
    st.error("No syllabus spine found yet — this app has nothing to teach from.")
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

# ---------------------------------------------------------------------------
# What this is
# ---------------------------------------------------------------------------

st.subheader("What this is")
st.markdown(
    """
    Most AI study tools mark against vibes: a model reads your answer and
    decides, from nothing, whether it "seems right." This one doesn't. Every
    question, every mark, and every piece of feedback here is anchored to the
    actual **Cambridge 9708 syllabus** — parsed directly from the official
    specification, not guessed at — so what you practise and what the exam
    tests are the same thing.

    Where a mark can be computed with plain arithmetic (MCQs, levels-based
    essay bands), it is — no model, no drift, no re-marking the same script
    two different ways. A language model is only ever used where judgement
    genuinely requires one: explaining a concept, or turning a mark scheme
    into specific feedback. That split is deliberate, and it's what keeps
    every score in this app trustworthy enough to act on.
    """
)

# ---------------------------------------------------------------------------
# How this environment works
# ---------------------------------------------------------------------------

st.subheader("🛤️ How it works")

step1, step2, step3, step4 = st.columns(4)
with step1:
    with st.container(border=True):
        st.markdown("### 🖊️ 1 · Practise")
        st.caption(
            "Sit MCQ papers, write essays, or ask the tutor about a concept "
            "you're stuck on."
        )
with step2:
    with st.container(border=True):
        st.markdown("### ✅ 2 · Get marked")
        st.caption(
            "MCQs mark instantly against the answer key. Essays are marked "
            "levels-first, the way examiners actually do it."
        )
with step3:
    with st.container(border=True):
        st.markdown("### 🔍 3 · See the gaps")
        st.caption(
            "Every mark is tagged to a syllabus code, so weak topics — and "
            "untested ones — surface on the AI Coach, not just low scores."
        )
with step4:
    with st.container(border=True):
        st.markdown("### 🏆 4 · Close them")
        st.caption(
            "The AI Coach turns those gaps into a prioritised revision plan "
            "against your target grade."
        )

st.write("")

# ---------------------------------------------------------------------------
# Explore the modules
# ---------------------------------------------------------------------------

st.subheader("🚀 Explore")

modules = [
    ("pages/1_MCQ_Practice.py", "📝", "MCQ Practice", "Sit a timed Paper 1 mock, marked instantly."),
    ("pages/2_Concept_Tutor.py", "💡", "Concept Tutor", "Ask about anything on the AS syllabus, in plain language."),
    ("pages/3_Essay_Practice.py", "✍️", "Essay Practice", "Write a Paper 2 essay — type it or snap a photo — and get levels-based feedback."),
    ("pages/4_AI_Coach.py", "🎯", "AI Coach", "Progress, diagnosis, target grade, and a plan to close the gap."),
    ("pages/5_Knowledge_Base.py", "📚", "Knowledge Base", "Revision notes for every topic on the syllabus."),
    ("pages/6_Worksheet_Helper.py", "📄", "Worksheet Helper", "Upload a worksheet from school and work through it question by question."),
]

row1 = st.columns(3)
row2 = st.columns(3)  # 6 modules: 3 + 3
for col, (path, icon, label, blurb) in zip(row1 + row2, modules):
    with col:
        with st.container(border=True):
            st.markdown(f"### {icon} {label}")
            st.caption(blurb)
            st.page_link(path, label=f"Open {label}", icon="👉")

st.write("")

# ---------------------------------------------------------------------------
# At a glance
# ---------------------------------------------------------------------------

st.subheader("At a glance")

counts = spine.counts()
db_counts = store.counts()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Syllabus topics", counts["topics"])
col2.metric("Learning outcomes", counts["outcomes"])
col3.metric("Questions banked", db_counts["question"])
col4.metric("Answers marked", db_counts["response"])

st.write("")

# ---------------------------------------------------------------------------
# Reference — syllabus spine and paper structure, for anyone who wants the
# detail. Folded away so it doesn't compete with the four sections above.
# ---------------------------------------------------------------------------

st.subheader("Reference")

with st.expander("Browse the full syllabus"):
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

with st.expander("Paper structure & assessment objectives"):
    for paper in assessment.PAPERS.values():
        st.markdown(f"**{paper.label}**")
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
        st.write("")

    st.markdown("**Assessment objectives**")
    st.caption("Economics has three AOs. There is no separate 'Application' objective.")
    for ao, title in assessment.AO_TITLES.items():
        p1 = assessment.AO_WEIGHTS_BY_PAPER["paper_1"][ao]
        p2 = assessment.AO_WEIGHTS_BY_PAPER["paper_2"][ao]
        overall = assessment.AO_WEIGHTS_AS_LEVEL[ao]
        st.markdown(
            f"- **{ao} {title}** — {overall}% overall · Paper 1 {p1}% · Paper 2 {p2}%"
        )

st.divider()
st.caption("AS Level Economics 9708 · Designed and Implemented by Karthik Varadharajan")