#!/usr/bin/env python3
"""Delete banked Paper 2 Section A data response groups by group id.

Refuses to touch any group that already has a response recorded against
it, so a student's practice history can never be silently wiped.

    python scripts\\prune_data_response.py --group-id dr_xxx --group-id dr_yyy
    python scripts\\prune_data_response.py --group-id dr_xxx --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.store.db import Store  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--group-id", action="append", required=True, dest="group_ids",
                     help="repeatable; group id(s) to delete")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not settings.db_path.exists():
        print("No store yet.")
        return 1

    store = Store(settings.db_path)
    with store.connect() as conn:
        for gid in args.group_ids:
            answered = conn.execute(
                "SELECT COUNT(*) FROM response r "
                "JOIN question q ON q.id = r.question_id "
                "WHERE json_extract(q.rubric, '$.group_id') = ? "
                "AND r.awarded IS NOT NULL",
                (gid,),
            ).fetchone()[0]
            if answered:
                print(f"SKIP {gid}: has {answered} answered response(s), not deleting.")
                continue

            ids = [
                r[0] for r in conn.execute(
                    "SELECT id FROM question WHERE json_extract(rubric, '$.group_id') = ?",
                    (gid,),
                ).fetchall()
            ]
            if not ids:
                print(f"SKIP {gid}: not found.")
                continue

            if args.dry_run:
                print(f"WOULD DELETE {gid}: {len(ids)} question row(s)")
                continue

            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM response WHERE question_id IN ({placeholders})", ids)
            conn.execute(f"DELETE FROM question WHERE id IN ({placeholders})", ids)
            conn.commit()
            print(f"DELETED {gid}: {len(ids)} question row(s)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
