#!/usr/bin/env python3
"""Register a CSV you downloaded as a usable dataset.

    python scripts/add_dataset.py path/to/downloaded.csv \
        --slug vietnam-trade-growth \
        --title "Balance of trade and real GDP growth, Viet Nam" \
        --source world_bank \
        --url https://data.worldbank.org/... \
        --region "Viet Nam" --units "% of GDP; annual %"

It copies the file to data/reference/datasets/<slug>/data.csv and writes the
manifest beside it: which registered source, the exact page, the licence, and
today's date. Nothing can be used as stimulus material without that manifest,
so this script is the only door in.

The licence is taken from the registry entry for the source, not typed by
hand — a licence typed at 11pm is a licence that ends up wrong. Use
--licence only when the specific page differs from the source default (the
OECD case: CC BY 4.0 only from 1 July 2024, older material is 'OECD Terms').

No network, no tokens.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.reference.dataset import DEFAULT_DATASETS_DIR, load_dataset  # noqa: E402
from src.reference.registry import (  # noqa: E402
    OPEN_DATA_LICENCES,
    RegistryError,
    load_registry,
)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", type=Path, help="the file you downloaded")
    ap.add_argument("--slug", required=True, help="folder name, e.g. uk-cpi-2015-2024")
    ap.add_argument("--title", required=True, help="what the table shows")
    ap.add_argument("--source", required=True, help="source id from data/reference/manifest.json")
    ap.add_argument("--url", required=True, help="the exact page you downloaded it from")
    ap.add_argument("--licence", default=None, help="override the source default")
    ap.add_argument("--region", default=None)
    ap.add_argument("--units", default=None)
    ap.add_argument("--notes", default=None, help="anything a reader of the table needs")
    ap.add_argument("--accessed-on", default=date.today().isoformat())
    ap.add_argument("--force", action="store_true", help="overwrite an existing slug")
    args = ap.parse_args()

    try:
        registry = load_registry()
        source = registry.require_data_source(args.source)
    except RegistryError as exc:
        print(f"REFUSED: {exc}")
        print("\nSources that may supply data:")
        for s in load_registry().data_sources():
            print(f"  {s.id:<20} {s.name} ({s.licence})")
        return 2

    licence = args.licence or source.licence
    if licence not in OPEN_DATA_LICENCES:
        print(f"REFUSED: licence {licence!r} is not in the allow-list.")
        return 2

    if not args.csv.exists():
        print(f"REFUSED: {args.csv} does not exist")
        return 2

    target = Path(DEFAULT_DATASETS_DIR) / args.slug
    if target.exists() and not args.force:
        print(f"REFUSED: {target} already exists (use --force to replace)")
        return 2
    target.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(args.csv, target / "data.csv")
    manifest = {
        "slug": args.slug,
        "title": args.title,
        "source": source.id,
        "url": args.url,
        "licence": licence,
        "accessed_on": args.accessed_on,
        "region": args.region,
        "units": args.units,
        "notes": args.notes,
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    try:
        dataset = load_dataset(args.slug)
    except Exception as exc:  # noqa: BLE001 - report anything and leave it visible
        print(f"WRITTEN, BUT IT DOES NOT LOAD: {exc}")
        print(f"Fix {target}/data.csv — a Section A table wants one header row, ")
        print("a year or period column, and one or two indicator columns.")
        return 1

    print(f"OK  {args.slug}")
    print(f"    {len(dataset.rows)} rows x {len(dataset.headers)} columns")
    print(f"    columns: {', '.join(dataset.headers)}")
    print(f"    {dataset.attribution()}")
    print()
    print(dataset.table(max_rows=6).as_text())
    if source.caution:
        print()
        print(f"CAUTION ({source.name}): {source.caution}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
