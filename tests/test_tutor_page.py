"""Drive the Concept Tutor screen headlessly, including the text box.

The v1 failure was invisible to every test in the suite: retrieval had unit
tests, the page had a static existence check, and nothing in between ever typed
a question the way a student types one and looked at what came back. These
tests do exactly that, with a fake provider so they spend nothing.

Skipped rather than failed when the spine is absent — a fresh clone has no
syllabus PDF, and the parse is the user's own.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

from src.config import settings
from src.llm.provider import LLMResponse

PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "2_Concept_Tutor.py")

pytestmark = pytest.mark.skipif(
    not settings.spine_path.exists()
    or not (settings.groq_api_key or settings.gemini_api_key or settings.mistral_api_key),
    reason="needs a parsed spine and at least one key in .env — both are local",
)


class FakeProvider:
    name = "fake"
    calls: list[str] = []

    def generate(self, prompt, *, system=None, **kwargs):
        FakeProvider.calls.append(prompt)
        return LLMResponse(
            text="Opportunity cost is the next best alternative forgone.",
            provider="fake",
            model="fake",
        )


@pytest.fixture(autouse=True)
def no_real_provider(monkeypatch):
    import streamlit as st

    # `st.cache_resource` and `st.cache_data` are process-global and survive
    # every AppTest run in the session, so whichever test runs a page FIRST
    # decides which provider every later test gets. Clearing per test is the
    # only way each one builds its own tutor around its own fake.
    st.cache_resource.clear()
    st.cache_data.clear()

    import src.llm.provider as provider_module

    FakeProvider.calls = []
    monkeypatch.setattr(provider_module, "build_provider", lambda _settings: FakeProvider())
    monkeypatch.setattr(settings.__class__, "groq_api_key", "test-key", raising=False)
    yield


# Generous on purpose. The FIRST AppTest run in a pytest process pays for
# everything cold — Streamlit's own start-up, the module imports, the spine
# parse, the note corpus and the tf-idf build — while every later run hits
# `st.cache_resource` and `st.cache_data`, which are process-global and
# therefore already warm. On a slower machine that first run took over 30
# seconds and failed alone while the other twelve passed, which looks like a
# bug in the page and is not one. The timeout is a ceiling, not a wait: a
# healthy run still finishes in whatever it finishes in.
FIRST_RUN_TIMEOUT = 120


def _run() -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=FIRST_RUN_TIMEOUT)
    at.run()
    return at


def test_page_loads_without_spending_a_token():
    at = _run()
    assert not at.exception
    assert FakeProvider.calls == []


def test_the_browse_panel_is_present():
    at = _run()
    text = " ".join(m.value for m in at.markdown) + " ".join(c.value for c in at.caption)
    assert "Browse" in " ".join(e.label for e in at.expander) or "Browse" in text


def test_a_typed_question_reaches_the_model_and_is_answered():
    """The whole point of the upgrade: the text box, not the buttons."""
    at = _run()
    at.chat_input[0].set_value("how does a subsidy affect the market").run()

    assert not at.exception
    assert FakeProvider.calls, "a typed in-scope question never reached the model"
    answered = any("next best alternative" in m.value for m in at.markdown)
    assert answered, "the answer was not rendered on the page"


def test_an_off_syllabus_question_is_refused_by_name_and_costs_nothing():
    at = _run()
    at.chat_input[0].set_value("how do I bake sourdough bread").run()

    assert not at.exception
    assert FakeProvider.calls == []
    said = " ".join(i.value for i in at.info)
    assert "sourdough" in said


def test_a_follow_up_is_answered_rather_than_refused():
    at = _run()
    at.chat_input[0].set_value("what is opportunity cost").run()
    first = len(FakeProvider.calls)
    at.chat_input[0].set_value("why?").run()

    assert not at.exception
    assert len(FakeProvider.calls) == first + 1, "the follow-up was refused"
    assert "Earlier in this conversation" in FakeProvider.calls[-1]


def test_a_misspelt_whole_course_question_is_answered_not_refused():
    """The report that prompted v3: "what is macroeconimics" was refused."""
    at = _run()
    at.chat_input[0].set_value("what is macroeconimics").run()

    assert not at.exception
    assert FakeProvider.calls, "a misspelt chapter-level question was refused"
    captions = " ".join(c.value for c in at.caption)
    assert "macroeconomy" in captions, "the substitution was not shown to the student"


def test_an_answer_carries_its_chapter_sources():
    at = _run()
    at.chat_input[0].set_value("what causes inflation").run()

    assert not at.exception
    # The summary line must be visible WITHOUT opening anything: sources
    # hidden inside a collapsed panel read as no sources at all.
    captions = " ".join(c.value for c in at.caption)
    assert "From Chapter" in captions
    shown = " ".join(m.value for m in at.markdown)
    assert "Chapter" in shown


def test_a_question_with_one_unknown_word_is_answered_around_it():
    """Reported: "how do i differentiate gdp and gnp" was refused outright,
    though GDP is topic 4.1 and the syllabus's own term is GNI."""
    at = _run()
    at.chat_input[0].set_value("how do i differentiate gdp and gnp").run()

    assert not at.exception
    assert FakeProvider.calls, "a question with a real syllabus subject was refused"
    prompt = FakeProvider.calls[-1]
    assert "does not appear anywhere in the AS syllabus" in prompt
    assert "do not explain it" in prompt
    captions = " ".join(c.value for c in at.caption)
    assert "gnp" in captions.lower()


def test_ordinary_words_are_not_rewritten_into_syllabus_terms():
    """Reported: "exam"->"example", "know"->"knowledge", "mark"->"market"."""
    at = _run()
    at.chat_input[0].set_value(
        "for exam preparation i would like to know how marks are distributed"
    ).run()

    assert not at.exception
    captions = " ".join(c.value for c in at.caption)
    for mangled in ["example", "knowledge", "market", "prepared"]:
        assert f"as “{mangled}”" not in captions, mangled


# --------------------------------------------- the data response panel


def _all_text(at) -> str:
    chunks = [m.value for m in at.markdown] + [c.value for c in at.caption]
    chunks += [e.label for e in at.expander]
    chunks += [str(getattr(m, "label", "")) for m in at.metric]
    return " ".join(c for c in chunks if c)


def test_the_data_response_panel_is_on_the_page():
    at = _run()
    assert not at.exception
    assert "Learn the data response" in " ".join(e.label for e in at.expander)


def test_the_data_response_panel_costs_nothing_to_open():
    """Shapes, caps, timings and command words are all read from code."""
    at = _run()
    assert FakeProvider.calls == []
    text = _all_text(at)
    assert "20 marks" in text or "Section A" in text


def test_a_data_response_question_typed_into_the_box_is_answered():
    at = _run()
    at.chat_input[0].set_value("How do I answer a data response?").run()
    assert not at.exception
    assert FakeProvider.calls, "the question never reached a provider"
    assert "specimen_2023" in FakeProvider.calls[-1]


def test_rendering_the_page_never_marks_a_question_as_seen():
    """A screen that writes to the database by being displayed writes on every
    rerun. The first version of the walkthrough did exactly that: running this
    file's tests burned all twelve banked data responses."""
    from src.store.db import Store

    store = Store(settings.db_path)
    if not store.is_initialised():
        pytest.skip("no initialised database")
    before = store.seen_group_ids()
    _run()
    _run()
    assert store.seen_group_ids() == before
