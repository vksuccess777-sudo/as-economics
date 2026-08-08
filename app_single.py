"""Fallback entry point: every screen from one script.

Use this when `streamlit run Home.py` gives you a working app with an empty
sidebar. Streamlit builds that sidebar by globbing `pages/*.py` next to the
entry script; if an extraction flattened the folders, or the directory is named
differently, the glob comes back empty and the app looks like the features were
never built. This file does not use that mechanism at all — it routes with a
radio button.

It does NOT duplicate any screen code. Each screen is executed from the same
file `pages/` holds, so the two entry points can never drift apart. If a screen
file is missing, this page says which one rather than failing silently.

`streamlit run Home.py` remains the normal way in. This is the escape hatch.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="AS Economics 9708", page_icon="📘", layout="wide")

# Each screen calls st.set_page_config itself. Calling it twice in one run is an
# error, so after ours it becomes a no-op for the rest of this script.
st.set_page_config = lambda *args, **kwargs: None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parent

SCREENS = {
    "Home": "Home.py",
    "MCQ practice — sit a Paper 1 mock": "pages/1_MCQ_Practice.py",
    "Concept tutor": "pages/2_Concept_Tutor.py",
    "Essay practice — Paper 2": "pages/3_Essay_Practice.py",
    "AI Coach — progress, diagnosis and plan": "pages/4_AI_Coach.py",
    "Knowledge base": "pages/5_Knowledge_Base.py",
    "Worksheet helper — solve a sheet from school": "pages/6_Worksheet_Helper.py",
    "Mock test — full Cambridge-pattern sitting": "pages/7_Mock_Test.py",
}

with st.sidebar:
    st.caption("Single-file mode")
    choice = st.radio("Screen", list(SCREENS), label_visibility="collapsed")
    st.divider()
    st.caption(
        "Using this because the normal sidebar was empty? Run "
        "`python scripts/check_pages.py` — it names the cause."
    )

target = ROOT / SCREENS[choice]

if not target.exists():
    st.error(f"Screen file missing: `{SCREENS[choice]}`")
    st.markdown(
        "The file is not where it should be. Run "
        "`python scripts/check_pages.py` — if your extraction flattened the "
        "folders, it will tell you exactly which files to move into `pages/`."
    )
    st.stop()

# run_name is deliberately not "__main__": these are Streamlit scripts, and
# running them under their own module name keeps any __main__ guard inert.
runpy.run_path(str(target), run_name="__streamlit_screen__")
