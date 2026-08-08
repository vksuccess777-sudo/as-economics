#!/usr/bin/env python3
"""Quick summary of everything banked in Paper 2 Section A so far.

    python scripts\\summary_data_response.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.store.db import Store  # noqa: E402


def main() -> int:
    if not settings.db_path.exists():
        print("No store yet.")
        return 1

    store = Store(settings.db_path)
    groups = store.data_response_groups(exclude_answered=False)

    if not groups:
        print("No data response groups banked yet.")
        return 0

    by_topic: dict[str, list[dict]] = {}
    for g in groups:
        by_topic.setdefault(g["topic_code"], []).append(g)

    for topic, gs in sorted(by_topic.items()):
        print(f"{topic}: {len(gs)} group(s)")
        for g in sorted(gs, key=lambda x: x["created_at"]):
            print(f"   {g['group_id']}  {g['created_at']}")

    print(f"\nTotal: {len(groups)} data response groups banked across {len(by_topic)} topic(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
