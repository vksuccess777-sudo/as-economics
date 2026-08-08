"""Drive the Section A screen the way a student uses it.

Everything here runs against a TEMPORARY database. An earlier test in this
project deleted real files as a side effect of running pytest; a test must
never mutate the repo it tests, and that includes the attempt log.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import src.config as config_module
from src.config import settings
from src.llm.provider import LLMResponse
from src.store.db import Store

PAGE = str(Path(__file__).resolve().parent.parent / "pages" / "7_Data_Response.py")

# The screen itself was withdrawn; the engine behind it was not. These tests
# skip rather than fail when the page file is absent, so restoring the screen
# restores its coverage with no other change.
pytestmark = [
    pytest.mark.skipif(
        not Path(PAGE).exists(),
        reason="the Data Response screen is not installed (withdrawn)",
    ),
    pytest.mark.skipif(
        not settings.spine_path.exists(),
        reason="needs a parsed spine — local to the user's machine",
    ),
]

STIMULUS = {
    "title": "Testland after the shock",
    "extract": "Output fell in 2020 and recovered in 2021. The bank called it "
               "'a recovery running out of room'.",
    "table_caption": "Table 1.1 Real GDP growth, Testland",
    "table_headers": ["Year", "GDP growth (%)"],
    "table_rows": [["2019", "2.4"], ["2020", "-9.3"], ["2021", "7.6"]],
    "attribution": "World Bank Open Data — Demo indicators. CC BY 4.0. "
                   "Retrieved 2026-08-06 from https://data.worldbank.org/indicator/DEMO",
    "dataset": "demo",
    "shape": "specimen_2023",
}

PARTS = [
    ("(a)", 2, "Using Table 1.1, compare growth in 2020 with growth in 2021.", "knowledge", 3),
    ("(b)(i)", 2, "Explain the relationship you would expect between growth and employment.", "analysis", 3),
    ("(b)(ii)", 2, "Consider the extent to which that is evident in the data.", "analysis", 3),
    ("(c)", 2, "Using the information provided, explain one supply-side constraint.", "knowledge", 3),
    ("(d)", 6, "Assess the likely effects on employment of the fall in output.", "analysis", 8),
    ("(e)", 6, "Assess whether this is 'a recovery running out of room'.", "analysis", 8),
]


class FakeProvider:
    name = "fake"
    calls: list[str] = []

    def generate(self, prompt, *, system=None, **kwargs):
        FakeProvider.calls.append(prompt)
        return LLMResponse(
            text=json.dumps(
                {
                    "judgements": [{"index": 0, "met": True, "why": "stated clearly"}],
                    "advice": "Add a conclusion.",
                }
            ),
            provider="fake",
            model="fake",
        )


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Point the whole page at a throwaway database, and bank one question."""
    db_path = tmp_path / "t.sqlite3"
    monkeypatch.setattr(
        config_module, "settings", dataclasses.replace(settings, db_path=db_path)
    )
    st.cache_resource.clear()
    st.cache_data.clear()

    store = Store(db_path)
    store.initialise()
    for index, (label, marks, prompt, band, n_points) in enumerate(PARTS):
        rubric = {
            "group_id": "g1",
            "part": label,
            "part_index": index,
            "kind": "assess" if marks == 6 else "data_read",
            "points": [{"text": f"point {i} for {label}", "band": band} for i in range(n_points)],
            "caps": {"analysis": 4, "evaluation": 2} if marks == 6 else None,
            "provenance": "generated_indicative",
        }
        if index == 0:
            rubric["stimulus"] = STIMULUS
        store.add_question(
            paper_key="paper_2",
            section_key="A",
            topic_code="1.1",
            max_marks=marks,
            body=json.dumps({"prompt": prompt}),
            origin="generated",
            syllabus_code="9708",
            syllabus_version="2026-2028",
            rubric=json.dumps(rubric),
        )

    import src.llm.provider as provider_module

    FakeProvider.calls = []
    monkeypatch.setattr(provider_module, "build_provider", lambda *a, **k: FakeProvider())
    yield store
    st.cache_resource.clear()
    st.cache_data.clear()


def _loaded() -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.run()
    return at


def test_the_page_loads_and_spends_nothing():
    at = _loaded()
    assert not at.exception
    assert FakeProvider.calls == [], "opening a question must cost no tokens"


def test_the_extract_and_every_part_are_on_screen():
    at = _loaded()
    body = " ".join(m.value for m in at.markdown)
    for label, _, prompt, _, _ in PARTS:
        assert label in body, f"{label} missing from the page"
    assert len(at.text_area) == len(PARTS)


def test_the_data_source_is_printed_under_the_table():
    """Attribution is a licence condition, not a nicety."""
    at = _loaded()
    captions = " ".join(c.value for c in at.caption)
    assert "World Bank Open Data" in captions
    assert "CC BY 4.0" in captions


def test_the_page_says_the_marks_are_indicative():
    at = _loaded()
    text = " ".join(c.value for c in at.caption)
    assert "indicative" in text.lower()


def test_the_page_separates_real_data_from_generated_prose():
    at = _loaded()
    captions = " ".join(c.value for c in at.caption).lower()
    assert "real published data" in captions
    assert "generated" in captions


def test_submitting_marks_every_part_and_totals_in_code():
    at = _loaded()
    for i, area in enumerate(at.text_area):
        area.set_value(f"An answer to part {i} with some economics in it.")
    at.run()
    at.button[0].click().run()

    assert not at.exception
    # One model call per part; nothing batched, nothing skipped.
    assert len(FakeProvider.calls) == len(PARTS)
    # One point credited per part = 6 marks out of 20.
    assert any("6 / 20" in s.value for s in at.success)


def test_blank_parts_are_recorded_as_zero_without_a_model_call(temp_db):
    at = _loaded()
    at.text_area[0].set_value("A comparison of the two years, using the table.")
    at.run()
    at.button[0].click().run()

    assert not at.exception
    assert len(FakeProvider.calls) == 1, "five blanks should spend nothing"

    with temp_db.connect() as conn:
        rows = conn.execute("SELECT awarded FROM response ORDER BY ordinal").fetchall()
    assert len(rows) == len(PARTS)
    assert rows[0]["awarded"] == 1
    assert all(r["awarded"] == 0 for r in rows[1:])


def test_marking_lands_in_the_attempt_log(temp_db):
    at = _loaded()
    at.text_area[0].set_value("A comparison of the two years, using the table.")
    at.run()
    at.button[0].click().run()

    counts = temp_db.counts()
    assert counts["attempt"] == 1
    assert counts["response"] == len(PARTS)


def test_an_empty_bank_explains_both_steps(tmp_path, monkeypatch):
    """A student with no datasets needs to be told to add data first — an
    empty screen reads as a broken feature."""
    monkeypatch.setattr(
        config_module,
        "settings",
        dataclasses.replace(settings, db_path=tmp_path / "empty.sqlite3"),
    )
    st.cache_resource.clear()
    at = AppTest.from_file(PAGE, default_timeout=90).run()
    assert not at.exception
    text = " ".join(i.value for i in at.info)
    assert "add_dataset.py" in text and "bank_data_response.py" in text
