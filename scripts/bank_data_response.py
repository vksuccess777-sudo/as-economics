#!/usr/bin/env python3
"""Bank Paper 2 Section A data responses. Batch only — never in the app.

    python scripts/bank_data_response.py --list
    python scripts/bank_data_response.py --dataset uk-cpi-2015-2024 --topic 5.1
    python scripts/bank_data_response.py --dataset vietnam-trade --topic 6.2 \
        --shape june_2024 --columns Year,Exports,GDP_growth --count 2
    python scripts/bank_data_response.py --dataset x --topic 4.1 --dry-run

Each data response banks as six question rows sharing a group id, twenty
marks in total. The table comes from the dataset; the model writes only the
prose around it, and any figure it invents gets the whole item rejected.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.llm.exceptions import AllProvidersRateLimitedError, LLMRateLimitError  # noqa: E402
from src.llm.provider import build_provider  # noqa: E402
from src.questions.data_response import (  # noqa: E402
    SHAPES,
    SHAPES_BY_NAME,
    DataResponseGenerator,
    build_prompt,
    syllabus_acronyms,
)
from src.reference.dataset import DatasetError, available_datasets, load_dataset  # noqa: E402
from src.store.db import Store  # noqa: E402
from src.syllabus.models import SyllabusSpine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset", help="slug under data/reference/datasets/")
    ap.add_argument("--topic", help="topic code the question is anchored to")
    ap.add_argument("--shape", default="specimen_2023",
                    choices=sorted(SHAPES_BY_NAME), help="which observed part structure")
    ap.add_argument("--columns", help="comma-separated columns to put in the table")
    ap.add_argument("--rows", type=int, default=9, help="most recent N rows")
    ap.add_argument("--count", type=int, default=1)
    ap.add_argument("--list", action="store_true", help="show datasets and shapes")
    ap.add_argument("--dry-run", action="store_true", help="print the prompt, spend nothing")
    args = ap.parse_args()

    if not settings.spine_path.exists():
        print("No syllabus spine. Run scripts/build_syllabus_spine.py first.")
        return 1
    spine = SyllabusSpine.load(settings.spine_path)

    if args.list or not (args.dataset and args.topic):
        slugs = available_datasets()
        print("Datasets that load cleanly:")
        if not slugs:
            print("  (none yet — add one with scripts/add_dataset.py)")
        for slug in slugs:
            ds = load_dataset(slug)
            print(f"  {slug:<28} {ds.title}")
            print(f"  {'':<28} {ds.short_attribution()}  columns: {', '.join(ds.headers)}")
        print("\nShapes:")
        for shape in SHAPES:
            parts = ", ".join(f"{p.label} {p.marks}" for p in shape.parts)
            print(f"  {shape.name:<16} {parts}   [{shape.source}]")
        return 0 if args.list else 2

    try:
        dataset = load_dataset(args.dataset)
    except DatasetError as exc:
        print(f"REFUSED: {exc}")
        return 2

    topic = spine.topic(args.topic)
    if topic is None:
        print(f"Topic {args.topic!r} is not in the spine.")
        return 2

    shape = SHAPES_BY_NAME[args.shape]
    columns = [c.strip() for c in args.columns.split(",")] if args.columns else None
    try:
        table = dataset.table(columns=columns, max_rows=args.rows)
    except DatasetError as exc:
        print(f"REFUSED: {exc}")
        return 2

    print(f"{dataset.title}  [{dataset.short_attribution()}]")
    print(table.as_text())
    print()

    if args.dry_run:
        print("--- prompt ---")
        print(build_prompt(
            topic, dataset, table, shape,
            allowed_acronyms=syllabus_acronyms(spine),
        ))
        return 0

    store = Store(settings.db_path)
    if not store.is_initialised():
        store.initialise()

    generator = DataResponseGenerator(build_provider(settings), store, spine)
    try:
        report = generator.generate(
            topic.code, dataset, shape=shape, columns=columns,
            max_rows=args.rows, count=args.count,
        )
    except (AllProvidersRateLimitedError, LLMRateLimitError) as exc:
        print(f"Stopped: {exc}")
        return 1

    print(report.summary())
    for code, reason in report.rejected:
        print(f"  rejected {code}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
