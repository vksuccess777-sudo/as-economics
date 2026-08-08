"""The Concept Tutor teaches Section A from the same facts the generator uses.

The load-bearing test here is the drift one: what a student is TAUGHT a part
demands has to be the same string the validator REJECTS on and the generator
is INSTRUCTED with. If those three ever disagree, a student is being coached
to write answers to questions the app does not build.
"""

from __future__ import annotations

import pytest

from src.marking.points_marker import PointsPart
from src.questions.data_response import (
    ASSESS_CAPS,
    KIND_GUIDANCE,
    SHAPES,
    SPECIMEN_2023,
)
from src.syllabus import assessment
from src.tutor.data_response_tutor import (
    KIND_STEPS,
    cap_consequence,
    guidance_for,
    is_data_response_question,
    minutes_for,
    reading_the_stimulus,
    section_a_facts,
)

from src.syllabus.parser import parse_text
from tests.fixtures import SYLLABUS_EXCERPT


@pytest.fixture(scope="module")
def parsed_spine():
    return parse_text(SYLLABUS_EXCERPT, level="AS")


# -------------------------------------------------------------- no drift


def test_every_part_kind_the_shapes_use_is_taught():
    """A kind the generator can emit that the tutor cannot coach is a gap."""
    used = {part.kind for shape in SHAPES for part in shape.parts}
    missing = used - set(KIND_STEPS)
    assert not missing, f"no coaching steps for part kinds: {sorted(missing)}"


def test_what_the_student_is_taught_is_the_validators_own_wording():
    facts = section_a_facts()
    for kind, demand in KIND_GUIDANCE.items():
        assert demand in facts, f"{kind} guidance is not in what the tutor teaches"


def test_guidance_for_a_part_carries_the_validators_demand():
    part = PointsPart(
        question_id="q1", label="(a)(ii)", prompt="Calculate the change.",
        max_marks=1, points=({"text": "x", "band": "knowledge"},), kind="calculate",
    )
    guide = guidance_for(part)
    assert guide.demand == KIND_GUIDANCE["calculate"]
    assert "percentage change" in guide.demand.lower()


def test_the_percentage_points_trap_is_taught_not_just_enforced():
    steps = " ".join(KIND_STEPS["calculate"]).lower()
    assert "percentage points" in steps
    assert "÷" in " ".join(KIND_STEPS["calculate"]) or "/" in " ".join(KIND_STEPS["calculate"])


# ------------------------------------------------------------- the facts


def test_facts_state_the_real_paper_numbers():
    facts = section_a_facts()
    assert f"{assessment.PAPER_2.marks} marks" in facts
    assert f"{assessment.PAPER_2.minutes} minutes" in facts
    assert "20 marks" in facts


def test_facts_name_both_observed_shapes_and_their_sources():
    facts = section_a_facts()
    for shape in SHAPES:
        assert shape.name in facts
        assert shape.source in facts


def test_facts_carry_the_caps_from_the_marker_not_from_prose():
    facts = section_a_facts()
    assert f"{ASSESS_CAPS['analysis']} marks for explanation and analysis" in facts


def test_cap_consequence_states_the_ceiling_an_unevaluated_answer_hits():
    note = cap_consequence(ASSESS_CAPS, 6)
    assert "stops at 4 out of 6" in note


def test_facts_include_cambridge_command_words_when_a_spine_is_given(parsed_spine):
    facts = section_a_facts(parsed_spine)
    if not parsed_spine.command_words:
        pytest.skip("fixture spine has no command words")
    assert "command word meanings" in facts.lower()


def test_time_budget_is_arithmetic_on_the_paper():
    # 120 minutes for 60 marks = 2 minutes a mark.
    assert minutes_for(6) == 12
    assert minutes_for(20) == 40


# ------------------------------------------------------------- routing


@pytest.mark.parametrize(
    "question",
    [
        "how do I answer a data response?",
        "What is Section A?",
        "explain the data-response question",
        "how is the stimulus used in paper 2",
        "tips for paper 2 section a",
    ],
)
def test_data_response_questions_are_recognised(question):
    assert is_data_response_question(question)


