#!/usr/bin/env python3
"""Fill the question bank. Run this in batches; the app never generates live.

    python scripts/bank_questions.py --topic 4.3 --count 5
    python scripts/bank_questions.py --all --per-topic 3
    python scripts/bank_questions.py --thin 5        # top up topics below 5

Generation is the only part of this system that spends tokens, so it is kept
deliberately manual and batched. A run that hits the rate limit stops cleanly
and tells you how long to wait; already-banked questions are unaffected.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.llm.exceptions import AllProvidersRateLimitedError, LLMRateLimitError  # noqa: E402
from src.llm.provider import build_provider  # noqa: E402
from src.questions.mcq_generator import MCQGenerator  # noqa: E402
from src.store.db import Store  # noqa: E402
from src.syllabus.models import SyllabusSpine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", help="a single topic code, e.g. 4.3")
    ap.add_argument("--all", action="store_true", help="every topic in the spine")
    ap.add_argument("--thin", type=int, metavar="N",
                    help="top up every topic holding fewer than N questions")
    ap.add_argument("--count", type=int, default=5, help="questions per topic")
    ap.add_argument("--per-topic", type=int, dest="per_topic",
                    help="alias for --count when using --all")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be generated, spend no tokens")
    args = ap.parse_args()

    if not settings.spine_path.exists():
        print("ERROR: no syllabus spine — run scripts/build_syllabus_spine.py first",
              file=sys.stderr)
        return 2
    spine = SyllabusSpine.load(settings.spine_path)

    store = Store(settings.db_path)
    if not store.is_initialised():
        store.initialise()

    per_topic = args.per_topic or args.count
    existing = store.bank_counts_by_topic()

    if args.topic:
        targets = [(args.topic, per_topic)]
    elif args.thin is not None:
        targets = [
            (t.code, args.thin - existing.get(t.code, 0))
            for t in spine.iter_topics()
            if existing.get(t.code, 0) < args.thin
        ]
    elif args.all:
        targets = [(t.code, per_topic) for t in spine.iter_topics()]
    else:
        ap.error("choose one of --topic, --all or --thin")
        return 2

    if not targets:
        print("Nothing to do — every topic already meets the threshold.")
        return 0

    print(f"{len(targets)} topic(s) to generate, "
          f"{sum(n for _, n in targets)} question(s) total\n")
    if args.dry_run:
        for code, n in targets:
            topic = spine.topic(code)
            label = topic.title if topic else "UNKNOWN TOPIC"
            print(f"  {code:<5} {label}  -> {n} (bank has {existing.get(code, 0)})")
        print("\nDry run — no tokens spent.")
        return 0

    try:
        provider = build_provider(settings)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    generator = MCQGenerator(provider, store, spine, seed=args.seed)

    total_banked = 0
    total_rejected = 0
    for code, n in targets:
        topic = spine.topic(code)
        if topic is None:
            print(f"  {code:<5} SKIPPED — not in the spine")
            continue
        try:
            report = generator.generate_for_topic(code, count=n)
        except LLMRateLimitError as exc:
            print(f"\nRate limit reached on {exc.provider}. "
                  f"Try again in about {exc.friendly_wait()}.")
            print(f"Banked {total_banked} question(s) before stopping — "
                  "they are saved, just re-run when the limit resets.")
            return 1
        except AllProvidersRateLimitedError as exc:
            print(f"\nEvery configured provider is rate-limited: {exc}")
            print(f"Banked {total_banked} question(s) before stopping — "
                  "they are saved, just re-run once a provider frees up.")
            return 1
        except Exception as exc:  # noqa: BLE001 - one bad topic must not kill the batch
            print(f"  {code:<5} FAILED — {type(exc).__name__}: {exc}")
            continue

        total_banked += report.banked
        total_rejected += len(report.rejected)
        print(f"  {code:<5} {topic.title[:44]:<44} {report.summary()}")
        for preview, reason in report.rejected:
            print(f"          rejected: {reason}  |  {preview}...")

    print(f"\nBanked {total_banked}, rejected {total_rejected}.")
    if total_rejected and total_banked:
        rate = total_rejected / (total_banked + total_rejected)
        if rate > 0.3:
            print(f"! rejection rate {rate:.0%} is high — the prompt may need work")

    counts = store.bank_counts_by_topic()
    thin = [t.code for t in spine.iter_topics() if counts.get(t.code, 0) < 3]
    if thin:
        print(f"\nTopics with fewer than 3 questions: {', '.join(thin)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
