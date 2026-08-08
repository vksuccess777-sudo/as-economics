"""The marker's job is to be hard to fool. These tests are the fooling attempts."""

from __future__ import annotations

import json

import pytest

from src.llm.provider import LLMResponse
from src.marking.diagram import DiagramDeclaration, DiagramSpec, Shift
from src.marking.essay_marker import (
    EssayMarker,
    EssayPart,
    ExtractedAnswer,
    MarkingError,
    build_judge_prompt,
    parse_json_object,
    parse_levels,
    record_essay,
)
from src.marking.levels import default_ladder
from src.store.db import Store

LADDER = default_ladder()

PART_A = EssayPart(
    question_id="q_a",
    topic_code="2.1",
    part="a",
    prompt="Explain how an increase in household income affects the market for new cars.",
    command_word="explain",
    max_marks=8,
    diagram=DiagramSpec(
        diagram_type="supply_demand",
        shifts=(Shift("demand", "right"),),
        effects={"price": "rise", "quantity": "rise"},
    ),
)

PART_B = EssayPart(
    question_id="q_b",
    topic_code="2.1",
    part="b",
    prompt="Discuss whether a rise in income is always the main determinant of car sales.",
    command_word="discuss",
    max_marks=12,
)

GOOD_DECLARATION = DiagramDeclaration(
    diagram_type="supply_demand",
    shifts=(Shift("demand", "right"),),
    effects={"price": "rise", "quantity": "rise"},
)

EXTRACTION = {
    "definitions": [{"term": "normal good", "correct": True, "note": ""}],
    "chains": [
        {
            "claim": "higher income raises demand",
            "steps": ["income up", "demand for a normal good up", "price and quantity up"],
            "complete": True,
            "break_point": "",
        }
    ],
    "judgements": [],
    "problems": [],
}


class ScriptedProvider:
    """Returns a queued response per call, and remembers every prompt it saw."""

    name = "fake"

    def __init__(self, *responses):
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        payload = self.responses.pop(0)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return LLMResponse(text=text, provider=self.name, model="fake")


def levels_payload(**levels):
    payload = {ao: {"level": lvl, "why": "because"} for ao, lvl in levels.items()}
    payload["next_steps"] = ["state the direction of the shift explicitly"]
    return payload


# --------------------------------------------------------------- marks


def test_marks_are_computed_from_levels_not_taken_from_the_model():
    provider = ScriptedProvider(EXTRACTION, levels_payload(AO1=3, AO2=3, AO3=2))
    marked = EssayMarker(provider, LADDER).mark(PART_A, "an answer", GOOD_DECLARATION)
    assert marked.levels == {"AO1": 3, "AO2": 3, "AO3": 2}
    assert marked.awarded == 8
    assert marked.marks_by_ao == {"AO1": 3, "AO2": 3, "AO3": 2}


def test_a_mark_supplied_by_the_model_is_ignored():
    """Even if the model volunteers 'marks': 8, the ladder decides."""
    payload = levels_payload(AO1=1, AO2=1, AO3=1)
    payload["marks"] = 8
    payload["total"] = 8
    provider = ScriptedProvider(EXTRACTION, payload)
    marked = EssayMarker(provider, LADDER).mark(PART_A, "an answer", GOOD_DECLARATION)
    assert marked.awarded == 3


def test_blank_answer_scores_zero_without_calling_the_model():
    provider = ScriptedProvider()  # no responses queued: a call would raise
    marked = EssayMarker(provider, LADDER).mark(PART_A, "   ", None)
    assert marked.awarded == 0
    assert provider.prompts == []


# ------------------------------------------------------------ two-pass


def test_judging_pass_never_sees_the_prose():
    """The whole point of two passes. If this fails, fluency buys marks again."""
    answer = "UNIQUE_STUDENT_PROSE_MARKER an eloquent but empty paragraph"
    provider = ScriptedProvider(EXTRACTION, levels_payload(AO1=2, AO2=2, AO3=1))
    EssayMarker(provider, LADDER).mark(PART_A, answer, GOOD_DECLARATION)
    extract_prompt, judge_prompt = provider.prompts
    assert "UNIQUE_STUDENT_PROSE_MARKER" in extract_prompt
    assert "UNIQUE_STUDENT_PROSE_MARKER" not in judge_prompt


def test_judge_prompt_omits_unassessed_objectives():
    """The 12-mark part scores AO1+AO2 together under AO1 (Cambridge's Table
    A); AO2 is unused for this part size and must be omitted from the prompt."""
    extracted = ExtractedAnswer.from_dict(EXTRACTION, word_count=100)
    from src.marking.diagram import check_diagram

    prompt = build_judge_prompt(
        LADDER.part(12), PART_B, extracted,
        check_diagram(PART_B.diagram, None),
    )
    assert "does not assess AO2" in prompt
    assert '"AO2"' not in prompt


def test_absence_of_judgements_is_visible_to_the_judge():
    extracted = ExtractedAnswer.from_dict(EXTRACTION, word_count=100)
    rendered = extracted.render()
    assert "JUDGEMENTS OFFERED:" in rendered
    assert "(none)" in rendered


# ------------------------------------------------------------- diagram


def test_missing_diagram_caps_ao2_even_when_the_model_is_generous():
    provider = ScriptedProvider(EXTRACTION, levels_payload(AO1=3, AO2=3, AO3=2))
    marked = EssayMarker(provider, LADDER).mark(PART_A, "an answer", None)
    assert marked.levels["AO2"] == 1
    assert marked.levels["AO1"] == 3
    assert marked.awarded == 3 + 1 + 2
    assert "capped" in (marked.cap_note or "")


