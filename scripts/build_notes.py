#!/usr/bin/env python3
"""Write the knowledge base: one revision note per syllabus topic.

    python scripts/build_notes.py --all
    python scripts/build_notes.py --topic 4.3
    python scripts/build_notes.py --missing        # only topics with no note
    python scripts/build_notes.py --all --dry-run  # spend nothing, see the plan

Notes are written once and read forever, so revising a topic costs no tokens.
Re-running for a topic replaces its note rather than adding a second one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.llm.exceptions import AllProvidersRateLimitedError, LLMRateLimitError  # noqa: E402
from src.llm.provider import build_provider  # noqa: E402
from src.notes.generator import NoteWriter  # noqa: E402
from src.store.db import Store  # noqa: E402
from src.syllabus.models import SyllabusSpine  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", help="a single topic code, e.g. 4.3")
    ap.add_argument("--all", action="store_true", help="every topic in the spine")
    ap.add_argument("--missing", action="store_true",
                    help="only topics that have no note yet")
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

    have = set(store.note_topics())
    if args.topic:
        plan = [args.topic]
    elif args.missing:
        plan = [c for c in spine.topic_codes if c not in have]
    elif args.all:
        plan = list(spine.topic_codes)
    else:
        ap.print_help()
        return 1

    print(f"Plan: {len(plan)} note(s). Bank already holds {len(have)}.")
    for code in plan:
        marker = " (replaces existing)" if code in have else ""
        print(f"  {code}{marker}")

    if args.dry_run:
        print("\nDry run — nothing generated, no tokens spent.")
        return 0

    try:
        provider = build_provider(settings)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    writer = NoteWriter(provider, store, spine)

    written = 0
    rejected: list[tuple[str, str]] = []
    for code in plan:
        try:
            report = writer.write_for_topic(code)
        except LLMRateLimitError as exc:
            print(f"\nRate limited on {code}: wait {exc.friendly_wait()}.")
            print(f"Kept every note written so far ({written}).")
            break
        except AllProvidersRateLimitedError as exc:
            print(f"\nEvery configured provider is rate-limited: {exc}")
            print(f"Kept every note written so far ({written}).")
            break
        except ValueError as exc:
            print(f"  {code}: {exc}")
            continue
        written += report.written
        rejected.extend(report.rejected)
        print(f"  {code}: {report.summary()}")

    print(f"\nWrote {written} note(s).")
    if rejected:
        print(f"Rejected {len(rejected)}:")
        for code, reason in rejected:
            print(f"  {code}: {reason}")
        print("Re-run for those topics; a rejection is not retried automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
