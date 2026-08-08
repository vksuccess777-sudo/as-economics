"""A note that quietly omits the hard section is worse than no note."""

from __future__ import annotations

import json

import pytest

from src.llm.provider import LLMResponse
from src.notes.generator import (
    Note,
    NoteValidationError,
    NoteWriter,
    parse_response,
    to_note,
    validate,
)
from src.store.db import Store
from src.syllabus.parser import parse_text
from tests.fixtures import SYLLABUS_EXCERPT

GOOD = {
    "definitions": [
        {"term": "opportunity cost", "meaning": "the value of the next best alternative forgone"},
        {"term": "scarcity", "meaning": "unlimited wants against limited resources"},
        {"term": "factors of production", "meaning": "land, labour, capital and enterprise"},
    ],
    "core_ideas": [
        "Resources are finite, so every choice forgoes an alternative, so the real cost of a decision is what was given up.",
        "A shift of resources towards capital goods lowers current consumption but raises future productive capacity.",
        "Because wants exceed resources, every economy must answer what, how and for whom to produce.",
    ],
    "diagrams": [
        {"name": "Production possibility curve",
         "what_to_label": "both axes as goods, the curve, points inside and outside",
         "what_shifts": "the whole curve outwards when productive capacity rises"},
    ],
    "evaluation": [
        "Whether the opportunity cost is high depends on how close the alternative was in value.",
        "The size of the gain from reallocating resources depends on whether they are occupationally mobile.",
    ],
    "common_mistakes": [
        "Stating opportunity cost as everything given up rather than the next best alternative.",
        "Describing a movement along the PPC as a shift of it.",
    ],
    "exam_notes": [
        "Usually a two-mark definition followed by an application to a stated scenario.",
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


class FakeProvider:
    name = "fake"

    def __init__(self, payload):
        self.payload = payload

    def generate(self, prompt, **kwargs):
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return LLMResponse(text=text, provider=self.name, model="fake-model")


def raw(**overrides):
    out = json.loads(json.dumps(GOOD))
    out.update(overrides)
    return out


# ------------------------------------------------------------ validation


def test_good_note_validates():
    validate(to_note(GOOD, "1.1"))


def test_missing_evaluation_section_is_rejected():
    """AO3 is 25% of the AS mark. A note that skips it teaches skipping it."""
    item = raw(evaluation=[])
    with pytest.raises(NoteValidationError, match="'evaluation'"):
        validate(to_note(item, "1.1"))


def test_thin_section_is_rejected():
    with pytest.raises(NoteValidationError, match="needs 3"):
        validate(to_note(raw(definitions=GOOD["definitions"][:1]), "1.1"))


def test_definition_without_meaning_is_rejected():
    item = raw(definitions=[{"term": "scarcity"}, *GOOD["definitions"]])
    with pytest.raises(NoteValidationError, match="missing its term or meaning"):
        validate(to_note(item, "1.1"))


def test_a_level_content_is_rejected():
    """Teaching indifference curves to an AS student wastes revision time."""
    item = raw(core_ideas=[*GOOD["core_ideas"],
                           "An indifference curve shows combinations giving equal satisfaction."])
    with pytest.raises(NoteValidationError, match="A Level content"):
        validate(to_note(item, "1.1"))


def test_a_level_leak_anywhere_in_the_note_is_caught():
    item = raw(common_mistakes=[*GOOD["common_mistakes"],
                                "Confusing the multiplier effect with the accelerator."])
    with pytest.raises(NoteValidationError, match="A Level content"):
        validate(to_note(item, "1.1"))


def test_diagrams_may_be_empty():
    validate(to_note(raw(diagrams=[]), "1.1"))


def test_parse_response_strips_fences():
    assert parse_response('```json\n{"a": 1}\n```') == {"a": 1}


# --------------------------------------------------------------- storage


def test_note_is_written_and_read_back(store, spine):
    report = NoteWriter(FakeProvider(GOOD), store, spine).write_for_topic("1.1")
    assert report.written == 1

    row = store.note("1.1")
    assert row is not None
    note = Note.from_row(row)
    assert len(note.section("definitions")) == 3
    assert note.mistakes_text()[0].startswith("Stating opportunity cost")
    assert row["model"] == "fake-model"


def test_rewriting_a_topic_replaces_rather_than_duplicates(store, spine):
    writer = NoteWriter(FakeProvider(GOOD), store, spine)
    writer.write_for_topic("1.1")
    writer.write_for_topic("1.1")
    assert store.note_topics() == ["1.1"]


def test_rejected_note_stores_nothing(store, spine):
    bad = FakeProvider(raw(common_mistakes=[]))
    report = NoteWriter(bad, store, spine).write_for_topic("1.1")
    assert report.written == 0
    assert store.note("1.1") is None
    assert "common_mistakes" in report.rejected[0][1]


def test_unparseable_response_is_a_rejection_not_a_crash(store, spine):
    report = NoteWriter(
        FakeProvider("Here are your notes!"), store, spine
    ).write_for_topic("1.1")
    assert report.written == 0
    assert "no JSON object" in report.rejected[0][1]


def test_unknown_topic_raises(store, spine):
    with pytest.raises(ValueError, match="not in the spine"):
        NoteWriter(FakeProvider(GOOD), store, spine).write_for_topic("9.9")


# ------------------------------------------------- spine decides, not a list
#
# Regression: a correct note on topic 3.3 was rejected for mentioning the Gini
# coefficient, which outcome 3.3.2 of the real syllabus explicitly names. The
# banned-terms list had been written from memory rather than read off the
# parsed spine. The list may now only propose a rejection; the spine decides.


def test_term_named_in_the_as_spine_is_not_a_leak(spine):
    """Gini coefficient is AS content — 3.3.2 names it."""
    item = raw(core_ideas=[
        "The Gini coefficient measures income inequality, so a rise in it means income is more unequally distributed.",
        *GOOD["core_ideas"][:2],
    ])
    validate(to_note(item, "3.3"), spine=spine)


def test_a_not_required_bracket_still_excludes_the_term(spine):
    """4.2.2 says 'injections and leakages (multiplier not required)'.

    The word appears in the spine, so presence alone cannot be the test — the
    bracket takes it back.
    """
    item = raw(core_ideas=[
        "The multiplier means an initial injection raises national income by more than the injection itself.",
        *GOOD["core_ideas"][:2],
    ])
    with pytest.raises(NoteValidationError, match="not required"):
        validate(to_note(item, "4.2"), spine=spine)


def test_genuine_a_level_content_is_still_rejected_with_a_spine(spine):
    item = raw(core_ideas=[*GOOD["core_ideas"],
                           "An indifference curve shows combinations giving equal satisfaction."])
    with pytest.raises(NoteValidationError, match="not in the AS spine"):
        validate(to_note(item, "1.1"), spine=spine)


def test_vocabulary_and_exclusions_are_read_off_the_spine(spine):
    from src.notes.generator import as_vocabulary

    vocabulary, excluded = as_vocabulary(spine)
    assert "gini coefficient" in vocabulary
    assert "multiplier" in excluded
    assert "calculation" in excluded, "the bracket names what is excluded"
    # The excluded phrase is stripped from the searchable text, so a term is
    # never both covered and excluded.
    assert "multiplier not required" not in vocabulary


def test_writer_passes_the_spine_through(store, spine):
    """The end-to-end path that failed in production."""
    item = raw(core_ideas=[
        "A higher Gini coefficient means income is distributed less equally, so redistribution has more to correct.",
        *GOOD["core_ideas"][:2],
    ])
    report = NoteWriter(FakeProvider(item), store, spine).write_for_topic("3.3")
    assert report.written == 1, report.rejected


# ---------------------------------------------- forbid, then retry once
#
# Regression: topic 3.3 was rejected twice in a row on live runs — first for
# the Gini coefficient (my bug), then for the Lorenz curve (a genuine A Level
# leak, page 33 of the syllabus: "calculation of Gini coefficient and Lorenz
# curve analysis"). The gate was right the second time; the loop was wrong.
# The prompt now forbids what the gate rejects, and one retry feeds the reason
# back instead of making a person re-run the command.


class ScriptedProvider:
    name = "fake"

    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.prompts: list[str] = []

    def generate(self, prompt, **kwargs):
        self.prompts.append(prompt)
        payload = self.payloads.pop(0)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return LLMResponse(text=text, provider=self.name, model="fake-model")


def test_forbidden_list_matches_what_the_validator_rejects(spine):
    """Prompt and gate derive from one source, so they cannot drift apart."""
    from src.notes.generator import A_LEVEL_TERMS, as_vocabulary, out_of_scope_terms

    forbidden = out_of_scope_terms(spine)
    vocabulary, excluded = as_vocabulary(spine)

    for term in A_LEVEL_TERMS:
        allowed = term in vocabulary and not any(term in e or e in term for e in excluded)
        assert (term not in forbidden) == allowed, term


def test_gini_is_allowed_but_lorenz_is_forbidden(spine):
    from src.notes.generator import out_of_scope_terms

    forbidden = out_of_scope_terms(spine)
    assert "gini coefficient" not in forbidden
    assert "lorenz curve" in forbidden
    assert "multiplier" in forbidden, "named in the spine, but marked not required"


def test_prompt_names_the_topic_specific_exclusion(spine):
    from src.notes.generator import build_prompt, not_required_lines, out_of_scope_terms

    topic = spine.topic("3.3")
    prompt = build_prompt(
        topic,
        out_of_scope=out_of_scope_terms(spine),
        excluded_lines=not_required_lines(spine, topic),
    )
    assert "lorenz curve" in prompt
    assert "calculation not required" in prompt, "the whole line, not the bracket alone"


def test_rejection_is_fed_back_on_the_retry(store, spine):
    bad = raw(core_ideas=["Lorenz curve analysis shows the degree of inequality.",
                          *GOOD["core_ideas"][:2]])
    provider = ScriptedProvider(bad, GOOD)
    report = NoteWriter(provider, store, spine).write_for_topic("3.3")

    assert report.written == 1
    assert report.attempts == 2
    assert "attempt 1" in report.rejected[0][1]
    assert "lorenz curve" in provider.prompts[1].lower()
    assert "previous attempt was rejected" in provider.prompts[1]


def test_retry_is_bounded_and_still_gated(store, spine):
    """A retry earns its way in; it is never waved through."""
    bad = raw(core_ideas=["Lorenz curve analysis shows inequality.", *GOOD["core_ideas"][:2]])
    provider = ScriptedProvider(bad, bad)
    report = NoteWriter(provider, store, spine).write_for_topic("3.3")

    assert report.written == 0
    assert len(report.rejected) == 2
    assert store.note("3.3") is None
