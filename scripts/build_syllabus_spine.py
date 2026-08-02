#!/usr/bin/env python3
"""Generate data/syllabus_spine.json from your local copy of the syllabus PDF.

    python scripts/build_syllabus_spine.py
    python scripts/build_syllabus_spine.py --pdf data/9708-syllabus.pdf --level AS

The PDF is NOT in this repository. Download it from cambridgeinternational.org
(AS & A Level Economics 9708 -> syllabus for your exam year) into data/.
The generated spine is git-ignored for the same reason.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.syllabus.parser import SyllabusParseError, parse_pdf  # noqa: E402


# Published shape of the AS syllabus (2026-2028):
# topics 1.1-1.6, 2.1-2.5, 3.1-3.3, 4.1-4.6, 5.1-5.4, 6.1-6.5.
EXPECTED_AS_TOPICS_PER_UNIT = {"1": 6, "2": 5, "3": 3, "4": 6, "5": 4, "6": 5}


def check_as_shape(spine) -> list[str]:
    """Return a list of warnings; empty means the parse matches the syllabus."""
    warnings: list[str] = []
    found = {u.code: len(u.topics) for u in spine.units}

    missing = set(EXPECTED_AS_TOPICS_PER_UNIT) - set(found)
    if missing:
        warnings.append(f"missing units: {', '.join(sorted(missing))}")

    for unit_code, expected in EXPECTED_AS_TOPICS_PER_UNIT.items():
        actual = found.get(unit_code)
        if actual is not None and actual != expected:
            warnings.append(
                f"unit {unit_code}: expected {expected} topics, found {actual}"
            )

    extra = set(found) - set(EXPECTED_AS_TOPICS_PER_UNIT)
    if extra:
        warnings.append(
            f"unexpected units (A Level leakage?): {', '.join(sorted(extra))}"
        )

    empty = [t.code for t in spine.iter_topics() if not t.outcomes]
    if empty:
        warnings.append(f"topics with no outcomes: {', '.join(empty)}")

    return warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", default=str(settings.syllabus_pdf))
    ap.add_argument("--out", default=str(settings.spine_path))
    ap.add_argument("--level", default=settings.level, choices=["AS", "A"])
    ap.add_argument("--version", default=settings.syllabus_version)
    args = ap.parse_args()

    try:
        spine = parse_pdf(
            args.pdf,
            level=args.level,
            syllabus_code=settings.syllabus_code,
            syllabus_version=args.version,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except SyllabusParseError as exc:
        print(f"ERROR: parse failed — {exc}", file=sys.stderr)
        return 3

    path = spine.save(args.out)
    counts = spine.counts()

    print(f"Parsed {args.pdf} ({args.level} Level, {args.version})")
    print(f"  units          {counts['units']}")
    print(f"  topics         {counts['topics']}")
    print(f"  outcomes       {counts['outcomes']}")
    print(f"  command words  {counts['command_words']}")
    print()
    for unit in spine.units:
        print(f"  {unit.code}  {unit.title}")
        for topic in unit.topics:
            print(f"      {topic.code:<5} {topic.title}  ({len(topic.outcomes)} outcomes)")
    print(f"\nWrote {path}")

    warnings = check_as_shape(spine) if args.level == "AS" else []
    if warnings:
        print("\nWARNINGS — check the PDF layout or the parser:")
        for w in warnings:
            print(f"  ! {w}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
