from src.syllabus import assessment as a


def test_economics_has_three_assessment_objectives():
    """Economics 9708 has no AO4 — that is Business 9609."""
    assert set(a.AO_TITLES) == {"AO1", "AO2", "AO3"}
    assert "AO4" not in a.AO_WEIGHTS_AS_LEVEL


def test_ao_weights_sum_to_100_everywhere():
    assert sum(a.AO_WEIGHTS_AS_LEVEL.values()) == 100
    for paper, weights in a.AO_WEIGHTS_BY_PAPER.items():
        assert sum(weights.values()) == 100, paper


def test_paper_marks_match_section_totals():
    for paper in a.PAPERS.values():
        assert sum(s.marks for s in paper.sections) == paper.marks


def test_as_award_is_made_of_two_papers_totalling_90_marks():
    assert set(a.PAPERS) == {"paper_1", "paper_2"}
    assert a.total_as_marks() == 90
    assert a.PAPER_1.percent_of_as + a.PAPER_2.percent_of_as == 100


def test_essay_sections_are_levels_based_but_data_response_is_not():
    assert a.is_levels_based("paper_2", "B")
    assert a.is_levels_based("paper_2", "C")
    assert not a.is_levels_based("paper_2", "A")
    assert not a.is_levels_based("paper_1", "mcq")


def test_evaluation_is_weighted_far_higher_in_paper_2():
    """Drives revision advice: AO3 is where Paper 2 marks are won or lost."""
    assert a.AO_WEIGHTS_BY_PAPER["paper_2"]["AO3"] > a.AO_WEIGHTS_BY_PAPER["paper_1"]["AO3"]


def test_units_route_to_the_right_essay_section():
    assert a.section_focus_for_unit("2") == "micro"
    assert a.section_focus_for_unit("5") == "macro"
    assert a.section_focus_for_unit("9") == "mixed"


def test_every_as_unit_is_classified_micro_or_macro():
    assert a.MICRO_UNITS | a.MACRO_UNITS == {"1", "2", "3", "4", "5", "6"}
    assert not a.MICRO_UNITS & a.MACRO_UNITS