@pytest.mark.parametrize(
    "question",
    [
        "explain price elasticity of demand",
        "what does the demand schedule table show",
        "why does the AD curve slope downwards",
        "how do I extract more marks from an essay",
        "what is a supply and demand diagram",
    ],
)
def test_ordinary_economics_questions_do_not_route_to_section_a(question):
    assert not is_data_response_question(question)


def test_paper_2_alone_is_not_enough_to_route_there():
    """Section B and C are also Paper 2 — the stimulus has to be named."""
    assert not is_data_response_question("how long is paper 2")
    assert is_data_response_question("how do I read the table in paper 2")


# ---------------------------------------------------------- per-part coaching


def _assess_part() -> PointsPart:
    return PointsPart(
        question_id="q9",
        label="(d)",
        prompt="Assess the impact of higher inflation on consumers.",
        max_marks=6,
        points=tuple({"text": f"point {i}", "band": "analysis"} for i in range(7)),
        caps=dict(ASSESS_CAPS),
        kind="assess",
        command_word="assess",
    )


def test_assess_guidance_reports_the_cap_and_its_consequence():
    guide = guidance_for(_assess_part())
    assert guide.kind == "assess"
    assert guide.minutes == 12
    assert "stops at 4 out of 6" in guide.cap_note


def test_guidance_counts_the_creditable_points_of_this_question():
    guide = guidance_for(_assess_part())
    assert guide.points_creditable == 7
    assert "7 creditable points" in " ".join(guide.notes)


def test_guidance_falls_back_to_the_prompts_first_word_for_the_command_word():
    part = PointsPart(
        question_id="q2", label="(a)", prompt="Describe the trend shown.",
        max_marks=2, points=(), kind="data_read",
    )
    assert guidance_for(part).command_word == "describe"


def test_guidance_uses_cambridges_own_command_word_meaning(parsed_spine):
    if "describe" not in {w.lower() for w in parsed_spine.command_words}:
        pytest.skip("fixture spine has no 'describe'")
    part = PointsPart(
        question_id="q2", label="(a)", prompt="Describe the trend shown.",
        max_marks=2, points=(), kind="data_read",
    )
    assert guidance_for(part, parsed_spine).command_meaning


def test_kind_is_inferred_from_caps_when_the_rubric_did_not_record_one():
    """Older banked questions predate the `kind` round-trip."""
    part = PointsPart(
        question_id="q3", label="(e)", prompt="Consider whether…",
        max_marks=6, points=(), caps=dict(ASSESS_CAPS),
    )
    assert guidance_for(part).kind == "assess"


def test_headline_names_marks_and_minutes():
    assert guidance_for(_assess_part()).headline() == "(d) · 6 marks · about 12 min"


# ----------------------------------------------------------- the stimulus


def test_reading_advice_reflects_the_table_actually_in_front_of_the_student():
    two_series = reading_the_stimulus(
        {
            "extract": "Prices rose 'sharply' last year.",
            "table_headers": ["Year", "Inflation", "Unemployment"],
            "table_rows": [["2020", "1.0", "4.0"], ["2021", "2.5", "4.5"]],
        }
    )
    joined = " ".join(two_series)
    assert "2 rows" in joined
    assert "relationship between them" in joined
    assert "quotation marks" in joined

    one_series = " ".join(
        reading_the_stimulus(
            {"table_headers": ["Year", "Inflation"], "table_rows": [["2020", "1.0"]]}
        )
    )
    assert "single series" in one_series
    assert "relationship between them" not in one_series


def test_reading_advice_survives_an_empty_stimulus():
    assert reading_the_stimulus({})


# -------------------------------------------------------- part round-trip


def test_points_part_reads_kind_back_off_a_banked_row():
    import json

    row = {
        "id": "q_x",
        "topic_code": "4.6",
        "max_marks": 6,
        "command_word": "assess",
        "body": json.dumps({"prompt": "Assess…"}),
        "rubric": json.dumps(
            {"part": "(d)", "kind": "assess", "caps": ASSESS_CAPS, "points": []}
        ),
    }
    part = PointsPart.from_row(row)
    assert part.kind == "assess"
    assert part.command_word == "assess"
    assert part.label == "(d)"


