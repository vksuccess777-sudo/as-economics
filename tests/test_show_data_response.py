"""The viewer is the only way to read a banked Section A question without
sitting a mock and spending the marking tokens, so its key names have to
match what the generator actually stores. They did not on my first pass:
the stimulus is stored under `title`, `table_headers` and `table_rows`,
the part label under `part`, and the wording in the `body` column.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.questions.data_response import SHAPES_BY_NAME  # noqa: E402
from src.store.db import Store  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "show_data_response", ROOT / "scripts" / "show_data_response.py"
)
show = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(show)


STIMULUS = {
    "title": "Prices under pressure",
    "extract": "UK inflation rose sharply, with the CPI annual rate reaching 9.1 "
               "per cent in 2022 before easing.",
    "table_caption": "Table 1.1 CPIH and CPI annual inflation rate, United Kingdom",
    "table_headers": ["Year", "CPIH annual rate (%)", "CPI annual rate (%)"],
    "table_rows": [["2022", "7.9", "9.1"], ["2023", "6.8", "7.3"]],
    "attribution": "Source: UK Office for National Statistics, OGL v3",
    "dataset": "uk-inflation-cpih-cpi",
    "shape": "june_2024",
}


@pytest.fixture
def store(tmp_path) -> Store:
    st = Store(tmp_path / "t.sqlite3")
    st.initialise()
    shape = SHAPES_BY_NAME["june_2024"]
    for index, spec in enumerate(shape.parts):
        rubric = {
            "group_id": "grp1",
            "part": spec.label,
            "part_index": index,
            "kind": spec.kind,
            "points": [{"text": f"point for {spec.label}", "band": "knowledge"}],
            "caps": None,
            "provenance": "generated_indicative",
            "diagram": None,
        }
        if index == 0:
            rubric["stimulus"] = STIMULUS
        st.add_question(
            paper_key="paper_2",
            section_key="A",
            topic_code="4.6",
            max_marks=spec.marks,
            body=json.dumps({"prompt": f"Wording for part {spec.label}"}),
            origin="generated",
            syllabus_code="9708",
            syllabus_version="2",
            rubric=json.dumps(rubric),
        )
    return st


def render(store: Store, capsys, argv: list[str]) -> str:
    """Run the script's main() against a throwaway store.

    Settings is a frozen dataclass, so the database is swapped by replacing
    the Store constructor the script calls rather than by pointing settings
    at another path.
    """
    original_store, original_argv = show.Store, sys.argv
    try:
        show.Store = lambda _path: store
        sys.argv = ["show_data_response.py", *argv]
        show.main()
    finally:
        show.Store, sys.argv = original_store, original_argv
    return capsys.readouterr().out


def test_prints_the_stimulus_and_every_part(store, capsys):
    out = render(store, capsys, [])
    assert "Prices under pressure" in out
    assert "Table 1.1" in out
    assert "Source: UK Office for National Statistics" in out
    for label in ("(a)(i)", "(a)(ii)", "(b)", "(c)", "(d)", "(e)"):
        assert label in out
    assert "Wording for part (e)" in out


def test_table_rows_are_rendered_not_dumped_as_json(store, capsys):
    """A student reading a JSON blob cannot see the table the question is about."""
    out = render(store, capsys, [])
    assert "table_rows" not in out
    assert "9.1" in out and "6.8" in out


def test_prompt_is_decoded_not_printed_as_raw_json(store, capsys):
    """The wording is JSON inside the body column. Printing the column itself
    put `{"prompt": "..."}` on screen — which is what shipped first time."""
    out = render(store, capsys, [])
    assert '{"prompt"' not in out
    assert "Wording for part (c)" in out


def test_no_part_label_prints_as_unknown(store, capsys):
    """`?` in the output means the rubric key name drifted from the generator."""
    out = render(store, capsys, [])
    assert "(?)" not in out


def test_marks_are_hidden_unless_asked_for(store, capsys):
    assert "point for (d)" not in render(store, capsys, [])
    assert "point for (d)" in render(store, capsys, ["--marks"])


def test_list_shows_the_group(store, capsys):
    out = render(store, capsys, ["--list"])
    assert "grp1" in out
    assert "20 marks" in out


def test_empty_database_says_so_rather_than_failing(tmp_path, capsys):
    empty = Store(tmp_path / "empty.sqlite3")
    empty.initialise()
    out = render(empty, capsys, [])
    assert "No data responses banked" in out
