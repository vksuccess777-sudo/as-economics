"""Section A generation is not trusted. These are the rejection rules.

The one that matters most is `unsupported_numbers`: a stimulus with an
invented statistic is the most damaging artifact this project could produce,
because the student would reason correctly from it and still be wrong.
"""

from __future__ import annotations

import copy
import json

import pytest

from src.llm.provider import LLMResponse
from src.questions.data_response import (
    JUNE_2024,
    SECTION_MARKS,
    SHAPES,
    SPECIMEN_2023,
    DataResponseError,
    DataResponseGenerator,
    parse_response,
    quoted_phrases,
    to_item,
    unsupported_numbers,
    validate,
)
from src.reference.dataset import Dataset, Table
from src.store.db import Store
from src.syllabus.parser import parse_text
from tests.fixtures import SYLLABUS_EXCERPT

TABLE = Table(
    headers=("Year", "GDP growth (%)", "Inflation (%)"),
    rows=(
        ("2019", "2.4", "1.8"),
        ("2020", "-9.3", "0.9"),
        ("2021", "7.6", "2.6"),
        ("2022", "4.1", "9.1"),
    ),
)

DATASET = Dataset(
    slug="demo",
    title="Demo indicators",
    source_id="world_bank",
    url="https://data.worldbank.org/indicator/DEMO",
    licence="CC BY 4.0",
    accessed_on="2026-08-06",
    headers=TABLE.headers,
    rows=TABLE.rows,
    notice="Source: World Bank Open Data, CC BY 4.0",
    source_name="World Bank Open Data",
    region="Testland",
)

EXTRACT = (
    "Testland spent the last four years riding a series of shocks. Output fell "
    "sharply in 2020 as restrictions closed much of the service sector, then "
    "rebounded the following year as households spent savings they had been "
    "unable to use. Inflation stayed low through the downturn before climbing "
    "steeply in 2022, driven mainly by imported energy and food prices rather "
    "than by domestic wage pressure. The central bank has described the "
    "position as 'a recovery running out of room', pointing to weak investment "
    "and an ageing workforce. The government argues that supply-side reform, "
    "particularly in training and transport, can raise the economy's capacity "
    "without adding to price pressure. Critics reply that reforms of that kind "
    "take years to work and that households need relief now."
)


def _part(label, marks, prompt, points):
    return {"label": label, "prompt": prompt, "points": points}


def _points(n, band="knowledge"):
    return [
        {"text": f"A creditable point number {i} about the economy.", "band": band}
        for i in range(n)
    ]


def raw_payload():
    return {
        "extract_title": "Testland after the shock",
        "extract": EXTRACT,
        "table_caption": "Table 1.1 Real GDP growth and inflation, Testland",
        "parts": [
            _part("(a)", 2, "Using Table 1.1, compare inflation in 2020 with inflation in 2022.", _points(3)),
            _part("(b)(i)", 2, "Explain the relationship you would expect between economic growth and inflation.", _points(3, "analysis")),
            _part("(b)(ii)", 2, "Consider the extent to which that relationship is evident in the data.", _points(3, "analysis")),
            _part("(c)", 2, "Using the information provided, explain one supply-side constraint on growth.", _points(3)),
            _part(
                "(d)", 6,
                "Assess the likely effects on employment of the change in output shown in the data.",
                _points(5, "analysis") + _points(3, "evaluation"),
            ),
            _part(
                "(e)", 6,
                "Assess whether Testland's position really is 'a recovery running out of room'.",
                _points(5, "analysis") + _points(3, "evaluation"),
            ),
        ],
    }


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT, level="AS")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.sqlite3")
    s.initialise()
    return s


def build(raw=None, shape=SPECIMEN_2023, topic_code="1.1"):
    return to_item(
        raw or raw_payload(),
        topic_code=topic_code,
        dataset=DATASET,
        table=TABLE,
        shape=shape,
    )


