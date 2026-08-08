"""Tests for the fourth round of Concept Tutor fixes.

All three come from real transcripts, and one of them is a regression I
introduced: approximate matching, added in v3 to rescue misspelt economics
terms, was also being applied to ordinary English and rewrote a student's
question into nonsense.
"""

from __future__ import annotations

import pytest

from src.llm.provider import LLMResponse
from src.syllabus.parser import parse_text
from src.tutor.explainer import ConceptTutor
from src.tutor.retriever import SpineRetriever, tokenise
from tests.fixtures import SYLLABUS_EXCERPT


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT, level="AS")


@pytest.fixture(scope="module")
def retriever(spine):
    return SpineRetriever(spine)


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.prompts = []
        self.systems = []

    def generate(self, prompt, *, system=None, **kwargs):
        self.prompts.append(prompt)
        self.systems.append(system)
        return LLMResponse(text="An explanation.", provider=self.name, model="fake")


# ------------------------------------------- ordinary words stay ordinary


def test_ordinary_words_are_never_resolved_to_syllabus_terms(retriever):
    """From a real transcript: "for exam preparation ... how marks are
    distributed" was read as "example / prepared / knowledge / market"."""
    question = "for exam preparation i would like to know how marks are distributed"
    _, resolved, _ = retriever.resolve_query(question)
    assert resolved == {}


def test_ordinary_words_survive_into_the_search_tokens(retriever):
    tokens, _, _ = retriever.resolve_query("how do i know this")
    assert "know" in tokens


def test_a_misspelt_economics_term_still_resolves(retriever):
    """The fix must not switch approximate matching off wholesale."""
    _, resolved, _ = retriever.resolve_query("explain oportunity cost")
    assert resolved.get("oportunity") == "opportunity"


# ------------------------------------------------------- partial answers


def test_one_unknown_word_beside_a_specific_anchor_is_answered_around(spine):
    """"how do i differentiate gdp and gnp" — GDP is syllabus content, GNP is
    not, and refusing the whole question teaches nothing."""
    retriever = SpineRetriever(spine)
    report = retriever.scope_report("what is scarcity and blorptax")
    assert report.reason == "partial"
    assert report.unknown_terms == ["blorptax"]


def test_the_partial_prompt_forbids_teaching_the_unknown_term(spine):
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine)
    result = tutor.explain("what is scarcity and blorptax")
    assert result.in_scope
    assert result.unsupported_terms == ["blorptax"]
    assert "do not explain it" in provider.prompts[0]


def test_a_question_that_is_only_an_unknown_term_is_still_refused(spine):
    """The guard this must not dissolve: the subject itself being missing."""
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine)
    result = tutor.explain("explain indifference curves")
    assert result.is_refusal
    assert provider.prompts == []


def test_two_unknown_terms_are_refused(retriever):
    report = retriever.scope_report("who is the president of india")
    assert report.reason == "unknown_terms"


def test_a_compound_term_is_one_subject_not_two(retriever):
    """"indifference curves" — the unknown word sits directly against the
    known one, so the term being asked about is the compound."""
    assert retriever.blocked_span("explain indifference curves", "indifference") == [
        "indifference",
        "curve",
    ]


def test_a_coordinator_separates_two_subjects(retriever):
    """"gdp and gnp" — two things, one of which the syllabus covers."""
    assert retriever.blocked_span("differentiate gdp and gnp", "gnp") == ["gnp"]


def test_the_partial_rule_needs_no_tuned_constant(spine):
    """It reads sentence structure, not corpus statistics. An idf cut-off
    tuned on 308 documents means something else on 40, and the fixture spine
    here IS the 40-document case."""
    small = SpineRetriever(spine)
    assert small.scope_report("explain indifference curves").reason == "unknown_terms"
    assert small.scope_report("what is scarcity and blorptax").reason == "partial"


# ------------------------------------------------------- exam routing


def test_a_marks_and_chapters_question_routes_to_exam_technique(spine):
    tutor = ConceptTutor(FakeProvider(), spine)
    for question in [
        "for exam preparation i would like to know how marks are distributed "
        "between chapters",
        "which chapters carry the most marks",
        "how long is paper 2",
    ]:
        assert tutor.is_exam_question(question), question


def test_the_exam_context_maps_chapters_to_paper_2_sections(spine):
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine)
    tutor.explain("which chapters carry the most marks")
    prompt = provider.prompts[0]
    assert "Section B" in prompt and "Section C" in prompt
    assert "learning outcomes" in prompt


def test_the_exam_context_refuses_to_invent_a_mark_distribution(spine):
    """The most damaging possible answer here is a plausible invented table —
    a student would revise to it."""
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine)
    tutor.explain("how are marks split between chapters")
    prompt = provider.prompts[0]
    assert "does not publish a mark distribution" in prompt
    assert "must not be presented as mark weightings" in prompt
