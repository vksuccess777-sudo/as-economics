#!/usr/bin/env python3
"""Turn a World Bank or ONS download into the shape add_dataset.py accepts.

Neither portal gives you a CSV the dataset loader can read.

  World Bank: a zip holding one WIDE csv — four metadata lines, then
  Country Name / Country Code / Indicator Name / Indicator Code and one
  column per year. DataBank exports ("1990 [YR1990]" headers) too.

  ONS time series: eight lines of Title/CDID/Unit preamble above the
  period,value rows, then annual, quarterly and monthly periods stacked
  in the same column.

The loader wants one header row and one row per year, so this reshapes
both into that and joins several indicators on the year:

    python scripts/tidy_reference_csv.py --country "United Kingdom" \
        --from 2014 --to 2023 --out uk-growth.csv \
        --labels "GDP growth (%),Unemployment (% of labour force)" \
        API_NY.GDP.MKTP.KD.ZG_DS2_en_csv_v2_1234.zip \
        API_SL.UEM.TOTL.ZS_DS2_en_csv_v2_5678.zip

--country is ignored for ONS files, which hold one series for the UK.
--round takes one value for every column, or one per file when they need
different precision: --round 3,1 keeps an exchange rate readable beside a
percentage.

Nothing here touches the network and nothing is written to
data/reference/ — the output is a plain CSV you then hand to
add_dataset.py, which is still the only door in.
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import zipfile
from pathlib import Path

YEAR = re.compile(r"^(\d{4})(?:\s*\[YR\d{4}\])?$")
BLANK = {"", "..", "n/a", "na", ".."}
COUNTRY_KEYS = ("Country Name", "Country")
SERIES_KEYS = ("Indicator Name", "Series Name")


class TidyError(ValueError):
    """The file is not a World Bank export, or holds nothing usable."""


def read_rows(path: Path) -> list[list[str]]:
    """Rows of the CSV, whether it arrived as a .csv or inside the .zip."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [
                n
                for n in zf.namelist()
                if n.lower().endswith(".csv") and not n.startswith("Metadata")
            ]
            if not names:
                raise TidyError(f"{path.name} contains no data CSV")
            # The API_<CODE>_... file is the data; Metadata_* files are not.
            names.sort(key=lambda n: (not n.startswith("API_"), len(n)))
            text = zf.read(names[0]).decode("utf-8-sig")
    else:
        text = path.read_text(encoding="utf-8-sig")
    return list(csv.reader(io.StringIO(text)))


def is_ons(rows: list[list[str]]) -> bool:
    """ONS time-series exports open with a Title line and carry no country
    column at all."""
    for row in rows[:12]:
        if row and row[0].strip().casefold() in {"title", "cdid"}:
            return True
    return False


ONS_YEAR = re.compile(r"^(\d{4})$")


def extract_ons(path: Path) -> tuple[str, dict[str, str]]:
    """ONS files stack annual, quarterly ('2014 Q1') and monthly ('2014 JAN')
    periods in one column. Only the bare-year rows are annual, and taking a
    monthly row as if it were the year would silently misreport the figure."""
    rows = read_rows(path)
    label = path.stem
    for row in rows[:12]:
        if row and row[0].strip().casefold() == "title" and len(row) > 1 and row[1].strip():
            label = row[1].strip()
            break

    values: dict[str, str] = {}
    for row in rows:
        if len(row) < 2:
            continue
        period, cell = row[0].strip(), row[1].strip()
        if ONS_YEAR.match(period) and cell.casefold() not in BLANK:
            values[period] = cell
    if len(values) < 2:
        raise TidyError(
            f"{path.name}: fewer than two annual rows. On the ONS page choose "
            "the yearly filter before downloading, or download the full series."
        )
    return label, values


def find_header(rows: list[list[str]]) -> int:
    """World Bank puts four lines of preamble above the real header, and the
    count has changed before now, so look for the header rather than skip a
    fixed number of lines."""
    for i, row in enumerate(rows):
        if any(cell.strip() in COUNTRY_KEYS for cell in row):
            return i
    raise TidyError(
        "no header row containing 'Country Name' — this does not look like a "
        "World Bank or DataBank export"
    )