def test_correct_diagram_leaves_levels_untouched():
    provider = ScriptedProvider(EXTRACTION, levels_payload(AO1=3, AO2=3, AO3=2))
    marked = EssayMarker(provider, LADDER).mark(PART_A, "an answer", GOOD_DECLARATION)
    assert marked.cap_note is None


def test_part_b_needs_no_diagram():
    """12-mark part: AO1 carries Cambridge's combined AO1+AO2 band (Table A,
    max 8); AO2 is unused for this part size; AO3 is Table B (max 4)."""
    provider = ScriptedProvider(EXTRACTION, levels_payload(AO1=3, AO3=2))
    marked = EssayMarker(provider, LADDER).mark(PART_B, "an answer", None)
    assert marked.cap_note is None
    assert marked.awarded == 8 + 4


# ----------------------------------------------------------- integrity


def test_level_off_the_ladder_raises_rather_than_clamping():
    """Clamping would hide a broken judging prompt behind a plausible mark."""
    provider = ScriptedProvider(EXTRACTION, levels_payload(AO1=7, AO2=1))
    with pytest.raises(MarkingError, match="off the ladder"):
        EssayMarker(provider, LADDER).mark(PART_A, "an answer", GOOD_DECLARATION)


def test_missing_ao_raises():
    provider = ScriptedProvider(EXTRACTION, levels_payload(AO1=2))
    with pytest.raises(MarkingError, match="no level for AO2"):
        EssayMarker(provider, LADDER).mark(PART_A, "an answer", GOOD_DECLARATION)


def test_non_json_judging_response_raises():
    provider = ScriptedProvider(EXTRACTION, "I would give this about 6 out of 8.")
    with pytest.raises(MarkingError, match="no JSON object"):
        EssayMarker(provider, LADDER).mark(PART_A, "an answer", GOOD_DECLARATION)


def test_fenced_json_is_recovered():
    fenced = "```json\n" + json.dumps(levels_payload(AO1=2, AO2=2, AO3=1)) + "\n```"
    provider = ScriptedProvider(EXTRACTION, fenced)
    marked = EssayMarker(provider, LADDER).mark(PART_A, "an answer", GOOD_DECLARATION)
    assert marked.awarded == 5


def test_extraction_does_not_invent_completeness():
    """An incomplete chain reported as incomplete must stay incomplete."""
    extracted = ExtractedAnswer.from_dict(
        {"chains": [{"claim": "x", "steps": ["a"], "complete": False}]}
    )
    assert extracted.complete_chains == 0
    assert "[incomplete]" in extracted.render()


def test_calibrated_ladder_is_flagged_on_every_result():
    """The shipped ladder is now built from the Cambridge specimen mark
    scheme (see data/levels/paper2_levels.json), so this should read True."""
    provider = ScriptedProvider(EXTRACTION, levels_payload(AO1=2, AO2=2, AO3=1))
    marked = EssayMarker(provider, LADDER).mark(PART_A, "an answer", GOOD_DECLARATION)
    assert marked.calibrated is True
    assert json.loads(marked.feedback_json())["calibrated"] is True


def test_uncalibrated_ladder_is_flagged_on_every_result():
    """The flagging mechanism itself, independent of which ladder ships."""
    from src.marking.levels import Ladder

    interim = Ladder(provenance="interim", source="", parts=LADDER.parts)
    provider = ScriptedProvider(EXTRACTION, levels_payload(AO1=2, AO2=2, AO3=1))
    marked = EssayMarker(provider, interim).mark(PART_A, "an answer", GOOD_DECLARATION)
    assert marked.calibrated is False
    assert json.loads(marked.feedback_json())["calibrated"] is False


def test_parse_levels_rejects_a_string_level():
    with pytest.raises(MarkingError, match="not an integer"):
        parse_levels({"AO1": {"level": "high"}, "AO2": {"level": 1}}, LADDER.part(8))


def test_parse_json_object_rejects_an_array():
    with pytest.raises(MarkingError):
        parse_json_object("[1, 2, 3]")


# -------------------------------------------------------------- store


def test_marked_essay_lands_in_the_attempt_log(tmp_path):
    store = Store(tmp_path / "t.sqlite3")
    store.initialise()
    qid = store.add_question(
        paper_key="paper_2",
        section_key="B",
        topic_code="2.1",
        max_marks=8,
        body=json.dumps({"prompt": PART_A.prompt}),
        origin="generated",
        syllabus_code="9708",
        syllabus_version="2026-2028",
        command_word="explain",
        rubric=json.dumps({"group_id": "e_1", "part": "a", "diagram": None}),
    )
    part = EssayPart.from_row(store.fetch_questions([qid])[0])
    provider = ScriptedProvider(EXTRACTION, levels_payload(AO1=3, AO2=2, AO3=1))
    marked = EssayMarker(provider, LADDER).mark(part, "an answer", None)

    attempt = store.start_attempt(mode="single_question", paper_key="paper_2")
    record_essay(store, attempt_id=attempt, ordinal=1, marked=marked,
                 answer_text="an answer")

    perf = store.topic_performance()
    assert perf[0]["topic_code"] == "2.1"
    assert perf[0]["marks_awarded"] == marked.awarded

    ao = {r["ao"]: r for r in store.ao_performance()}
    assert ao["AO1"]["answered"] == 1
    # Cambridge point-marks the 8-mark part (a) AO1 3 / AO2 3 / AO3 2, so an
    # 8-mark part DOES carry (a small amount of) evaluation credit.
    assert ao["AO3"]["answered"] == 1

    cw = store.command_word_performance()
    assert cw[0]["command_word"] == "explain"
