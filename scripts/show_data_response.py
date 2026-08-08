#!/usr/bin/env python3
"""Print a banked Section A data response exactly as it was stored.

    python scripts/show_data_response.py              # the most recent one
    python scripts/show_data_response.py --list       # all of them
    python scripts/show_data_response.py --group <id>
    python scripts/show_data_response.py --marks      # include the mark points

There is no screen that shows a data response outside a running mock, so
without this the only way to look at what was generated is to sit the mock
and spend the marking tokens. This reads the database and nothing else: no
model call, no network.

`--marks` prints the generated mark points too. Leave it off if you intend
to attempt the question yourself.
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.marking.points_marker import PointsPart  # noqa: E402
from src.store.db import Store  # noqa: E402

WIDTH = 88


def wrap(text: str, indent: str = "") -> str:
    return "\n".join(
        textwrap.fill(line, WIDTH, initial_indent=indent, subsequent_indent=indent)
        if line.strip()
        else ""
        for line in str(text).splitlines()
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--group", help="group_id to print (default: most recent)")
    ap.add_argument("--list", action="store_true", help="list banked data responses")
    ap.add_argument("--marks", action="store_true", help="also print the mark points")
    args = ap.parse_args()

    store = Store(settings.db_path)
    if not store.is_initialised():
        print("No database yet — nothing has been banked.")
        return 1

    groups = store.data_response_groups(exclude_answered=False)
    if not groups:
        print("No data responses banked. Run scripts/bank_data_response.py first.")
        return 1

    if args.list:
        print(f"{len(groups)} banked data response(s):\n")
        for g in groups:
            print(f"  {g['group_id']}   topic {g['topic_code']}   "
                  f"{g['parts']} parts   {g['marks']} marks   {g['created_at']}")
        return 0

    group_id = args.group or groups[0]["group_id"]
    parts = store.data_response_parts(group_id)
    if not parts:
        print(f"No parts found for group {group_id!r}. Try --list.")
        return 1

    stimulus = store.data_response_stimulus(group_id) or {}

    print("=" * WIDTH)
    print(f"Section A data response — group {group_id}")
    print(f"topic {parts[0]['topic_code']}   {sum(p['max_marks'] for p in parts)} marks   "
          f"{len(parts)} parts")
    print("=" * WIDTH)

    if stimulus.get("title"):
        print(f"\n{stimulus['title']}\n")
    if stimulus.get("extract"):
        print(wrap(stimulus["extract"]))
    if stimulus.get("table_caption"):
        print(f"\n{stimulus['table_caption']}")

    headers = stimulus.get("table_headers") or []
    rows = stimulus.get("table_rows") or []
    if headers and rows:
        widths = [
            max(len(str(headers[i])), *(len(str(r[i])) for r in rows))
            for i in range(len(headers))
        ]
        print()
        print("  " + "  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)))
        for row in rows:
            print("  " + "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))

    if stimulus.get("attribution"):
        print(f"\n{stimulus['attribution']}")

    print("\n" + "-" * WIDTH)
    # Decoded through the marker's own PointsPart so this can never drift from
    # what the mock screen shows: the wording is JSON inside the body column,
    # not the column itself.
    for part in (PointsPart.from_row(row) for row in parts):
        print(f"\n{part.label}  [{part.max_marks}]")
        print(wrap(part.prompt, indent="      "))
        if args.marks:
            for point in part.points:
                print(
                    wrap(
                        f"- ({point.get('band', '?')}) {point.get('text', '')}",
                        indent="      ",
                    )
                )

    print("\n" + "-" * WIDTH)
    print("Every figure in the prose above should appear in the table. That is the "
          "one guard the design leans on, so it is worth reading for.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
