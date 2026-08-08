"""What the solver sends, what it accepts back, and what it refuses to do.

The assertions worth reading are the ones about what does NOT happen: an essay
item never comes back as a finished essay, an MCQ key that is not one of the
printed options is rejected rather than shown, and no mark is ever awarded.
"""

from __future__ import annotations

import json

import pytest

from src.llm.provider import LLMResponse
from src.syllabus.parser import parse_text
from src.worksheet.classify import classify_all
from src.worksheet.models import ESSAY, MCQ, SHORT, Item
from src.worksheet.segment import segment
from src.worksheet.solve import (
    SolveError,
    build_prompt,
    check_mcq,
    parse_response,
    solve_item,
    validate,
)

from tests.fixtures import SYLLABUS_EXCERPT


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT)


class ScriptedProvider:
    """Returns each queued reply in turn and records every prompt."""

    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []
        self.systems = []
        self.temperatures = []

    def generate(self, prompt, *, system=None, max_tokens=1500, temperature=0.2):
        self.prompts.append(prompt)
        self.systems.append(system)
        self.temperatures.append(temperature)
        reply = self.replies.pop(0) if self.replies else "{}"
        if not isinstance(reply, str):
            reply = json.dumps(reply)
        return LLMResponse(text=reply, provider="scripted", model="scripted")


def short_item(**overrides) -> Item:
    base = dict(
        label="1(a)",
        text="Air pollution from a coal-fired power station.",
        number="1",
        part="a",
        marks=2,
        kind=SHORT,
        command_word="identify",
        context=(
            "Identify, in each case, a government policy measure that could be "
            "used to correct the following examples of market failure."
        ),
    )
    base.update(overrides)
    return Item(**base)


def mcq_item() -> Item:
    return Item(
        label="4",
        text="Which of the following shifts the supply curve of wheat right?",
        number="4",
        kind=MCQ,
        options={
            "A": "An increase in the price of wheat",
            "B": "A fall in the wage rate of farm workers",
            "C": "An increase in the demand for bread",
            "D": "A tax on wheat producers",
        },
    )


def essay_item() -> Item:
    return Item(
        label="5",
        text="Discuss whether a maximum price is the best way to make housing affordable.",
        number="5",
        marks=12,
        kind=ESSAY,
        command_word="discuss",
    )


GOOD_SHORT = {
    "answer": "A tax on the power station's emissions.",
    "working": ["A specific indirect tax raises private cost towards social cost."],
    "marks_guidance": "1 for naming the measure, 1 for linking it to the externality.",
    "common_error": "Naming a subsidy, which worsens over-production.",
}

GOOD_ESSAY = {
    "answer": "Whether a price ceiling is the best instrument, not just whether it works.",
    "working": ["Explain a maximum price below equilibrium.", "Show the shortage."],
    "evaluation": ["Depends on elasticity of supply.", "Compare with housing subsidies."],
    "diagram": "Demand and supply of rented housing, ceiling below equilibrium.",
    "marks_guidance": "Top band reaches a supported judgement.",
    "common_error": "Describing the policy without judging it.",
}


# ---------------------------------------------------------------- prompts


def test_the_shared_instruction_travels_with_the_part(spine):
    prompt = build_prompt(short_item(), spine=spine, syllabus_lines=[])
    assert "Identify, in each case" in prompt
    assert "Air pollution" in prompt


def test_the_printed_tariff_shapes_the_answer(spine):
    prompt = build_prompt(short_item(marks=2), spine=spine, syllabus_lines=[])
    assert "[2]" in prompt


def test_no_printed_tariff_means_no_invented_one(spine):
    prompt = build_prompt(short_item(marks=None), spine=spine, syllabus_lines=[])
    assert "do not award" in prompt.lower()


def test_the_command_word_definition_is_quoted_from_the_spine(spine):
    item = short_item(command_word="define", text="Define the term 'merit good'.")
    prompt = build_prompt(item, spine=spine, syllabus_lines=[])
    assert "give precise meaning" in prompt