def test_points_part_still_reads_a_row_without_a_command_word_column():
    import json

    row = {
        "id": "q_y",
        "topic_code": "4.6",
        "max_marks": 2,
        "body": json.dumps({"prompt": "Describe…"}),
        "rubric": json.dumps({"part": "(a)", "kind": "data_read", "points": []}),
    }
    part = PointsPart.from_row(row)
    assert part.command_word == ""
    assert part.kind == "data_read"


def test_specimen_shape_still_totals_twenty():
    assert SPECIMEN_2023.total() == 20


# --------------------------------------------------- routing in the tutor


class _FakeProvider:
    name = "fake"

    def __init__(self):
        self.prompts: list[str] = []
        self.systems: list[str] = []

    def generate(self, prompt, *, system=None, **kwargs):
        from src.llm.provider import LLMResponse

        self.prompts.append(prompt)
        self.systems.append(system)
        return LLMResponse(text="Section A works like this.", provider="fake", model="fake")


def _tutor(spine):
    from src.tutor.explainer import ConceptTutor

    provider = _FakeProvider()
    return ConceptTutor(provider, spine), provider


def test_a_section_a_question_is_answered_from_the_observed_shapes(parsed_spine):
    tutor, provider = _tutor(parsed_spine)
    result = tutor.explain("How do I answer the data response?")
    assert result.kind == "data_response"
    assert result.in_scope
    prompt = provider.prompts[0]
    for shape in SHAPES:
        assert shape.source in prompt
    assert "60 marks" in prompt


def test_the_section_a_route_beats_the_general_exam_route(parsed_spine):
    """'How are marks split in Section A' satisfies both; the specific one wins."""
    tutor, provider = _tutor(parsed_spine)
    result = tutor.explain("How are the marks split in Section A of paper 2?")
    assert result.kind == "data_response"
    assert "up to 4 marks for explanation and analysis" in provider.prompts[0].lower()


def test_a_concept_question_still_goes_through_retrieval(parsed_spine):
    tutor, _ = _tutor(parsed_spine)
    result = tutor.explain("Explain price elasticity of demand.")
    assert result.kind in {"concept", "refusal"}


def test_the_section_a_route_is_told_not_to_invent_mark_allocations(parsed_spine):
    tutor, provider = _tutor(parsed_spine)
    tutor.explain("What is Section A?")
    assert "Do not invent mark allocations" in provider.systems[0]


# ------------------------------------------- coached practice is not an attempt


def test_walking_through_a_question_is_recorded_as_seen_never_as_a_response(tmp_path):
    from src.store.db import Store

    store = Store(tmp_path / "t.sqlite3")
    store.initialise()
    before = store.counts()

    store.mark_group_seen("dr_abc")
    store.mark_group_seen("dr_abc")          # idempotent
    store.mark_group_seen("dr_def", surface="concept_tutor")

    assert store.seen_group_ids() == {"dr_abc", "dr_def"}
    assert store.seen_group_ids(surface="somewhere_else") == set()
    # The point of the whole design: nothing landed in the attempt log.
    assert store.counts()["response"] == before["response"] == 0
    assert store.counts()["attempt"] == before["attempt"] == 0


def test_an_existing_database_self_upgrades_to_hold_seen_questions(tmp_path):
    """The `note`/`observed_mistake` pattern: a new table makes is_initialised
    false, the app re-runs schema.sql, and every statement is CREATE IF NOT
    EXISTS so nothing already there is touched."""
    import sqlite3

    from src.store.db import Store

    path = tmp_path / "old.sqlite3"
    store = Store(path)
    store.initialise()
    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE practice_seen")
    assert not store.is_initialised()
    store.initialise()
    assert store.is_initialised()
    store.mark_group_seen("dr_x")
    assert store.seen_group_ids() == {"dr_x"}