class FakeProvider:
    name = "fake"

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        payload = self.payloads[min(self.calls - 1, len(self.payloads) - 1)]
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return LLMResponse(text=text, provider=self.name, model="fake")


# ---- the shapes are real ------------------------------------------------


def test_every_shape_totals_twenty():
    for shape in SHAPES:
        assert shape.total() == SECTION_MARKS, shape.name


def test_every_shape_ends_with_two_six_mark_assess_parts():
    """True of both mark schemes in data/papers/, and the reason the marker
    can apply the 4-analysis/2-evaluation caps at all."""
    for shape in SHAPES:
        tail = shape.parts[-2:]
        assert [p.marks for p in tail] == [6, 6], shape.name
        assert all(p.is_assess and p.caps for p in tail), shape.name


def test_shapes_differ_in_their_opening_parts():
    assert [p.marks for p in SPECIMEN_2023.parts] != [p.marks for p in JUNE_2024.parts]


# ---- invented figures ---------------------------------------------------


def test_a_figure_absent_from_the_table_is_caught():
    assert unsupported_numbers("Growth reached 7.2% in 2021.", TABLE) == ["7.2%"]


def test_a_figure_present_in_the_table_passes():
    assert unsupported_numbers("Growth reached 7.6% in 2021.", TABLE) == []


def test_formatting_differences_are_not_invented_figures():
    assert unsupported_numbers("Inflation of 9.10 per cent", TABLE) == []


def test_table_and_figure_references_are_not_treated_as_data():
    assert unsupported_numbers("Using Table 1.1 and Fig. 2.3, compare...", TABLE) == []


def test_counting_words_are_allowed():
    assert unsupported_numbers("Explain one reason and two consequences.", TABLE) == []


def test_a_year_outside_the_table_is_caught():
    assert unsupported_numbers("Since 2015 the economy has grown.", TABLE) == ["2015"]


def test_generated_extract_with_an_invented_statistic_is_rejected():
    raw = copy.deepcopy(raw_payload())
    raw["extract"] = raw["extract"].replace(
        "imported energy", "imported energy, which rose 43.7%,"
    )
    with pytest.raises(DataResponseError, match="not in the data"):
        validate(build(raw))


# ---- structure ----------------------------------------------------------


def test_a_good_item_validates(spine):
    validate(build(), known_topic_codes=set(spine.topic_codes))


def test_parts_out_of_order_are_rejected():
    raw = copy.deepcopy(raw_payload())
    raw["parts"][0]["label"] = "(z)"
    with pytest.raises(DataResponseError, match="out of order"):
        build(raw)


def test_wrong_number_of_parts_is_rejected():
    raw = copy.deepcopy(raw_payload())
    raw["parts"].pop()
    with pytest.raises(DataResponseError, match="expected 6 parts"):
        build(raw)


def test_too_few_mark_points_makes_full_marks_unreachable():
    raw = copy.deepcopy(raw_payload())
    raw["parts"][0]["points"] = _points(1)
    with pytest.raises(DataResponseError, match="full marks would be unreachable"):
        validate(build(raw))


def test_a_six_mark_part_without_enough_evaluation_points_is_rejected():
    """Two of its six marks are for evaluation. One evaluation point means two
    marks the student cannot reach however well they write."""
    raw = copy.deepcopy(raw_payload())
    raw["parts"][4]["points"] = _points(6, "analysis") + _points(1, "evaluation")
    with pytest.raises(DataResponseError, match="marks are available for evaluation"):
        validate(build(raw))


def test_a_six_mark_part_that_asks_for_no_judgement_is_rejected():
    raw = copy.deepcopy(raw_payload())
    raw["parts"][4]["prompt"] = "Explain the effects on employment shown in the data."
    with pytest.raises(DataResponseError, match="asks for no judgement"):
        validate(build(raw))


def test_extract_must_set_up_a_phrase_a_part_picks_up():
    raw = copy.deepcopy(raw_payload())
    raw["extract"] = raw["extract"].replace("'a recovery running out of room'", "weak")
    raw["parts"][5]["prompt"] = "Assess whether growth is likely to continue."
    with pytest.raises(DataResponseError, match="quotes no phrase"):
        validate(build(raw))


