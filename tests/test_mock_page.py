"""Drive the Mock Test screen headlessly.

This screen had no test of any kind, which is how a Paper 2 could be reported
as three separate section metrics with nothing ever adding them up. The report
path below builds the sitting in session state and asserts what the student
actually reads: a mark out of 60 for Paper 2, out of 90 for a full mock, and
an explicit statement of any marks the bank could not set.

Skipped rather than failed without a parsed spine — a fresh clone has none,
and the parse is the user's own copy of the syllabus.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from streamlit.testing.v1 import AppTest

from src.config import settings

PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "7_Mock_Test.py")

# See the note in test_tutor_page.py: the first AppTest run in a process pays
# for cold Streamlit start-up and cold caches, and a machine ten times slower
# than the one this was written on will exceed a tight ceiling on that run
# alone.
FIRST_RUN_TIMEOUT = 120

pytestmark = pytest.mark.skipif(
    not settings.spine_path.exists(),
    reason="needs a parsed spine — local to the user's machine",
)


def _text(at: AppTest) -> str:
    chunks = []
    for collection in (at.markdown, at.caption, at.subheader, at.header, at.warning, at.info):
        chunks += [getattr(e, "value", "") for e in collection]
    for metric in at.metric:
        chunks += [metric.label, str(metric.value), str(getattr(metric, "delta", ""))]
    return " ".join(c for c in chunks if c)


# ------------------------------------------------------------------ setup


def test_setup_screen_loads():
    at = AppTest.from_file(PAGE, default_timeout=FIRST_RUN_TIMEOUT)
    at.run()
    assert not at.exception


def test_setup_screen_states_the_marks_of_every_component():
    at = AppTest.from_file(PAGE, default_timeout=FIRST_RUN_TIMEOUT)
    at.run()
    text = _text(at)
    assert "30 marks" in text          # Paper 1
    assert "20 marks" in text          # each Paper 2 section
    assert "60 marks" in text          # Paper 2


# ----------------------------------------------------------------- report


def _fake_mcq_paper(score: int, total: int):
    return SimpleNamespace(
        score=score,
        total=total,
        percent=round(100.0 * score / total, 1) if total else 0.0,
        answers=[],
        wrong_answers=lambda: [],
    )


def _fake_points_part(awarded: int, max_marks: int, label: str):
    return SimpleNamespace(
        label=label,
        awarded=awarded,
        max_marks=max_marks,
        per_point=[],
        missed_advice="",
    )


def _report(session: dict) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=FIRST_RUN_TIMEOUT)
    for key, value in session.items():
        at.session_state[key] = value
    at.run()
    return at


def _base(exam_type: str, flow: list[str]) -> dict:
    return {
        "mock_flow": flow,
        "mock_flow_idx": len(flow),   # past the end == the report
        "mock_topic_filter": None,
        "mock_exam_type": exam_type,
        "mock_paper2_started_at": None,
    }


def test_paper_one_only_reports_out_of_thirty():
    at = _report(
        _base("paper1", ["paper1"])
        | {
            "mock_results": {"paper1": _fake_mcq_paper(21, 30)},
            "mock_set_marks": {"paper1": 30},
        }
    )
    assert not at.exception
    text = _text(at)
    assert "21 / 30" in text
    assert "70.0%" in text


def test_a_short_paper_one_still_reports_out_of_thirty_and_says_so():
    at = _report(
        _base("paper1", ["paper1"])
        | {
            "mock_results": {"paper1": _fake_mcq_paper(18, 24)},
            "mock_set_marks": {"paper1": 24},
        }
    )
    assert not at.exception
    text = _text(at)
    assert "18 / 30" in text
    assert "24 of the 30 marks" in text
    assert "75.0%" in text          # the fairer figure, stated as well


def test_paper_two_gets_a_total_out_of_sixty():
    at = _report(
        _base("paper2", ["section_a", "section_b", "section_c"])
        | {
            "mock_results": {
                "section_a": [_fake_points_part(2, 2, "(a)"), _fake_points_part(10, 18, "(b)")],
                "section_b": [],
                "section_c": [],
            },
            "mock_set_marks": {"section_a": 20, "section_b": 20, "section_c": 20},
        }
    )
    assert not at.exception
    text = _text(at)
    assert "/ 60" in text


def test_a_skipped_section_is_counted_against_the_paper_not_dropped():
    """The bug: 34/40 read as 85% on a paper worth 60."""
    at = _report(
        _base("paper2", ["section_b", "section_c"])
        | {
            "mock_results": {"section_b": [], "section_c": []},
            "mock_set_marks": {"section_b": 20, "section_c": 20},
        }
    )
    assert not at.exception
    text = _text(at)
    assert "0 / 60" in text
    assert "Section A" in text
    assert "not sat" in text or "was not sat" in text


def test_a_full_mock_totals_ninety():
    at = _report(
        _base("full", ["paper1", "section_a", "section_b", "section_c"])
        | {
            "mock_results": {
                "paper1": _fake_mcq_paper(24, 30),
                "section_a": [_fake_points_part(12, 20, "(a)")],
                "section_b": [],
                "section_c": [],
            },
            "mock_set_marks": {
                "paper1": 30, "section_a": 20, "section_b": 20, "section_c": 20,
            },
        }
    )
    assert not at.exception
    text = _text(at)
    assert "/ 90" in text
    assert "AS aggregate" in text
