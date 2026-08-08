"""The reshaper stands between a downloaded file and add_dataset.py.

Its failures are the quiet kind — a monthly figure read as an annual one, a
year present in one indicator and missing from another — so the refusals are
tested as carefully as the successes.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "tidy_reference_csv", ROOT / "scripts" / "tidy_reference_csv.py"
)
tidy = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(tidy)


YEARS = [str(y) for y in range(2014, 2024)]


def world_bank_csv(tmp_path: Path, code: str, name: str, series: dict, *, zipped=True) -> Path:
    rows = [
        ["Data Source", "World Development Indicators", "", ""],
        ["Last Updated Date", "2026-07-01", "", ""],
        [],
        ["Country Name", "Country Code", "Indicator Name", "Indicator Code", *YEARS, ""],
    ]
    for country, values in series.items():
        rows.append(
            [country, country[:3].upper(), name, code]
            + [str(values.get(y, "")) for y in YEARS]
            + [""]
        )
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    if not zipped:
        path = tmp_path / f"API_{code}.csv"
        path.write_text(buf.getvalue(), encoding="utf-8")
        return path
    path = tmp_path / f"API_{code}_DS2_en_csv_v2_1.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"API_{code}_DS2_en_csv_v2_1.csv", buf.getvalue())
        zf.writestr(f"Metadata_Country_API_{code}.csv", "a,b\n1,2\n")
    return path


def ons_csv(tmp_path: Path, title: str, annual: dict) -> Path:
    rows = [["Title", title], ["CDID", "L55O"], ["Unit", "%"], ["Important notes", ""]]
    rows += [[y, str(v)] for y, v in annual.items()]
    rows += [[f"{y} Q1", "99.9"] for y in annual]
    rows += [[f"{y} JAN", "88.8"] for y in annual]
    path = tmp_path / "series-l55o.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    return path


def test_world_bank_zip_becomes_one_row_per_year(tmp_path):
    path = world_bank_csv(
        tmp_path,
        "NY.GDP.MKTP.KD.ZG",
        "GDP growth (annual %)",
        {"United Kingdom": {y: 1.5 for y in YEARS}, "India": {y: 7.0 for y in YEARS}},
    )
    rows = tidy.build([path], "United Kingdom", None, None, [1])
    assert rows[0] == ["Year", "GDP growth (annual %)"]
    assert [r[0] for r in rows[1:]] == YEARS
    assert {r[1] for r in rows[1:]} == {"1.5"}


def test_plain_csv_is_accepted_too(tmp_path):
    path = world_bank_csv(
        tmp_path, "X", "GDP growth (annual %)", {"United Kingdom": {y: 2 for y in YEARS}},
        zipped=False,
    )
    rows = tidy.build([path], "United Kingdom", None, None, [1])
    assert len(rows) == len(YEARS) + 1


def test_wrong_country_is_refused_and_names_what_is_there(tmp_path):
    path = world_bank_csv(tmp_path, "X", "GDP growth", {"India": {y: 7 for y in YEARS}})
    with pytest.raises(tidy.TidyError) as exc:
        tidy.build([path], "United Kingdom", None, None, [1])
    assert "India" in str(exc.value)


def test_two_indicators_join_on_the_year(tmp_path):
    a = world_bank_csv(tmp_path, "A", "GDP growth", {"United Kingdom": {y: 1 for y in YEARS}})
    b = world_bank_csv(tmp_path, "B", "Unemployment", {"United Kingdom": {y: 4 for y in YEARS}})
    rows = tidy.build([a, b], "United Kingdom", 2018, 2021, [1])
    assert rows[0] == ["Year", "GDP growth", "Unemployment"]
    assert [r[0] for r in rows[1:]] == ["2018", "2019", "2020", "2021"]


def test_a_year_missing_from_one_indicator_is_dropped_not_left_blank(tmp_path):
    full = {y: 1 for y in YEARS}
    holed = {y: 4 for y in YEARS if y != "2020"}
    a = world_bank_csv(tmp_path, "A", "GDP growth", {"United Kingdom": full})
    b = world_bank_csv(tmp_path, "B", "Unemployment", {"United Kingdom": holed})
    rows = tidy.build([a, b], "United Kingdom", None, None, [1])
    years = [r[0] for r in rows[1:]]
    assert "2020" not in years
    assert all(len(r) == 3 and all(c for c in r) for r in rows)


def test_ons_reads_annual_rows_only(tmp_path):
    path = ons_csv(tmp_path, "CPIH ANNUAL RATE 00: ALL ITEMS", {"2021": 2.5, "2022": 7.9})
    rows = tidy.build([path], "United Kingdom", None, None, [1])
    assert rows == [
        ["Year", "CPIH ANNUAL RATE 00: ALL ITEMS"],
        ["2021", "2.5"],
        ["2022", "7.9"],
    ]
    # the quarterly and monthly rows carried 99.9 and 88.8
    assert "99.9" not in {c for r in rows for c in r}
    assert "88.8" not in {c for r in rows for c in r}


def test_ons_and_world_bank_can_be_joined(tmp_path):
    wb = world_bank_csv(
        tmp_path, "A", "GDP growth", {"United Kingdom": {y: 1 for y in YEARS}}
    )
    ons = ons_csv(tmp_path, "CPIH ANNUAL RATE", {"2018": 2.3, "2019": 1.7})
    rows = tidy.build([wb, ons], "United Kingdom", None, None, [1])
    assert [r[0] for r in rows[1:]] == ["2018", "2019"]


def test_labels_must_match_the_number_of_files(tmp_path):
    path = world_bank_csv(tmp_path, "A", "GDP growth", {"United Kingdom": {y: 1 for y in YEARS}})
    with pytest.raises(tidy.TidyError):
        tidy.build([path], "United Kingdom", None, None, [1], labels=["one", "two"])


def test_labels_replace_the_portal_wording(tmp_path):
    path = world_bank_csv(
        tmp_path,
        "A",
        "Unemployment, total (% of total labor force) (modeled ILO estimate)",
        {"United Kingdom": {y: 4 for y in YEARS}},
    )
    rows = tidy.build([path], "United Kingdom", None, None, [1], labels=["Unemployment (%)"])
    assert rows[0] == ["Year", "Unemployment (%)"]


def test_round_may_differ_per_column(tmp_path):
    """A single precision for every column destroys an exchange rate sitting
    beside a percentage — 0.782 becomes 0.8."""
    fx = world_bank_csv(
        tmp_path, "A", "Exchange rate", {"United Kingdom": {y: 0.7823 for y in YEARS}}
    )
    ca = world_bank_csv(
        tmp_path, "B", "Current account", {"United Kingdom": {y: -3.0491 for y in YEARS}}
    )
    rows = tidy.build([fx, ca], "United Kingdom", 2020, 2021, [3, 1])
    assert rows[1][1:] == ["0.782", "-3.0"]


def test_one_round_value_applies_to_every_column(tmp_path):
    a = world_bank_csv(tmp_path, "A", "One", {"United Kingdom": {y: 1.234 for y in YEARS}})
    b = world_bank_csv(tmp_path, "B", "Two", {"United Kingdom": {y: 5.678 for y in YEARS}})
    rows = tidy.build([a, b], "United Kingdom", 2020, 2021, [2])
    assert rows[1][1:] == ["1.23", "5.68"]


def test_round_list_must_match_the_number_of_files(tmp_path):
    path = world_bank_csv(tmp_path, "A", "One", {"United Kingdom": {y: 1 for y in YEARS}})
    with pytest.raises(tidy.TidyError):
        tidy.build([path], "United Kingdom", None, None, [1, 2])


def test_minus_one_leaves_the_figures_untouched(tmp_path):
    path = world_bank_csv(
        tmp_path, "A", "One", {"United Kingdom": {y: "1.23456789" for y in YEARS}}
    )
    rows = tidy.build([path], "United Kingdom", 2020, 2021, [None])
    assert rows[1][1] == "1.23456789"


def test_one_year_is_refused_rather_than_written(tmp_path):
    path = world_bank_csv(tmp_path, "A", "GDP growth", {"United Kingdom": {"2020": 1}})
    with pytest.raises(tidy.TidyError):
        tidy.build([path], "United Kingdom", None, None, [1])


def test_a_file_from_neither_portal_is_refused(tmp_path):
    path = tmp_path / "random.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    with pytest.raises(tidy.TidyError) as exc:
        tidy.build([path], "United Kingdom", None, None, [1])
    assert "Country Name" in str(exc.value)


def test_output_loads_through_the_real_dataset_loader(tmp_path):
    """The whole point of the script: what comes out must go in."""
    import json

    from src.reference.dataset import load_dataset

    a = world_bank_csv(tmp_path, "A", "GDP growth", {"United Kingdom": {y: 1.5 for y in YEARS}})
    rows = tidy.build([a], "United Kingdom", 2018, 2023, [1])

    slug = "unit-test-uk"
    root = tmp_path / "datasets" / slug
    root.mkdir(parents=True)
    with (root / "data.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "slug": slug,
                "title": "Real GDP growth, United Kingdom",
                "source": "world_bank",
                "url": "https://data.worldbank.org/indicator/NY.GDP.MKTP.KD.ZG?locations=GB",
                "licence": "CC BY 4.0",
                "accessed_on": "2026-08-07",
            }
        ),
        encoding="utf-8",
    )

    dataset = load_dataset(slug, datasets_dir=tmp_path / "datasets")
    assert dataset.headers[0] == "Year"
    assert len(dataset.rows) == 6