def test_quoted_phrase_extraction():
    assert quoted_phrases("the bank called it 'a soft landing' yesterday") == ["a soft landing"]


def test_short_extract_is_rejected():
    raw = copy.deepcopy(raw_payload())
    raw["extract"] = "Testland grew, then it did not. It called this 'a recovery running out of room'."
    with pytest.raises(DataResponseError, match="extract is"):
        validate(build(raw))


def test_syllabus_leak_in_a_prompt_is_rejected():
    raw = copy.deepcopy(raw_payload())
    # No digits in the replacement: the invented-number check runs first, and
    # a topic code IS a number, so a leak test written with one proves nothing
    # about the leak rule.
    raw["parts"][0]["prompt"] = "Using the table and the syllabus, compare the two years."
    with pytest.raises(DataResponseError, match="refers to the syllabus"):
        validate(build(raw))


def test_unknown_topic_is_rejected(spine):
    with pytest.raises(DataResponseError, match="not in the spine"):
        validate(build(topic_code="99.9"), known_topic_codes=set(spine.topic_codes))


def test_parse_response_survives_markdown_fences():
    assert parse_response('```json\n{"a": 1}\n```') == {"a": 1}


# ---- banking ------------------------------------------------------------


def test_banking_writes_six_linked_parts_worth_twenty(spine, store):
    generator = DataResponseGenerator(FakeProvider([raw_payload()]), store, spine)
    report = generator.generate("1.1", DATASET, shape=SPECIMEN_2023)
    assert report.banked == 1

    groups = store.data_response_groups(exclude_answered=False)
    assert len(groups) == 1
    group_id = groups[0]["group_id"]

    parts = store.data_response_parts(group_id)
    assert len(parts) == 6
    assert sum(p["max_marks"] for p in parts) == SECTION_MARKS
    assert [json.loads(p["rubric"])["part"] for p in parts] == [
        "(a)", "(b)(i)", "(b)(ii)", "(c)", "(d)", "(e)"
    ]


def test_the_stimulus_is_stored_once_not_six_times(spine, store):
    generator = DataResponseGenerator(FakeProvider([raw_payload()]), store, spine)
    generator.generate("1.1", DATASET)
    group_id = store.data_response_groups(exclude_answered=False)[0]["group_id"]
    parts = store.data_response_parts(group_id)
    with_stimulus = [p for p in parts if json.loads(p["rubric"]).get("stimulus")]
    assert len(with_stimulus) == 1

    stimulus = store.data_response_stimulus(group_id)
    assert stimulus["table_rows"][0][0] == "2019"
    assert "CC BY 4.0" in stimulus["attribution"]


def test_a_section_a_group_is_not_offered_as_an_essay(spine, store):
    """Essay screens look for two-part groups; six parts must not appear there."""
    generator = DataResponseGenerator(FakeProvider([raw_payload()]), store, spine)
    generator.generate("1.1", DATASET)
    assert store.essay_groups(exclude_answered=False) == []


def test_rejection_is_retried_once_with_the_reason_fed_back(spine, store):
    bad = copy.deepcopy(raw_payload())
    bad["parts"][0]["prompt"] = "Using Table 1.1, growth was 7.2% — compare the two years."
    provider = FakeProvider([bad, raw_payload()])
    report = DataResponseGenerator(provider, store, spine).generate("1.1", DATASET)
    assert provider.calls == 2
    assert report.banked == 1


def test_both_attempts_failing_banks_nothing(spine, store):
    bad = copy.deepcopy(raw_payload())
    bad["parts"].pop()
    provider = FakeProvider([bad])
    report = DataResponseGenerator(provider, store, spine).generate("1.1", DATASET)
    assert report.banked == 0
    assert provider.calls == 2
    assert store.data_response_groups(exclude_answered=False) == []