def test_syllabus_lines_are_put_in_front_of_the_model(spine):
    prompt = build_prompt(
        short_item(),
        spine=spine,
        syllabus_lines=["Methods and effects of government intervention in markets"],
    )
    assert "government intervention" in prompt


def test_not_required_terms_are_named_as_off_limits(spine):
    prompt = build_prompt(
        short_item(), spine=spine, syllabus_lines=[], excluded=["multiplier"]
    )
    assert "multiplier" in prompt
    assert "NOT REQUIRED" in prompt


def test_stimulus_reaches_every_item_on_a_data_response_sheet(spine):
    prompt = build_prompt(
        short_item(), spine=spine, syllabus_lines=[],
        stimulus="Extract A: sugar prices rose 11% in 2024.",
    )
    assert "sugar prices rose 11%" in prompt


def test_an_essay_item_is_told_not_to_write_the_essay(spine):
    prompt = build_prompt(essay_item(), spine=spine, syllabus_lines=[])
    assert "Do NOT write the essay" in prompt


def test_the_system_prompt_forbids_inventing_a_mark_scheme(spine):
    provider = ScriptedProvider([GOOD_SHORT])
    solve_item(short_item(), provider=provider, spine=spine)
    assert "never invent" in provider.systems[0].lower()


# ------------------------------------------------------------- validating


def test_json_wrapped_in_a_code_fence_is_still_read():
    payload = parse_response("```json\n{\"answer\": \"yes\"}\n```")
    assert payload["answer"] == "yes"


def test_prose_around_the_object_is_tolerated():
    payload = parse_response("Here you go:\n{\"answer\": \"yes\"}\nHope that helps")
    assert payload["answer"] == "yes"


def test_a_reply_with_no_json_is_an_error():
    with pytest.raises(SolveError):
        parse_response("I am not going to answer that.")


def test_an_mcq_key_outside_the_printed_options_is_rejected():
    """A key of 'E' on a four-option question is a hallucination, not an answer."""
    item = mcq_item()
    with pytest.raises(SolveError, match="not one of the printed options"):
        validate({"answer": "E is right", "mcq_key": "E"}, item)


def test_an_essay_plan_made_of_paragraphs_is_rejected():
    payload = dict(GOOD_ESSAY, working=["x" * 700])
    with pytest.raises(SolveError, match="prose paragraphs"):
        validate(payload, essay_item())


def test_a_missing_answer_is_rejected():
    with pytest.raises(SolveError, match="answer"):
        validate({"working": ["something"]}, short_item())


# ---------------------------------------------------------------- solving


def test_a_short_item_is_solved_in_one_call(spine):
    provider = ScriptedProvider([GOOD_SHORT])
    solution = solve_item(short_item(), provider=provider, spine=spine)
    assert solution.answer.startswith("A tax")
    assert solution.attempts == 1
    assert solution.provenance == "derived"


def test_a_rejected_reply_is_retried_once_with_the_reason_fed_back(spine):
    bad = {"answer": "B is right", "mcq_key": "E"}
    good = {"answer": "B — a fall in costs raises supply", "mcq_key": "B",
            "option_notes": {"B": "lower costs shift supply right"}}
    provider = ScriptedProvider([bad, good])
    solution = solve_item(mcq_item(), provider=provider, spine=spine)

    assert solution.mcq_key == "B"
    assert solution.attempts == 2
    assert "previous attempt was rejected" in provider.prompts[1]
    # Repeating the temperature reproduces the answer that was just rejected.
    assert provider.temperatures[1] > provider.temperatures[0]


def test_two_bad_replies_give_up_loudly_rather_than_showing_junk(spine):
    provider = ScriptedProvider(["not json", "still not json"])
    with pytest.raises(SolveError):
        solve_item(short_item(), provider=provider, spine=spine)


