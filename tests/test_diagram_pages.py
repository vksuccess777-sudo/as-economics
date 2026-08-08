"""The diagrams have to actually reach the screen.

`st.image` accepting a raw SVG string is the load-bearing assumption of the
whole renderer. It is an assumption about Streamlit, not about this code, so
it gets asserted by driving the real page rather than by reading the source.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.config import settings
from src.llm.provider import LLMResponse

ROOT = Path(__file__).resolve().parent.parent
KB = str(ROOT / "pages" / "5_Knowledge_Base.py")
TUTOR = str(ROOT / "pages" / "2_Concept_Tutor.py")
FIRST_RUN_TIMEOUT = 120

pytestmark = pytest.mark.skipif(
    not settings.spine_path.exists(),
    reason="needs a parsed spine — local to the user's machine",
)


class _FakeProvider:
    name = "fake"

    def generate(self, prompt, *, system=None, **kwargs):
        return LLMResponse(text="…", provider="fake", model="fake")


@pytest.fixture(autouse=True)
def no_real_provider(monkeypatch):
    """`st.cache_resource` is process-global and survives every AppTest run.

    Running the Concept Tutor here without this fixture cached a ConceptTutor
    holding a REAL Groq client, and every later test in the session then made
    live API calls through the cached object — seven failures in
    test_tutor_page.py that passed in isolation. Any test that runs a page
    must patch the provider, even when it never intends to ask a question.
    """
    import streamlit as st

    # `st.cache_resource` and `st.cache_data` are process-global and survive
    # every AppTest run in the session, so whichever test runs a page FIRST
    # decides which provider every later test gets. Clearing per test is the
    # only way each one builds its own tutor around its own fake.
    st.cache_resource.clear()
    st.cache_data.clear()

    import src.llm.provider as provider_module

    monkeypatch.setattr(
        provider_module, "build_provider", lambda _settings: _FakeProvider()
    )
    monkeypatch.setattr(settings.__class__, "groq_api_key", "test-key", raising=False)
    yield


def _text(at) -> str:
    return " ".join(
        [m.value for m in at.markdown] + [c.value for c in at.caption]
    )


def _at_topic(chapter: str, topic: str):
    at = AppTest.from_file(KB, default_timeout=FIRST_RUN_TIMEOUT)
    at.run()
    assert not at.exception
    at.selectbox[0].set_value(chapter).run()
    # `.options` holds the FORMATTED labels ("✓ 4.3 Aggregate demand…"), not
    # the raw codes, so guarding on membership there silently skips every
    # test. set_value takes the underlying value.
    picker = [r for r in at.radio if r.label == "Topic"][0]
    picker.set_value(topic).run()
    return at


def test_the_knowledge_base_loads():
    at = AppTest.from_file(KB, default_timeout=FIRST_RUN_TIMEOUT)
    at.run()
    assert not at.exception


def test_a_macro_topic_draws_its_diagram():
    at = _at_topic("4", "4.3")
    assert not at.exception
    text = _text(at)
    assert "Aggregate demand and aggregate supply" in text
    assert "Drawn in code" in text


def test_the_diagram_controls_are_offered():
    at = _at_topic("4", "4.3")
    labels = {r.label for r in at.radio}
    assert "shift" in labels
    assert "direction" in labels


def test_changing_the_direction_redraws_without_error():
    at = _at_topic("4", "4.3")
    direction = [r for r in at.radio if r.label == "direction"][0]
    direction.set_value("left").run()
    assert not at.exception
    assert "Drawn in code" in _text(at)


def test_a_micro_intervention_topic_draws_its_diagrams():
    at = _at_topic("3", "3.2")
    assert not at.exception
    text = _text(at)
    assert "Indirect tax" in text
    assert "Buffer stock" in text


def test_a_topic_with_no_diagram_says_so_rather_than_drawing_a_wrong_one():
    at = _at_topic("1", "1.1")
    assert not at.exception
    assert "Drawn in code" not in _text(at)


def test_the_concept_tutor_still_loads_with_diagrams_wired_in():
    at = AppTest.from_file(TUTOR, default_timeout=FIRST_RUN_TIMEOUT)
    at.run()
    assert not at.exception


def test_a_concept_answer_actually_shows_a_diagram():
    """The first version of `_diagrams_for` read `source.code`; the attribute
    is `topic_code`, so it matched nothing and NO diagram ever appeared. The
    page still loaded, so a "page loads" test passed happily. This asserts the
    diagram reaches the screen."""
    at = AppTest.from_file(TUTOR, default_timeout=FIRST_RUN_TIMEOUT)
    at.run()
    assert not at.exception
    at.chat_input[0].set_value("how does an indirect tax affect the market").run()
    assert not at.exception
    labels = [m.value for m in at.markdown]
    assert any("Indirect tax" in label for label in labels), labels[-6:]


def test_the_diagram_matches_what_was_asked():
    at = AppTest.from_file(TUTOR, default_timeout=FIRST_RUN_TIMEOUT)
    at.run()
    at.chat_input[0].set_value("what is a maximum price").run()
    assert not at.exception
    labels = " ".join(m.value for m in at.markdown)
    assert "Maximum price" in labels


# ------------------------------------------------------------ actually visible


def _svg_blocks(at) -> list[str]:
    return [m.value for m in at.markdown if "<svg" in m.value]


def test_the_knowledge_base_emits_a_real_svg_not_just_a_heading():
    """The render path moved from st.image to inline HTML for sizing. Asserting
    on the heading alone would pass with the diagram gone."""
    at = _at_topic("4", "4.3")
    blocks = _svg_blocks(at)
    assert blocks, "no SVG reached the page"
    assert 'viewBox="0 0 720 520"' in blocks[0]
    assert "max-width" in blocks[0]


def test_the_size_control_is_offered_and_changes_the_wrapper():
    at = _at_topic("4", "4.3")
    sizes = [r for r in at.radio if r.label == "Diagram size"]
    assert sizes, "no size control"
    assert "max-width:900px" in _svg_blocks(at)[0]
    sizes[0].set_value("Full width").run()
    assert not at.exception
    assert "max-width" not in _svg_blocks(at)[0]


def test_the_tutor_emits_a_real_svg_too():
    at = AppTest.from_file(TUTOR, default_timeout=FIRST_RUN_TIMEOUT)
    at.run()
    at.chat_input[0].set_value("how does an indirect tax affect the market").run()
    assert not at.exception
    assert _svg_blocks(at), "no SVG reached the tutor answer"
