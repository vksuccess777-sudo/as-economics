"""The MCQ setup panel, driven headlessly.

Selection is the one part of this screen with no other test: build_paper has
unit tests, marking has unit tests, and the pickers that decide what reaches
build_paper had none. A filter that quietly selects the wrong topics produces a
plausible paper, which is the kind of fault nobody notices.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.config import settings

PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "1_MCQ_Practice.py")

pytestmark = pytest.mark.skipif(
    not settings.spine_path.exists() or not settings.db_path.exists(),
    reason="needs the local spine and question bank",
)


def _run(**state) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=30)
    for key, value in state.items():
        at.session_state[key] = value
    at.run()
    return at


def test_the_setup_panel_offers_chapters_and_topics():
    at = _run()
    assert not at.exception
    labels = [m.label for m in at.multiselect]
    assert any("Chapter" in label for label in labels)
    assert any("Topic" in label for label in labels)


def test_choosing_a_chapter_narrows_the_topic_options():
    at = _run()
    at.multiselect(key="mcq_chapters").set_value(["4"]).run()
    assert not at.exception
    options = at.multiselect(key="mcq_topics").options
    assert options and all(code.startswith("4.") for code in options)


def test_a_topic_can_be_chosen_without_choosing_its_chapter_first():
    at = _run()
    options = at.multiselect(key="mcq_topics").options
    assert len(options) > 6, "with no chapter chosen, every topic should be offered"


def test_the_tutor_handover_seeds_both_pickers_without_locking_them():
    at = _run(practice_topic="4.1")
    assert not at.exception
    assert at.session_state["mcq_chapters"] == ["4"]
    assert at.session_state["mcq_topics"] == ["4.1"]
    assert not at.multiselect(key="mcq_topics").disabled


def test_deselecting_a_chapter_does_not_strand_its_topics():
    """Streamlit raises when session state holds a value that is not in the
    widget's options, so the stale topic has to be cleared, not ignored."""
    at = _run(practice_topic="4.1")
    at.multiselect(key="mcq_chapters").set_value(["2"]).run()
    assert not at.exception
    assert at.session_state["mcq_topics"] == []
