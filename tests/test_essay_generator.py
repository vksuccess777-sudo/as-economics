"""Generated essays are not trusted. These are the rejection rules."""

from __future__ import annotations

import json

import pytest

from src.llm.provider import LLMResponse
from src.questions.essay_generator import (
    EssayGenerator,
    EssayValidationError,
    parse_response,
    to_item,
    validate,
    validate_diagram_spec,
)
from src.store.db import Store
from src.syllabus.parser import parse_text
from tests.fixtures import SYLLABUS_EXCERPT

RAW = {
    "part_a": "Explain, using a diagram, how a rise in consumer income affects "
              "the equilibrium price and quantity in the market for new cars.",
    "part_a_command": "explain",
    "part_b": "Discuss whether government subsidies are the most effective way "
              "to raise the consumption of electric vehicles.",
    "part_b_command": "discuss",
    "outcome_code": "2.1.5",
    "diagram": {
        "diagram_type": "supply_demand",
        "shifts": [{"curve": "demand", "direction": "right"}],
        "effects": {"price": "rise", "quantity": "rise"},
        "required": True,
    },
}


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT, level="AS")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.sqlite3")
    s.initialise()
    return s


class FakeProvider:
    name = "fake"

    def __init__(self, payload):
        self.payload = payload

    def generate(self, prompt, **kwargs):
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return LLMResponse(text=text, provider=self.name, model="fake")


def raw(**overrides):
    out = json.loads(json.dumps(RAW))
    out.update(overrides)
    return out


# ------------------------------------------------------------ validation


def test_good_essay_validates():
    validate(to_item(RAW, "2.1"), known_topic_codes={"2.1"})


def test_part_b_without_a_judgement_command_word_is_rejected():
    """A 12-mark 'explain' cannot reach AO3, so it is a defective question."""
    item = to_item(raw(part_b_command="explain"), "2.1")
    with pytest.raises(EssayValidationError, match="carries no judgement"):
        validate(item)


def test_part_a_asking_for_judgement_is_rejected():
    item = to_item(raw(part_a_command="evaluate"), "2.1")
    with pytest.raises(EssayValidationError, match="not an explanation command word"):
        validate(item)


def test_syllabus_leak_is_rejected():
    item = to_item(
        raw(part_a="Explain, with reference to topic 2.1 of the syllabus, how "
                   "demand shifts when income rises."),
        "2.1",
    )
    with pytest.raises(EssayValidationError, match="refers to the syllabus"):
        validate(item)


def test_part_b_repeating_part_a_is_rejected():
    item = to_item(raw(part_b=RAW["part_a"].replace("Explain", "Discuss")), "2.1")
    with pytest.raises(EssayValidationError, match="repeats part"):
        validate(item)


def test_unknown_topic_is_rejected():
    with pytest.raises(EssayValidationError, match="not in the spine"):
        validate(to_item(RAW, "9.9"), known_topic_codes={"2.1"})


# --------------------------------------------------------------- diagram


def test_unknown_curve_name_is_rejected():
    """The killer bug this rule exists for: an invented curve name would mark
    every correct student declaration wrong, because the check is exact."""
    with pytest.raises(EssayValidationError, match="unknown curve"):
        validate_diagram_spec(
            {"diagram_type": "supply_demand",
             "shifts": [{"curve": "consumption", "direction": "right"}],
             "effects": {"price": "rise"}}
        )


def test_unknown_diagram_type_is_rejected():
    with pytest.raises(EssayValidationError, match="unknown diagram type"):
        validate_diagram_spec({"diagram_type": "laffer_curve", "shifts": []})


def test_unknown_effect_is_rejected():
    with pytest.raises(EssayValidationError, match="unknown effect"):
        validate_diagram_spec(
            {"diagram_type": "ad_as",
             "shifts": [{"curve": "AD", "direction": "right"}],
             "effects": {"price level": "increases"}}  # not in the vocabulary
        )


def test_empty_diagram_spec_is_rejected():
    with pytest.raises(EssayValidationError, match="states nothing to check"):
        validate_diagram_spec({"diagram_type": "ppc", "shifts": [], "effects": {}})


def test_diagram_is_optional():
    item = to_item(raw(diagram=None), "2.1")
    validate(item)
    assert item.diagram is None


# --------------------------------------------------------------- banking


def test_banking_writes_two_linked_parts(store, spine):
    generator = EssayGenerator(FakeProvider(RAW), store, spine)
    report = generator.generate_for_topic("2.1", count=1)
    assert report.banked == 1

    groups = store.essay_groups(exclude_answered=False)
    assert len(groups) == 1
    parts = store.essay_parts(groups[0]["group_id"])
    assert [p["max_marks"] for p in parts] == [8, 12]
    assert [json.loads(p["rubric"])["part"] for p in parts] == ["a", "b"]
    assert all(p["paper_key"] == "paper_2" for p in parts)
    assert all(p["origin"] == "generated" for p in parts)


def test_micro_topic_routes_to_section_b(store, spine):
    EssayGenerator(FakeProvider(RAW), store, spine).generate_for_topic("2.1")
    assert store.essay_groups(exclude_answered=False)[0]["section_key"] == "B"


def test_macro_topic_routes_to_section_c(store, spine):
    EssayGenerator(FakeProvider(RAW), store, spine).generate_for_topic("4.3")
    assert store.essay_groups(exclude_answered=False)[0]["section_key"] == "C"


def test_rejected_essay_banks_nothing(store, spine):
    bad = FakeProvider(raw(part_b_command="explain"))
    report = EssayGenerator(bad, store, spine).generate_for_topic("2.1", count=1)
    assert report.banked == 0
    assert len(report.rejected) == 1
    assert store.essay_groups(exclude_answered=False) == []


def test_unparseable_response_is_a_rejection_not_a_crash(store, spine):
    report = EssayGenerator(
        FakeProvider("Sorry, I cannot help with that."), store, spine
    ).generate_for_topic("2.1", count=1)
    assert report.banked == 0
    assert "no JSON object" in report.rejected[0][1]


def test_parse_response_strips_fences():
    assert parse_response("```json\n{\"a\": 1}\n```") == {"a": 1}
