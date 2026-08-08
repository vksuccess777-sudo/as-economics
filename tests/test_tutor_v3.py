"""Tests for the third version of the Concept Tutor.

The bug these exist to prevent: "what is macroeconomics" — a question about
half the AS course — was refused, because unit titles were in no document and
because vocabulary membership was an exact string match. A student who cannot
spell "macroeconomics" is exactly the student who needs to ask what it is.
"""

from __future__ import annotations

import pytest

from src.llm.provider import LLMResponse
from src.syllabus.parser import parse_text
from src.tutor.explainer import ConceptTutor, build_sources
from src.tutor.retriever import SpineRetriever, Vocabulary, tokenise
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


# --------------------------------------------------------- sibilant plurals


def test_sibilant_plurals_reach_their_singular():
    """"taxes" gave "taxe" and "losses" gave "losse" — the -ies bug again."""
    assert tokenise("taxes")[0] == tokenise("tax")[0]
    assert tokenise("losses")[0] == tokenise("loss")[0]


# ------------------------------------------------------------- resolution


def test_a_prefix_resolves_to_the_full_term():
    vocab = Vocabulary({"macroeconomy", "microeconomy", "demand"})
    assert vocab.resolve("macro") == "macroeconomy"


def test_a_shared_root_resolves_across_word_forms():
    vocab = Vocabulary({"macroeconomy"})
    assert vocab.resolve("macroeconomic") == "macroeconomy"


def test_a_typo_resolves_in_a_long_word():
    vocab = Vocabulary({"macroeconomy", "inflation", "elasticity"})
    assert vocab.resolve("macroeconimic") == "macroeconomy"
    assert vocab.resolve("inflasion") == "inflation"


def test_resolution_does_not_reach_across_meanings():
    """The loose end of this feature: an off-syllabus word finding a home."""
    vocab = Vocabulary({"indirect", "price", "index", "money", "monetary"})
    for token in ["indifference", "india", "president", "monopoly", "deadweight"]:
        assert vocab.resolve(token) is None, token


def test_short_fragments_do_not_resolve():
    vocab = Vocabulary({"demand", "supply"})
    assert vocab.resolve("dem") is None


def test_the_substitution_is_reported_not_silent(retriever):
    """A student who used the wrong word must see which one was answered."""
    _, resolved, _ = retriever.resolve_query("what is oportunity cost")
    assert resolved.get("oportunity") == "opportunity"


# --------------------------------------------------------------- chapters


def test_unit_titles_are_searchable(spine):
    """"The Macroeconomy" is the name of unit 4 and was in no document."""
    retriever = SpineRetriever(spine)
    assert retriever.counts()["chapters"] == len(spine.units)
    hits = retriever.search("macroeconomy")
    assert hits and hits[0].source == "chapter"


def test_a_whole_course_area_question_is_in_scope(spine):
    retriever = SpineRetriever(spine)
    for question in [
        "what is macroeconomics",
        "what is macro economics",
        "what is the macroeconomy",
    ]:
        assert retriever.is_in_scope(question), question


def test_chapters_do_not_pollute_the_topic_list(spine):
    """Topic coverage is topics; a chapter is not one."""
    retriever = SpineRetriever(spine)
    hits = retriever.search("macroeconomy")
    assert all(code != "4" for code, _ in retriever.topics_covered(hits))


# --------------------------------------------------- syllabus exclusions


def test_a_not_required_term_is_named_as_such_not_refused_blankly(spine):
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine, excluded_phrases=[["multiplier"]])
    result = tutor.explain("explain the multiplier")

    assert result.is_refusal
    assert provider.prompts == []
    assert "not required" in result.text.lower()


def test_exclusion_is_by_phrase_not_by_word(spine):
    """"marginal revenue product" must not retire the word "revenue"."""
    retriever = SpineRetriever(
        spine, excluded_phrases=[["marginal", "revenue", "product"]]
    )
    assert retriever.excluded_in(tokenise("what is marginal revenue product"))
    assert not retriever.excluded_in(tokenise("how do taxes raise revenue"))


# ----------------------------------------------------------- attribution


def test_sources_name_chapter_and_topic(spine):
    retriever = SpineRetriever(spine)
    sources = build_sources(retriever.search("opportunity cost", k=6))
    assert sources
    first = sources[0]
    assert first.unit_code and first.unit_title
    assert first.topic_code.startswith("1.")
    assert "Chapter" in first.chapter


def test_a_chapter_source_appears_only_when_nothing_inside_it_matched(spine):
    retriever = SpineRetriever(spine)
    chapter_only = build_sources(retriever.search("macroeconomy", k=6))
    assert any(s.is_chapter for s in chapter_only)

    specific = build_sources(retriever.search("opportunity cost", k=6))
    units_with_topics = {s.unit_code for s in specific if not s.is_chapter}
    assert not [
        s for s in specific if s.is_chapter and s.unit_code in units_with_topics
    ]


def test_sources_are_attached_to_an_answer(spine):
    result = ConceptTutor(FakeProvider(), spine).explain("what is opportunity cost")
    assert result.sources
    assert result.sources[0].detail(), "a source with nothing under it is decoration"


def test_the_model_is_told_not_to_write_its_own_references(spine):
    """Citations are computed from the retrieved documents. A model that
    writes its own can invent one, and an invented chapter reference sends a
    student to the wrong page while looking authoritative."""
    provider = FakeProvider()
    ConceptTutor(provider, spine).explain("what is opportunity cost")
    assert "do not write your own references" in provider.systems[0].lower()