def extract(path: Path, country: str) -> tuple[str, dict[str, str]]:
    """(label, {year: value}) for one indicator, for one country."""
    rows = read_rows(path)
    if is_ons(rows):
        return extract_ons(path)
    start = find_header(rows)
    header = [cell.strip() for cell in rows[start]]

    def column(keys: tuple[str, ...]) -> int | None:
        for key in keys:
            if key in header:
                return header.index(key)
        return None

    country_at = column(COUNTRY_KEYS)
    series_at = column(SERIES_KEYS)
    if country_at is None:
        raise TidyError(f"{path.name}: no country column")

    years = {i: m.group(1) for i, c in enumerate(header) if (m := YEAR.match(c))}
    if not years:
        raise TidyError(
            f"{path.name}: no year columns found. If you exported from DataBank, "
            "choose the layout with years across the top."
        )

    wanted = country.strip().casefold()
    seen: list[str] = []
    for row in rows[start + 1 :]:
        if len(row) <= country_at:
            continue
        name = row[country_at].strip()
        if not name:
            continue
        seen.append(name)
        if name.casefold() != wanted:
            continue
        label = (
            row[series_at].strip()
            if series_at is not None and len(row) > series_at and row[series_at].strip()
            else path.stem
        )
        values = {}
        for i, year in years.items():
            if i < len(row):
                cell = row[i].strip()
                if cell.casefold() not in BLANK:
                    values[year] = cell
        if not values:
            raise TidyError(f"{path.name}: {name} has no values in any year")
        return label, values

    raise TidyError(
        f"{path.name}: no row for {country!r}. Names in this file include: "
        + ", ".join(sorted(set(seen))[:8])
    )


def shorten(label: str) -> str:
    """'GDP growth (annual %)' -> 'GDP growth (annual %)' but drop the trailing
    country qualifier some exports add. Kept deliberately light: the column
    heading is what the student reads in the exam table."""
    return label.split(" [")[0].strip()


def build(
    paths: list[Path],
    country: str,
    first: int | None,
    last: int | None,
    places: list[int | None],
    labels: list[str] | None = None,
) -> list[list[str]]:
    if len(places) == 1:
        places = places * len(paths)
    if len(places) != len(paths):
        raise TidyError(
            f"--round has {len(places)} values for {len(paths)} files. Give one "
            "value for all columns, or one per file in the same order."
        )
    if labels and len(labels) != len(paths):
        raise TidyError(
            f"--labels has {len(labels)} names for {len(paths)} files. A column "
            "heading is what the student reads in the exam table, so a "
            "mismatch is never guessed at."
        )
    columns: list[tuple[str, dict[str, str]]] = []
    for i, path in enumerate(paths):
        label, values = extract(path, country)
        columns.append((labels[i].strip() if labels else shorten(label), values))

    years = sorted({y for _, v in columns for y in v})
    if first is not None:
        years = [y for y in years if int(y) >= first]
    if last is not None:
        years = [y for y in years if int(y) <= last]
    # A year missing from any indicator would make a row the reader cannot
    # compare across, so drop it rather than print a gap.
    years = [y for y in years if all(y in v for _, v in columns)]
    if len(years) < 2:
        raise TidyError(
            "fewer than two years are present in every indicator. Widen "
            "--from/--to, or register the indicators as separate datasets."
        )

    def fmt(cell: str, dp: int | None) -> str:
        if dp is None:
            return cell
        try:
            return f"{float(cell.replace(',', '')):.{dp}f}"
        except ValueError:
            return cell

    out = [["Year", *(label for label, _ in columns)]]
    for year in years:
        out.append(
            [year, *(fmt(values[year], places[i]) for i, (_, values) in enumerate(columns))]
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", type=Path, help="one .zip or .csv per indicator")
    ap.add_argument(
        "--country",
        default="United Kingdom",
        help="exactly as the file spells it (ignored for ONS files)",
    )
    ap.add_argument(
        "--labels",
        default=None,
        help="comma-separated column headings, one per file, in the same order",
    )
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--from", dest="first", type=int, default=None)
    ap.add_argument("--to", dest="last", type=int, default=None)
    ap.add_argument(
        "--round",
        dest="places",
        default="1",
        help=(
            "decimal places: one value for every column, or a comma-separated "
            "value per file when they need different precision "
            "(an exchange rate near 0.78 is destroyed by 1 dp). "
            "Use -1 to leave a column's figures exactly as downloaded."
        ),
    )
    args = ap.parse_args()

    try:
        places = [
            None if int(p) < 0 else int(p)
            for p in str(args.places).split(",")
            if p.strip()
        ]
    except ValueError:
        print(f"REFUSED: --round {args.places!r} is not a number or list of numbers")
        return 2
    if not places:
        print("REFUSED: --round needs at least one value")
        return 2

    labels = [p for p in args.labels.split(",")] if args.labels else None

    try:
        rows = build(args.files, args.country, args.first, args.last, places, labels)
    except (TidyError, OSError, zipfile.BadZipFile) as exc:
        print(f"REFUSED: {exc}")
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows(rows)

    print(f"wrote {args.out}  ({len(rows) - 1} rows x {len(rows[0])} columns)")
    print()
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))
    print()
    print("Check the figures against the page you downloaded from, then register it:")
    print(f"  python scripts/add_dataset.py {args.out} --slug <slug> --title ... "
          "--source <world_bank|ons|...> --url <the exact page it came from>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