def test_an_essay_solution_is_marked_as_a_plan(spine):
    provider = ScriptedProvider([GOOD_ESSAY])
    solution = solve_item(essay_item(), provider=provider, spine=spine)
    assert solution.is_plan
    assert solution.evaluation


def test_nothing_in_a_solution_awards_a_mark(spine):
    provider = ScriptedProvider([GOOD_SHORT])
    solution = solve_item(short_item(), provider=provider, spine=spine)
    assert not hasattr(solution, "awarded")
    assert not hasattr(solution, "marks")


# ------------------------------------------------------- syllabus grounding


class StubHit:
    def __init__(self, ref, source="syllabus", text="", topic_code="3.2",
                 topic_title="Methods and effects of government intervention",
                 unit_code="3", unit_title="Government microeconomic intervention"):
        self.ref = ref
        self.source = source
        self.text = text
        self.topic_code = topic_code
        self.topic_title = topic_title
        self.unit_code = unit_code
        self.unit_title = unit_title
        self.outcome = None
        self.score = 1.0


class StubRetriever:
    def __init__(self, hits):
        self.hits = hits

    def search(self, query, k=6):
        return self.hits


def test_syllabus_references_are_computed_not_taken_from_the_model(spine):
    """The model invents plausible outcome codes; the retriever does not."""
    provider = ScriptedProvider([dict(GOOD_SHORT, syllabus_refs=["9.9.9"])])
    retriever = StubRetriever([StubHit("3.2.1", text="impact and incidence of taxes")])
    solution = solve_item(
        short_item(), provider=provider, spine=spine, retriever=retriever
    )
    assert solution.syllabus_refs == ["3.2.1"]
    assert "9.9.9" not in solution.syllabus_refs
    assert solution.topic_code == "3.2"


def test_a_question_matching_nothing_on_the_syllabus_is_flagged_not_refused(spine):
    """A worksheet came from a teacher — help with it and say what you noticed."""
    provider = ScriptedProvider([GOOD_SHORT])
    solution = solve_item(
        short_item(), provider=provider, spine=spine, retriever=StubRetriever([])
    )
    assert solution.answer, "an off-syllabus item must still be solved"
    assert "A Level" in solution.scope_note


def test_chapter_only_matches_do_not_count_as_a_topic(spine):
    provider = ScriptedProvider([GOOD_SHORT])
    retriever = StubRetriever([StubHit("3", source="chapter", text="Government")])
    solution = solve_item(
        short_item(), provider=provider, spine=spine, retriever=retriever
    )
    assert solution.scope_note


# ------------------------------------------------------------ mcq checking


def test_the_mcq_comparison_is_a_comparison_not_a_mark(spine):
    provider = ScriptedProvider([{"answer": "B", "mcq_key": "B"}])
    item = mcq_item()
    solution = solve_item(item, provider=provider, spine=spine)

    assert check_mcq(item, solution, "B") is True
    assert check_mcq(item, solution, "d") is False
    assert check_mcq(item, solution, "") is None


def test_end_to_end_from_worksheet_text_to_solutions(spine):
    text = (
        "1. Identify, in each case, a policy measure that could correct the "
        "following examples of market failure.\n"
        "(a) Air pollution from a power station. [2]\n"
        "(b) Under-consumption of vaccinations. [2]\n"
    )
    sheet = segment(text)
    classify_all(sheet.items, spine)
    provider = ScriptedProvider([GOOD_SHORT, GOOD_SHORT])

    solutions = [
        solve_item(item, provider=provider, spine=spine, stimulus=sheet.preamble)
        for item in sheet.items
    ]
    assert len(solutions) == 2
    assert all(s.answer for s in solutions)
    # Each part was solved on its own terms, not folded into one call.
    assert "Air pollution" in provider.prompts[0]
    assert "vaccinations" in provider.prompts[1]
