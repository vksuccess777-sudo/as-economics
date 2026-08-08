"""Tests for the second version of the Concept Tutor.

The bug these exist to prevent: the free-text box refused almost every question
a student would actually type, while the starter buttons — which quote the
syllabus verbatim — always worked. Every test below is phrased the way a
fifteen-year-old types, not the way Cambridge writes.
"""

from __future__ import annotations

import json

import pytest

from src.llm.provider import LLMResponse
from src.syllabus.parser import parse_text
from src.tutor.explainer import ConceptTutor
from src.tutor.retriever import (
    GENERAL_WORDS,
    SpineRetriever,
    note_documents,
    tokenise,
)
from tests.fixtures import SYLLABUS_EXCERPT


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT, level="AS")


@pytest.fixture(scope="module")
def note_docs(spine):
    """A note in the same shape build_notes.py writes."""
    body = json.dumps(
        {
            "definitions": [
                {
                    "term": "Merit good",
                    "meaning": "A good that is under-consumed because "
                    "consumers have imperfect information about its benefits",
                }
            ],
            "core_ideas": [
                "Under-consumption of merit goods is a form of market failure "
                "which a government can address by subsidising provision"
            ],
            "common_mistakes": [
                "Confusing merit goods with public goods"
            ],
        }
    )
    return note_documents(body, topic_code="1.6", topic_title="Classification of goods and services")


@pytest.fixture(scope="module")
def retriever(spine, note_docs):
    return SpineRetriever(spine, note_docs)


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.prompts = []
        self.systems = []

    def generate(self, prompt, *, system=None, **kwargs):
        self.prompts.append(prompt)
        self.systems.append(system)
        return LLMResponse(text="An explanation.", provider=self.name, model="fake")


# ------------------------------------------------------------- stemming


def test_ies_plurals_meet_their_singular():
    """The v1 stemmer turned "subsidies" into "subsidie" while a student's
    "subsidy" stayed "subsidy", so core unit 3 content read as off-syllabus."""
    assert tokenise("subsidies")[0] == tokenise("subsidy")[0]
    assert tokenise("externalities")[0] == tokenise("externality")[0]
    assert tokenise("monopolies")[0] == tokenise("monopoly")[0]


def test_stemming_still_protects_ss_and_us_endings():
    assert tokenise("surplus process") == ["surplus", "process"]


# ------------------------------------------------------- the scope gate


def test_ordinary_english_does_not_make_a_question_out_of_scope(retriever):
    """The v1 gate counted "affect" as evidence of being off-syllabus."""
    for question in [
        "how does a subsidy affect the market",
        "what happens to the price when supply increases",
        "why do governments impose maximum prices",
        "i dont understand opportunity cost",
    ]:
        assert not retriever.unknown_terms(question), question


def test_a_technical_unknown_still_refuses(retriever):
    report = retriever.scope_report("explain indifference curves")
    assert not report.in_scope
    assert report.reason == "unknown_terms"
    assert "indifference" in report.unknown_terms


def test_the_general_list_holds_no_economics(retriever):
    """A leaked economics term would silently disarm the guard for that word."""
    for term in ["demand", "supply", "elasticity", "inflation", "scarcity",
                 "subsidy", "monopoly", "externality", "utility"]:
        assert tokenise(term)[0] not in GENERAL_WORDS, term


def test_refusal_reports_the_topics_that_did_score(retriever):
    report = retriever.scope_report("explain indifference curves")
    assert report.near_misses, "a refusal should still offer somewhere to go"


def test_a_question_of_only_ordinary_words_fails_on_the_floor(retriever):
    report = retriever.scope_report("what should I do tomorrow")
    assert not report.in_scope
    assert report.reason == "below_floor"


# ------------------------------------------------------- notes as corpus


def test_notes_widen_the_vocabulary(spine, note_docs):
    without = SpineRetriever(spine)
    with_notes = SpineRetriever(spine, note_docs)
    assert with_notes.counts()["notes"] == len(note_docs)
    assert len(with_notes.vocabulary) > len(without.vocabulary)


