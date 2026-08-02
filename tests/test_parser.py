import pytest

from src.syllabus.parser import SyllabusParseError, parse_text
from tests.fixtures import SYLLABUS_EXCERPT


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT, level="AS")


def test_only_as_units_are_parsed(spine):
    """The A Level content section must not leak into an AS spine."""
    assert [u.code for u in spine.units] == ["1", "2", "4", "6"]
    assert spine.topic("7.1") is None
    assert spine.topic("9.1") is None


def test_unit_titles_strip_the_level_marker(spine):
    unit = next(u for u in spine.units if u.code == "1")
    assert unit.title == "Basic economic ideas and resource allocation"


def test_continued_unit_header_does_not_duplicate_the_unit(spine):
    assert len([u for u in spine.units if u.code == "1"]) == 1


def test_continued_topic_header_does_not_duplicate_the_topic(spine):
    """'2.1 Demand and supply curves continued' must reopen 2.1, not add it."""
    unit_2 = next(u for u in spine.units if u.code == "2")
    assert [t.code for t in unit_2.topics] == ["2.1"]
    assert [o.code for o in unit_2.topics[0].outcomes] == ["2.1.1", "2.1.2"]


def test_outcome_codes_are_not_mistaken_for_topic_codes(spine):
    """'1.1.1 ...' must not match the a.b topic pattern."""
    topic = spine.topic("1.1")
    assert topic is not None
    assert [o.code for o in topic.outcomes] == ["1.1.1", "1.1.2", "1.1.3", "1.1.4"]


def test_bullets_attach_to_their_outcome(spine):
    outcome = spine.outcome("1.1.4")
    assert outcome.bullets == ("what to produce", "how to produce", "for whom to produce")


def test_wrapped_outcome_text_is_rejoined(spine):
    """1.6.3 wraps mid-sentence onto a bare 'market' line."""
    outcome = spine.outcome("1.6.3")
    assert outcome.text.endswith("imperfect information in the market")


def test_wrapped_outcome_with_parenthetical_is_rejoined(spine):
    outcome = spine.outcome("4.3.8")
    assert "long run (LRAS" in outcome.text


def test_wrapped_bullet_text_is_rejoined_to_the_bullet_not_the_outcome(spine):
    """The regression that matters: 6.3.1's second bullet wraps onto 'payments'."""
    outcome = spine.outcome("6.3.1")
    assert len(outcome.bullets) == 2
    assert outcome.bullets[1].endswith("balance of payments")
    # The wrapped word must NOT also have been glued onto the outcome text.
    assert outcome.text.count("payments") == 1
    assert outcome.text.endswith("balance of payments:")


def test_page_furniture_is_discarded(spine):
    text = " ".join(o.searchable_text() for o in spine.iter_outcomes())
    assert "cambridgeinternational" not in text.lower()
    assert "Back to contents" not in text


def test_unit_intro_prose_is_not_captured_as_an_outcome(spine):
    for outcome in spine.iter_outcomes():
        assert not outcome.text.startswith("Candidates will")


def test_topics_are_sorted_numerically(spine):
    unit_1 = next(u for u in spine.units if u.code == "1")
    assert [t.code for t in unit_1.topics] == ["1.1", "1.2", "1.3", "1.6"]


def test_command_words_are_parsed_with_wrapped_meanings(spine):
    assert set(spine.command_words) == {"Analyse", "Assess", "Calculate", "Evaluate"}
    assert spine.command_words["Analyse"].endswith("them")


def test_a_level_section_can_be_parsed_separately():
    a_spine = parse_text(SYLLABUS_EXCERPT, level="A")
    assert [u.code for u in a_spine.units] == ["7", "9"]
    assert a_spine.outcome("9.1.1").bullets == (
        "calculation of:",
        "average and marginal propensities to save (aps and mps)",
    )


def test_missing_section_raises_rather_than_returning_empty():
    with pytest.raises(SyllabusParseError):
        parse_text("nothing that looks like a syllabus at all", level="AS")


def test_round_trip_through_json(tmp_path, spine):
    from src.syllabus.models import SyllabusSpine

    path = spine.save(tmp_path / "spine.json")
    reloaded = SyllabusSpine.load(path)
    assert reloaded.counts() == spine.counts()
    assert reloaded.outcome("1.1.4").bullets == spine.outcome("1.1.4").bullets


def test_helper_properties(spine):
    outcome = spine.outcome("4.3.8")
    assert outcome.topic_code == "4.3"
    assert outcome.unit_code == "4"
    assert "4.3" in spine.topic_codes
