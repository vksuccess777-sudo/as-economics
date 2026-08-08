#!/usr/bin/env python3
"""What will the 'Go deeper' panel actually offer, and do the links work?

    python scripts/check_links.py                 # no network at all
    python scripts/check_links.py --topic 3.2
    python scripts/check_links.py --verify        # HEAD every URL

The fetching lives here, not in src/reference, on purpose: that package must
stay incapable of reading anything, and a test enforces it. This script only
ever asks whether a URL responds — it never reads a page body.

No tokens, ever.
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.reference.links import LinkSet, load_links  # noqa: E402
from src.reference.registry import RegistryError, load_registry  # noqa: E402
from src.syllabus.models import SyllabusSpine  # noqa: E402

TIMEOUT = 12
UA = "as-econ link check (personal study tool)"


def head(url: str) -> str:
    request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return f"{response.status} OK"
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 405):
            return f"{exc.code} (blocks HEAD — open it yourself)"
        return f"{exc.code} DEAD"
    except Exception as exc:  # noqa: BLE001
        return f"unreachable: {type(exc).__name__}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--topic", help="one topic code, e.g. 3.2")
    ap.add_argument("--verify", action="store_true", help="HEAD-check every URL")
    args = ap.parse_args()

    try:
        registry = load_registry()
    except RegistryError as exc:
        print(f"MANIFEST BROKEN: {exc}")
        return 2

    print(f"{len(registry.sources)} sources registered\n")
    for source in registry.sources:
        role = "LINK ONLY" if not source.is_data else "data"
        print(f"  {source.id:<20} {role:<10} {source.licence:<28} {source.name}")
        if source.caution:
            print(f"      caution: {source.caution}")
    print()

    spine_path = Path(settings.spine_path)
    if not spine_path.exists():
        print(f"No spine at {spine_path}. Run scripts/build_syllabus_spine.py first.")
        return 2
    spine = SyllabusSpine.load(spine_path)

    try:
        linkset = load_links(registry, set(spine.topic_codes))
    except Exception as exc:  # noqa: BLE001
        print(f"LINKS FILE BROKEN: {exc}")
        return 2

    curated = len(linkset.links)
    print(f"{curated} curated link(s) in data/reference/links.json")
    if curated == 0:
        print("  (that is the shipped state — every topic still gets live search links)")
    print()

    topics = [args.topic] if args.topic else list(spine.topic_codes)
    for code in topics:
        topic = spine.topic(code)
        if topic is None:
            print(f"{code}: not in the spine")
            continue
        rows = linkset.go_deeper(code, topic.title)
        print(f"{code}  {topic.title}")
        for row in rows:
            marker = "*" if row.kind == "curated" else " "
            status = f"   [{head(row.url)}]" if (args.verify and row.kind == "curated") else ""
            print(f"  {marker} {row.source_name:<22} {row.label}{status}")
        for notice in LinkSet.notices(rows):
            print(f"    notice: {notice}")
        print()

    if args.verify:
        print("Source home pages:")
        for source in registry.sources:
            print(f"  {source.id:<20} {head(source.home)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