def test_a_note_phrase_can_carry_a_question_the_spine_misses(spine, note_docs):
    """"market failure" is student wording; the excerpt's outcome lines do not
    contain it, the notes do."""
    question = "what is market failure"
    assert "failure" not in SpineRetriever(spine).vocabulary
    assert SpineRetriever(spine, note_docs).is_in_scope(question)


def test_note_documents_are_split_by_section():
    body = {"definitions": [{"term": "T", "meaning": "M"}], "evaluation": ["E"]}
    docs = note_documents(body, topic_code="1.1", topic_title="Topic")
    assert {d.ref for d in docs} == {"definitions", "evaluation"}
    assert all(d.source == "note" for d in docs)


def test_a_malformed_note_body_is_ignored_not_raised():
    assert note_documents("not json", topic_code="1.1", topic_title="T") == []


def test_syllabus_context_precedes_note_context(spine, note_docs):
    tutor = ConceptTutor(FakeProvider(), spine, documents=note_docs)
    hits = tutor.retriever.search("merit goods")
    context = tutor.build_context(hits)
    assert "Syllabus outcomes:" in context
    assert "Revision notes" in context
    assert context.index("Syllabus outcomes:") < context.index("Revision notes")


# ---------------------------------------------------------- follow-ups


def test_a_follow_up_inherits_the_previous_question(spine, note_docs):
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine, documents=note_docs)
    history = [
        {"question": "what is opportunity cost", "answer": "Because...",
         "in_scope": True}
    ]
    result = tutor.explain("why?", history=history)

    assert result.in_scope, "a follow-up must not be refused for having no nouns"
    assert result.followed_up
    assert "opportunity cost" in provider.prompts[0].lower()
    assert "Earlier in this conversation" in provider.prompts[0]


def test_a_follow_up_with_no_history_is_still_refused(spine, note_docs):
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine, documents=note_docs)
    result = tutor.explain("why?", history=[])
    assert result.is_refusal
    assert provider.prompts == []


def test_a_new_off_topic_question_does_not_inherit_scope(spine, note_docs):
    """The follow-up path must not become a way in for anything unmatched."""
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine, documents=note_docs)
    history = [
        {"question": "what is opportunity cost", "answer": "...", "in_scope": True}
    ]
    result = tutor.explain("explain indifference curves", history=history)
    assert result.is_refusal
    assert provider.prompts == []


def test_history_sent_to_the_model_is_bounded(spine, note_docs):
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine, documents=note_docs)
    history = [
        {"question": f"question {i}", "answer": "x" * 5000, "in_scope": True}
        for i in range(6)
    ]
    history[-1]["question"] = "what is opportunity cost"
    tutor.explain("give me an example", history=history)
    assert "question 0" not in provider.prompts[0]
    assert provider.prompts[0].count("x" * 800) == 0


# -------------------------------------------------------- exam technique


def test_exam_technique_questions_route_away_from_concept_retrieval(spine):
    tutor = ConceptTutor(FakeProvider(), spine)
    assert tutor.is_exam_question("what does evaluate mean in the exam")
    assert tutor.is_exam_question("how many marks is section B worth")
    assert tutor.is_exam_question("how should I structure a 12 mark answer")


def test_an_economics_question_containing_an_exam_noun_is_not_rerouted(spine):
    """"what happens to the price of paper" is about paper, not Paper 2."""
    tutor = ConceptTutor(FakeProvider(), spine)
    assert not tutor.is_exam_question("what happens to the price of paper")


def test_exam_answer_is_grounded_in_cambridge_command_words(spine):
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine)
    result = tutor.explain("what does evaluate mean in the exam")

    assert result.kind == "exam"
    prompt = provider.prompts[0]
    assert "Evaluate:" in prompt or "Evaluate: " in prompt
    assert "60 marks" in prompt  # Paper 2 structure, from code not the model
    assert "no\nA* at AS" in prompt or "there is no " in prompt


def test_exam_prompt_forbids_inventing_thresholds(spine):
    provider = FakeProvider()
    ConceptTutor(provider, spine).explain("how many marks is section B worth")
    assert "Do not invent mark allocations" in provider.systems[0]
