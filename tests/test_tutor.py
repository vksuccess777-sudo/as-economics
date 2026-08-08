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
def a_level_spine():
    return parse_text(SYLLABUS_EXCERPT, level="A")


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


# ---------------------------------------------------------- tokenising


def test_stopwords_and_short_words_are_dropped():
    assert tokenise("What is the meaning of opportunity cost?") == ["opportunity", "cost"]


def test_question_framing_words_do_not_become_search_terms():
    """"Explain the difference between X and Y" must search for X and Y only."""
    assert tokenise("Explain the difference between demand and supply") == [
        "demand",
        "supply",
    ]


def test_empty_query_returns_no_hits(retriever):
    assert retriever.search("what is the?") == []


# ----------------------------------------------------------- retrieval


def test_retrieval_finds_the_right_topic(retriever):
    hits = retriever.search("what is opportunity cost")
    assert hits[0].topic_code == "1.1"


def test_topic_title_contributes_to_matching(retriever):
    """"scarcity" appears in the topic title, not only in outcome text."""
    hits = retriever.search("scarcity")
    assert hits[0].topic_code == "1.1"


def test_topics_covered_deduplicates_and_sorts(retriever):
    hits = retriever.search("demand and supply curves")
    codes = [code for code, _ in retriever.topics_covered(hits)]
    assert codes == sorted(set(codes))


def test_unrelated_question_falls_below_the_relevance_floor(retriever):
    """The guard that stops the tutor answering from general knowledge."""
    assert not retriever.is_in_scope("how do I bake sourdough bread")
    assert not retriever.is_in_scope("what is photosynthesis")


def test_a_genuine_syllabus_question_clears_the_floor(retriever):
    assert retriever.is_in_scope("explain opportunity cost")
    assert retriever.is_in_scope("what shifts the demand curve")


# --------------------------------------------------------------- tutor


def test_in_scope_question_reaches_the_model_with_syllabus_context(spine):
    provider = FakeProvider()
    result = ConceptTutor(provider, spine).explain("what is opportunity cost")

    assert result.in_scope
    assert result.text == "An explanation."
    assert len(provider.prompts) == 1
    assert "opportunity cost" in provider.prompts[0].lower()
    assert "Student's question" in provider.prompts[0]


def test_out_of_scope_question_never_reaches_the_model(spine):
    """No tokens spent, and no confident answer invented."""
    provider = FakeProvider()
    result = ConceptTutor(provider, spine).explain("how do I bake sourdough bread")

    assert result.is_refusal
    assert provider.prompts == [], "an out-of-scope question must not call the LLM"
    # The refusal names the word it could not place. A refusal the student
    # cannot interrogate is indistinguishable from a broken text box.
    assert "sourdough" in result.text


def test_a_level_question_is_diagnosed_rather_than_refused_vaguely(spine, a_level_spine):
    provider = FakeProvider()
    tutor = ConceptTutor(provider, spine, a_level_spine=a_level_spine)
    result = tutor.explain("explain indifference curves and total utility")

    assert result.is_refusal
    assert provider.prompts == []
    assert "A Level content" in result.text
    assert result.a_level_topics


def test_without_the_a_level_spine_the_refusal_is_still_safe(spine):
    provider = FakeProvider()
    result = ConceptTutor(provider, spine).explain("explain indifference curves")
    assert result.is_refusal
    assert provider.prompts == []


def test_system_prompt_forbids_inventing_numbers(spine):
    provider = FakeProvider()
    ConceptTutor(provider, spine).explain("what is opportunity cost")
    system = provider.systems[0]
    assert "Never invent numerical thresholds" in system
    assert "cannot draw" in system


def test_context_is_grouped_by_topic(spine):
    tutor = ConceptTutor(FakeProvider(), spine)
    hits = tutor.retriever.search("opportunity cost and choices")
    context = tutor.build_context(hits)
    assert "Scarcity, choice and opportunity cost:" in context
    assert context.count("Scarcity, choice and opportunity cost:") == 1


def test_topics_are_reported_for_the_ui(spine):
    result = ConceptTutor(FakeProvider(), spine).explain("what is opportunity cost")
    assert ("1.1", "Scarcity, choice and opportunity cost") in result.topics


# ------------------------------------------------- vocabulary coverage


def test_a_shared_common_word_alone_does_not_put_a_question_in_scope(retriever):
    """Regression: "indifference curves" matched "Demand and supply curves"
    on the word "curves" alone, and would have been answered as AS content."""
    assert not retriever.is_in_scope("explain indifference curves")


def test_vocabulary_coverage_scores_known_and_unknown_terms(retriever):
    assert retriever.vocabulary_coverage("opportunity cost") == 1.0
    assert retriever.vocabulary_coverage("sourdough photosynthesis") == 0.0
    assert 0 < retriever.vocabulary_coverage("indifference curves") < 1.0


def test_coverage_does_not_block_ordinary_syllabus_questions(retriever):
    for question in [
        "what is opportunity cost",
        "what causes a shift in the demand curve",
        "explain the difference between demand and supply",
    ]:
        assert retriever.is_in_scope(question), question


def test_singular_and_plural_forms_match_each_other(retriever):
    """Students write "the demand curve"; the syllabus writes "demand curves"."""
    assert retriever.is_in_scope("what causes a shift in the demand curve")
    assert retriever.is_in_scope("what causes shifts in demand curves")
    singular = retriever.search("demand curve")
    plural = retriever.search("demand curves")
    # Compared by ref, not outcome.code: chapter documents carry no outcome.
    assert [h.ref for h in singular] == [h.ref for h in plural]


def test_stemming_does_not_mangle_economics_terms():
    from src.tutor.retriever import tokenise
    assert "surplus" in tokenise("consumer surplus")
    assert "analysis" in tokenise("AD AS analysis")
