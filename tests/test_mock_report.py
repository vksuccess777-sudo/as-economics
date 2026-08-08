"""A mock must report against the marks Cambridge sets, not the marks it managed to ask."""

from __future__ import annotations

import pytest

from src.marking.mock_report import (
    EXAM_TYPES,
    MockReportError,
    build_report,
    official_marks,
    shortfall_notes,
)
from src.syllabus import assessment


# ---------------------------------------------------------------- totals


def test_component_totals_come_from_the_syllabus_data():
    assert official_marks("paper1") == assessment.PAPER_1.marks == 30
    assert official_marks("section_a") == 20
    assert official_marks("section_b") == 20
    assert official_marks("section_c") == 20


def test_paper_2_official_total_is_sixty():
    mock = build_report("paper2", {"section_a": (14, 20), "section_b": (11, 20), "section_c": (9, 20)})
    paper2 = mock.paper("paper_2")
    assert paper2 is not None
    assert paper2.official_marks == assessment.PAPER_2.marks == 60
    assert paper2.awarded == 34
    assert paper2.percent == pytest.approx(56.7)


def test_full_mock_totals_ninety_and_that_is_the_as_aggregate():
    mock = build_report(
        "full",
        {
            "paper1": (21, 30),
            "section_a": (13, 20),
            "section_b": (12, 20),
            "section_c": (10, 20),
        },
    )
    assert mock.official_marks == 90 == assessment.total_as_marks()
    assert mock.awarded == 56
    assert mock.covers_whole_as
    assert mock.is_full
    assert mock.gradeable


def test_paper_weightings_match_the_raw_mark_split():
    """33/67 is exactly 30/90 and 60/90, which is why no weighting is applied."""
    assert round(100 * 30 / 90) == assessment.PAPER_1.percent_of_as
    assert round(100 * 60 / 90) == assessment.PAPER_2.percent_of_as


# ------------------------------------------------------- skipped sections


def test_a_skipped_section_still_counts_against_the_paper_total():
    """The bug this module exists for: 34/40 read as 85% on a 60-mark paper."""
    mock = build_report("paper2", {"section_b": (17, 20), "section_c": (17, 20)})
    paper2 = mock.paper("paper_2")
    assert paper2.official_marks == 60
    assert paper2.awarded == 34
    assert paper2.percent == pytest.approx(56.7)   # NOT 85.0
    assert paper2.percent_of_set == pytest.approx(85.0)
    assert [c.key for c in paper2.skipped] == ["section_a"]
    assert not paper2.is_full


def test_skipped_component_is_reported_not_dropped():
    mock = build_report("paper2", {"section_b": (10, 20), "section_c": (10, 20)})
    section_a = mock.component("section_a")
    assert section_a is not None
    assert section_a.sat is False
    assert section_a.awarded == 0
    assert section_a.official_marks == 20
    assert section_a.set_marks == 0


def test_short_paper_one_reports_both_denominators():
    mock = build_report("paper1", {"paper1": (18, 24)})
    p1 = mock.paper("paper_1")
    assert p1.official_marks == 30
    assert p1.not_set == 6
    assert p1.percent == pytest.approx(60.0)
    assert p1.percent_of_set == pytest.approx(75.0)
    assert not p1.is_full
    assert [c.key for c in p1.short] == ["paper1"]


def test_shortfall_notes_name_the_missing_marks():
    mock = build_report("full", {"paper1": (18, 24), "section_b": (10, 20), "section_c": (10, 20)})
    notes = " ".join(shortfall_notes(mock))
    assert "Section A" in notes
    assert "20 marks" in notes
    assert "6 short" in notes


def test_no_shortfall_notes_when_the_sitting_was_complete():
    mock = build_report(
        "full",
        {"paper1": (20, 30), "section_a": (10, 20), "section_b": (10, 20), "section_c": (10, 20)},
    )
    assert shortfall_notes(mock) == []


# ------------------------------------------------------------- gradeable


def test_a_single_paper_is_never_gradeable():
    mock = build_report("paper1", {"paper1": (28, 30)})
    assert mock.is_full
    assert not mock.covers_whole_as
    assert not mock.gradeable


def test_an_incomplete_full_mock_is_not_gradeable():
    mock = build_report("full", {"paper1": (28, 30), "section_b": (18, 20), "section_c": (18, 20)})
    assert mock.covers_whole_as
    assert not mock.gradeable


# ------------------------------------------------------------- validation


def test_results_for_a_component_outside_the_sitting_are_rejected():
    with pytest.raises(MockReportError):
        build_report("paper1", {"paper1": (10, 30), "section_a": (5, 20)})


def test_unknown_exam_type_is_rejected():
    with pytest.raises(MockReportError):
        build_report("paper3", {})


def test_every_exam_type_names_only_known_components():
    from src.marking.mock_report import COMPONENTS

    for components in EXAM_TYPES.values():
        assert set(components) <= set(COMPONENTS)


def test_empty_sitting_scores_zero_out_of_the_full_paper():
    mock = build_report("full", {})
    assert mock.awarded == 0
    assert mock.official_marks == 90
    assert mock.percent == 0.0
    assert mock.percent_of_set == 0.0   # no division by zero
