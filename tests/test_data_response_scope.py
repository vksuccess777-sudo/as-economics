"""Three gates added after reading the first question this actually produced.

The first generated topic-4.6 item put 8 of its 20 marks on CPIH, asked for a
subtraction where both real papers ask for a percentage change, and read a
single cell where both ask for a trend. None of that was invented data, so the
figures gate passed it. These are the rules that would have caught it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.questions.data_response import (  # noqa: E402
    KIND_GUIDANCE,
    MAX_EXTRACT_WORDS,
    MIN_EXTRACT_WORDS,
    SHAPES,
    SHAPES_BY_NAME,
    DataResponseError,
    build_prompt,
    off_syllabus_acronyms,
    to_item,
    TARGET_EXTRACT_WORDS,
    schema_text,
    scope_instruction,
    syllabus_acronyms,
    validate,
)
from src.reference.dataset import Dataset, Table  # noqa: E402
from src.syllabus.models import SyllabusSpine  # noqa: E402
from src.syllabus.parser import parse_text  # noqa: E402

from tests.fixtures import SYLLABUS_EXCERPT  # noqa: E402


SHAPE = SHAPES_BY_NAME["june_2024"]

TABLE = Table(
    headers=("Year", "CPIH annual rate (%)", "CPI annual rate (%)"),
    rows=(("2021", "2.5", "2.6"), ("2022", "7.9", "9.1"), ("2023", "6.8", "7.3")),
)

DATASET = Dataset(
    slug="uk-inflation",
    title="CPIH and CPI annual inflation rate, United Kingdom",
    source_id="ons",
    url="https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/l55o/mm23",
    licence="OGL v3",
    accessed_on="2026-08-07",
    headers=TABLE.headers,
    rows=TABLE.rows,
    notice="",
    source_name="UK Office for National Statistics",
    region="United Kingdom",
    units="% annual change",
)

EXTRACT = " ".join(
    ["The 'general rise in prices' has concerned policymakers for several years."]
    + ["Prices rose quickly and then eased across the period shown."] * 12
)


def part(label: str, prompt: str, marks: int, points: int, bands=None) -> dict:
    bands = bands or ["knowledge"] * points
    return {
        "label": label,
        "prompt": prompt,
        "points": [{"text": f"a creditable mark point number {i}", "band": bands[i]} for i in range(points)],
    }


def payload(**overrides) -> dict:
    parts = [
        part("(a)(i)", "Using Table 1.1, identify the overall trend in the CPI "
                       "annual rate between 2021 and 2023.", 1, 1),
        part("(a)(ii)", "Calculate the percentage change in the CPI annual rate "
                        "between 2021 and 2022.", 1, 1),
        part("(b)", "Explain what is meant by a 'general rise in prices'.", 2, 2),
        part("(c)", "Explain two possible causes of the rise in prices shown.", 4, 4),
        part("(d)", "Assess the effects of rising prices on the economy.", 6, 6,
             ["analysis"] * 4 + ["evaluation"] * 2),
        part("(e)", "Assess whether a 'general rise in prices' always harms "
                    "consumers.", 6, 6, ["analysis"] * 4 + ["evaluation"] * 2),
    ]
    raw = {
        "extract_title": "Prices in the United Kingdom",
        "extract": EXTRACT,
        "table_caption": "Table 1.1 CPIH and CPI annual inflation rate",
        "parts": parts,
    }
    for label, prompt in overrides.items():
        target = label.replace("_", "").replace("part", "")
        for p in raw["parts"]:
            if p["label"].replace("(", "").replace(")", "") == target:
                p["prompt"] = prompt
    return raw


def build(raw: dict):
    return to_item(raw, topic_code="4.6", dataset=DATASET, table=TABLE, shape=SHAPE)


@pytest.fixture(scope="module")
def spine() -> SyllabusSpine:
    return parse_text(SYLLABUS_EXCERPT, level="AS")


@pytest.fixture
def allowed(spine) -> set[str]:
    return syllabus_acronyms(spine)


def check(raw: dict, allowed: set[str]) -> None:
    validate(build(raw), allowed_acronyms=allowed)


# ---- the baseline must pass, or every rejection below proves nothing -----


def test_a_clean_item_passes(allowed):
    check(payload(), allowed)


# ---- gate 1: measures the syllabus does not name ------------------------


def test_a_part_about_an_unnamed_measure_is_rejected(allowed):
    raw = payload(partb="Explain the difference between CPI and CPIH.")
    with pytest.raises(DataResponseError) as exc:
        check(raw, allowed)
    assert "CPIH" in str(exc.value)


def test_the_extract_may_still_mention_it(allowed):
    """The table shows CPIH; refusing to name it in the prose would make the
    stimulus dishonest about its own data."""
    raw = payload()
    raw["extract"] = "The CPIH is one measure. " + EXTRACT
    check(raw, allowed)


def test_two_letter_forms_are_not_treated_as_measures(allowed):
    """UK, US and EU are countries."""
    assert off_syllabus_acronyms("the UK and the US economies", allowed) == []


def test_acronyms_the_syllabus_names_are_allowed(spine, allowed):
    for term in ("CPI", "CAB"):
        assert term in allowed
    assert off_syllabus_acronyms("the CPI and the CAB", allowed) == []


def test_the_allowed_set_is_derived_from_the_spine_not_hard_coded(spine):
    """The whole point: a syllabus revision changes this with no code change."""
    assert "CPI" in syllabus_acronyms(spine)
    assert "CPIH" not in syllabus_acronyms(spine)


def test_prompt_forbids_exactly_what_the_gate_allows(allowed):
    instruction = scope_instruction(allowed)
    for term in allowed:
        assert term in instruction


def test_the_prompt_carries_the_scope_instruction(spine, allowed):
    topic = next(t for u in spine.units for t in u.topics if t.code == "4.6")
    text = build_prompt(topic, DATASET, TABLE, SHAPE, allowed_acronyms=allowed)
    assert "must not be the subject of a part" in text


# ---- gate 2: the calculate part ----------------------------------------


def test_a_calculate_part_must_ask_for_a_percentage_change(allowed):
    raw = payload()
    raw["parts"][1]["prompt"] = (
        "Calculate the difference between the CPI and CPIH rates in 2021."
    )
    with pytest.raises(DataResponseError) as exc:
        check(raw, allowed)
    assert "percentage" in str(exc.value).lower()


# ---- gate 3: the data-read part ----------------------------------------


def test_reading_one_cell_is_rejected(allowed):
    raw = payload()
    raw["parts"][0]["prompt"] = "What was the CPI annual inflation rate in 2022?"
    with pytest.raises(DataResponseError) as exc:
        check(raw, allowed)
    assert "trend" in str(exc.value).lower()


def test_the_specimens_own_wording_is_not_rejected(allowed):
    """The first version of this rule demanded a word like 'trend' and rejected
    the 2023 specimen's (b)(ii), which names no period at all. The rule states
    the failure -- one period and no comparison -- not an approved vocabulary."""
    raw = payload()
    raw["parts"][0]["prompt"] = (
        "Consider the extent to which this relationship is evident in the data "
        "in Table 1.1."
    )
    check(raw, allowed)


def test_a_comparison_satisfies_the_data_read_part(allowed):
    raw = payload()
    raw["parts"][0]["prompt"] = (
        "Using Table 1.1, compare the CPI annual rate in 2021 with 2023."
    )
    check(raw, allowed)


# ---- every gate must have a matching instruction ------------------------


def test_every_part_kind_in_use_is_explained_to_the_model():
    """A gate the prompt never mentions is a retry loop, not a guard. The
    calculate and data-read gates shipped without one and cost two rejected
    attempts on a real run before this test existed."""
    kinds = {part.kind for shape in SHAPES for part in shape.parts}
    missing = sorted(kinds - set(KIND_GUIDANCE))
    assert not missing, f"part kinds with no instruction: {missing}"


def test_the_instructions_name_what_the_gates_demand():
    assert "PERCENTAGE CHANGE" in KIND_GUIDANCE["calculate"]
    for word in ("TREND", "COMPARISON"):
        assert word in KIND_GUIDANCE["data_read"]


def test_the_schema_carries_the_instructions():
    text = schema_text(SHAPE)
    assert "PERCENTAGE CHANGE" in text
    assert "single year" in text


# ---- extract length: aim at a target, not at a boundary -----------------


def test_the_target_sits_well_inside_the_accepted_band():
    """A real run produced 87 words against a 90 minimum, twice. Asking for a
    boundary gets answers on both sides of it, so the prompt asks for a target
    and the validator keeps the band."""
    assert MIN_EXTRACT_WORDS < TARGET_EXTRACT_WORDS < MAX_EXTRACT_WORDS
    assert TARGET_EXTRACT_WORDS - MIN_EXTRACT_WORDS >= 40
    assert MAX_EXTRACT_WORDS - TARGET_EXTRACT_WORDS >= 40


def test_the_schema_asks_for_the_target(allowed):
    text = schema_text(SHAPE)
    assert str(TARGET_EXTRACT_WORDS) in text
    assert "aim for the target" in text


def test_a_short_extract_is_told_which_way_to_move(allowed):
    raw = payload()
    raw["extract"] = "The 'general rise in prices' worried policymakers. " + (
        "Prices rose. " * 10
    )
    with pytest.raises(DataResponseError) as exc:
        check(raw, allowed)
    message = str(exc.value)
    assert "add about" in message
    assert str(TARGET_EXTRACT_WORDS) in message


def test_a_long_extract_is_told_to_cut(allowed):
    raw = payload()
    raw["extract"] = "The 'general rise in prices' worried policymakers. " + (
        "Prices rose steadily across the whole of the period shown. " * 40
    )
    with pytest.raises(DataResponseError) as exc:
        check(raw, allowed)
    assert "cut about" in str(exc.value)


# ---- the gates stay optional so existing callers are unaffected --------


def test_without_an_allowed_set_the_acronym_gate_is_silent(allowed):
    raw = payload(partb="Explain the difference between CPI and CPIH.")
    validate(build(raw))  # no allowed_acronyms -> no acronym rejection
