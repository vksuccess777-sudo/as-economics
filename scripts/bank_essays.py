#!/usr/bin/env python3
"""Fill the Paper 2 essay bank. Batch only — the app never generates live.

    python scripts/bank_essays.py --topic 4.3 --count 2
    python scripts/bank_essays.py --all --per-topic 1
    python scripts/bank_essays.py --thin 1        # top up topics with no essay
    python scripts/bank_essays.py --all --dry-run # spend nothing, see the plan

Each essay banks as two rows: part (a) 8 marks and part (b) 12 marks, sharing a
group id. Essays cost more tokens per item than MCQs, so start with --thin 1 to
get one essay per topic before deepening anywhere.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.llm.exceptions import AllProvidersRateLimitedError, LLMRateLimitError  # noqa: E402
from src.llm.provider import build_provider  # noqa: E402
from src.questions.essay_generator import EssayGenerator  # noqa: E402
from src.store.db import Store  # noqa: E402
from src.syllabus.models import SyllabusSpine  # noqa: E402


def essays_per_topic(store: Store) -> dict[str, int]:
    groups = store.essay_groups(exclude_answered=False)
    counts: dict[str, int] = {}
    for g in groups:
        counts[g["topic_code"]] = counts.get(g["topic_code"], 0) + 1
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", help="a single topic code, e.g. 4.3")
    ap.add_argument("--all", action="store_true", help="every topic in the spine")
    ap.add_argument("--thin", type=int, metavar="N",
                    help="top up every topic holding fewer than N essays")
    ap.add_argument("--count", type=int, default=1, help="essays per topic")
    ap.add_argument("--per-topic", type=int, dest="per_topic",
                    help="alias for --count when using --all")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the plan, spend no tokens")
    args = ap.parse_args()

    if not settings.spine_path.exists():
        print("No syllabus spine. Run scripts/build_syllabus_spine.py first.")
        return 1

    spine = SyllabusSpine.load(settings.spine_path)
    store = Store(settings.db_path)
    if not store.is_initialised():
        store.initialise()

    count = args.per_topic or args.count
    existing = essays_per_topic(store)

    if args.topic:
        plan = [(args.topic, count)]
    elif args.thin is not None:
        plan = [
            (code, args.thin - existing.get(code, 0))
            for code in spine.topic_codes
            if existing.get(code, 0) < args.thin
        ]
    elif args.all:
        plan = [(code, count) for code in spine.topic_codes]
    else:
        ap.print_help()
        return 1

    plan = [(code, n) for code, n in plan if n > 0]
    total = sum(n for _, n in plan)
    print(f"Plan: {len(plan)} topic(s), {total} essay(s) = {total * 2} question rows.")
    for code, n in plan:
        print(f"  {code}: {n} (bank holds {existing.get(code, 0)})")

    if args.dry_run:
        print("\nDry run — nothing generated, no tokens spent.")
        return 0

    try:
        provider = build_provider(settings)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    generator = EssayGenerator(provider, store, spine)

    banked = 0
    rejected: list[tuple[str, str]] = []
    for code, n in plan:
        try:
            report = generator.generate_for_topic(code, count=n)
        except LLMRateLimitError as exc:
            print(f"\nRate limited on {code}: wait {exc.friendly_wait()}.")
            print(f"Kept everything banked so far ({banked} essays).")
            break
        except AllProvidersRateLimitedError as exc:
            print(f"\nEvery configured provider is rate-limited: {exc}")
            print(f"Kept everything banked so far ({banked} essays).")
            break
        except ValueError as exc:
            print(f"  {code}: {exc}")
            continue
        banked += report.banked
        rejected.extend(report.rejected)
        print(f"  {code}: {report.summary()}")

    print(f"\nBanked {banked} essay(s).")
    if rejected:
        print(f"Rejected {len(rejected)}:")
        for code, reason in rejected:
            print(f"  {code}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
