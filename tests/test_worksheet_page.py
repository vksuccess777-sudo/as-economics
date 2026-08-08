"""Drive the Worksheet Helper screen the way a student uses it.

Unit tests cover segmentation and solving. This covers the join: paste a
worksheet, get items on screen, ask for one solution, and check that exactly
one model call happened and that the screen says where the answer came from.

Skipped rather than failed without a parsed spine and a key — both are local to
the user's machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from streamlit.testing.v1 import AppTest

from src.config import settings
from src.llm.provider import LLMResponse

PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "6_Worksheet_Helper.py")

pytestmark = pytest.mark.skipif(
    not settings.spine_path.exists()
    or not (settings.groq_api_key or settings.gemini_api_key or settings.mistral_api_key),
    reason="needs a parsed spine and at least one key in .env — both are local",
)

WORKSHEET = """1. Identify, in each case, a government policy measure that could be used to
correct the following examples of market failure.
(a) Air pollution from a coal-fired power station. [2]
(b) Under-consumption of vaccinations in a rural district. [2]

2. Discuss whether indirect taxes are the best way to reduce cigarette
consumption. [12]
"""

ANSWER = {
    "answer": "A specific indirect tax on emissions.",
    "working": ["It raises private cost towards social cost."],
    "evaluation": ["Depends on price elasticity of demand."],
    "marks_guidance": "1 for the measure, 1 for the link.",
    "common_error": "Suggesting a subsidy.",
}


class FakeProvider:
    name = "fake"
    calls: list[str] = []

    def generate(self, prompt, *, system=None, **kwargs):
        FakeProvider.calls.append(prompt)
        return LLMResponse(text=json.dumps(ANSWER), provider="fake", model="fake")


@pytest.fixture(autouse=True)
def no_real_provider(monkeypatch):
    import src.llm.provider as provider_module

    FakeProvider.calls = []
    monkeypatch.setattr(provider_module, "build_provider", lambda _s: FakeProvider())
    yield


def _loaded() -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    at.text_area[0].set_value(WORKSHEET).run()
    return at


def test_the_page_loads_and_spends_nothing():
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert not at.exception
    assert FakeProvider.calls == []


def test_an_empty_page_asks_for_a_worksheet_rather_than_erroring():
    at = AppTest.from_file(PAGE, default_timeout=60).run()
    assert any("Nothing loaded" in info.value for info in at.info)


def test_pasted_text_is_split_into_items_without_a_model_call():
    at = _loaded()
    assert not at.exception
    body = " ".join(m.value for m in at.markdown)
    assert "1(a)" in body and "1(b)" in body and "2" in body
    assert FakeProvider.calls == [], "reading a worksheet must cost nothing"


def test_the_question_count_and_marks_are_reported():
    at = _loaded()
    labels = {m.label: m.value for m in at.metric}
    assert labels.get("Questions") == "3"
    assert labels.get("Marks printed") == "16"


def test_an_answer_box_appears_before_any_solution():
    """Attempt first is the whole point — the box exists before the button."""
    at = _loaded()
    assert any(area.label == "Your answer" for area in at.text_area)


def test_solving_one_item_calls_the_model_once_and_shows_the_answer():
    at = _loaded()
    at.button(key="ws_solve_1(a)").click().run()

    assert not at.exception
    assert len(FakeProvider.calls) == 1
    body = " ".join(m.value for m in at.markdown)
    assert "specific indirect tax on emissions" in body.lower()


def test_the_solution_says_it_is_not_a_mark_scheme():
    at = _loaded()
    at.button(key="ws_solve_1(a)").click().run()
    captions = " ".join(c.value for c in at.caption)
    assert "mark scheme" in captions.lower()


def test_the_shared_instruction_is_in_the_prompt_for_a_lettered_part():
    at = _loaded()
    at.button(key="ws_solve_1(a)").click().run()
    assert "Identify, in each case" in FakeProvider.calls[0]


def test_an_essay_item_is_answered_with_a_plan_not_an_essay():
    at = _loaded()
    at.button(key="ws_solve_2").click().run()
    assert "Do NOT write the essay" in FakeProvider.calls[0]
    body = " ".join(m.value for m in at.markdown) + " ".join(i.value for i in at.info)
    assert "plan, not an essay" in body.lower()


def test_solving_one_item_does_not_solve_the_others():
    at = _loaded()
    at.button(key="ws_solve_1(a)").click().run()
    assert len(FakeProvider.calls) == 1


def test_nothing_is_written_to_the_attempt_log():
    """Worksheet work must never enter the data the AI Coach diagnoses from."""
    from src.store.db import Store

    store = Store(settings.db_path)
    before = store.counts()
    at = _loaded()
    at.button(key="ws_solve_1(a)").click().run()
    assert store.counts() == before
