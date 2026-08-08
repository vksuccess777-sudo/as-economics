#!/usr/bin/env python3
"""Read a worksheet and show what the app makes of it. Spends nothing.

    python scripts/check_worksheet.py                      # built-in sample
    python scripts/check_worksheet.py path/to/sheet.pdf
    python scripts/check_worksheet.py sheet.docx --prompt 2

Everything printed here happens before any model is called: extraction,
splitting into items, mark allocations, command words, and which topic each
item was matched to. `--prompt N` prints the exact prompt item N would be sent,
so the wording can be checked without paying for it.

Worth running on a real worksheet the first time a new layout shows up. The
number to look at is COVERAGE — anything below 100% means lines of the sheet
were not placed under a question, and the items list is incomplete.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import settings  # noqa: E402
from src.notes.generator import out_of_scope_terms  # noqa: E402
from src.store.db import Store  # noqa: E402
from src.syllabus.models import SyllabusSpine  # noqa: E402
from src.tutor.corpus import excluded_phrases, load_note_documents  # noqa: E402
from src.tutor.retriever import SpineRetriever  # noqa: E402
from src.worksheet.classify import classify_all, command_word_note  # noqa: E402
from src.worksheet.extract import extract  # noqa: E402
from src.worksheet.models import KIND_LABELS  # noqa: E402
from src.worksheet.segment import segment  # noqa: E402
from src.worksheet.solve import build_prompt  # noqa: E402
from src.worksheet.topics import coverage_counts, item_topic  # noqa: E402

SAMPLE = """Economics Department — Market Failure Worksheet
Name: ....................

1. Identify, in each case, a government policy measure that could be used to
correct the following examples of market failure.
(a) Air pollution from a coal-fired power station. [2]
(b) Under-consumption of vaccinations in a rural district. [2]
(c) A monopoly water supplier charging a very high price. [2]

2. Define the term 'merit good'. [2]

3. Explain, using a demand and supply diagram, how a specific indirect tax
affects the price and quantity of cigarettes. [6]

4. Which of the following is most likely to shift the supply curve of wheat to
the right?
A An increase in the price of wheat
B A fall in the wage rate of farm workers
C An increase in the demand for bread
D A tax on wheat producers

5. Discuss whether a maximum price is the best way to make housing affordable
for low income families. [12]
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="worksheet file; omit for the sample")
    parser.add_argument("--prompt", metavar="LABEL",
                        help="print the prompt for one item, e.g. --prompt 1(a)")
    parser.add_argument("--text", action="store_true",
                        help="print the extracted text before splitting it")
    parser.add_argument("--log", action="store_true",
                        help="also write matched topics to worksheet_topic_log, "
                             "same as the live Worksheet Helper page does on "
                             "upload. Off by default so a dry run stays a dry run.")
    args = parser.parse_args(argv)

    if args.path:
        source = Path(args.path)
        if not source.exists():
            print(f"No such file: {source}")
            return 1
        result = extract(source.name, source.read_bytes())
        for warning in result.warnings:
            print(f"WARNING  {warning}")
        if not result.ok:
            return 1
        raw, name, kind = result.text, source.name, result.kind
    else:
        raw, name, kind = SAMPLE, "built-in sample", "text"

    print(f"Source:         {name} ({kind})")

    if args.text:
        print("\n--- extracted text ---")
        print(raw)
        print("--- end ---\n")

    if not settings.spine_path.exists():
        print(f"Spine:          MISSING at {settings.spine_path}")
        print("Run: python scripts/build_syllabus_spine.py")
        return 1
    spine = SyllabusSpine.load(settings.spine_path)

    sheet = segment(raw, source_name=name, source_kind=kind)
    classify_all(sheet.items, spine)

    print(f"Items:          {len(sheet.items)}")
    print(f"Marks printed:  {sheet.total_printed_marks or '—'}")
    print(f"Coverage:       {sheet.coverage:.0%} "
          f"({sheet.placed_lines}/{sheet.total_lines} lines placed)")
    if sheet.preamble:
        head = sheet.preamble.replace("\n", " / ")[:90]
        print(f"Preamble:       {head}")
    print()

    for warning in sheet.warnings:
        print(f"WARNING  {warning}")
    if sheet.warnings:
        print()

    store = Store(settings.db_path)
    retriever = None
    if store.is_initialised():
        retriever = SpineRetriever(
            spine,
            documents=load_note_documents(store, spine),
            excluded_phrases=excluded_phrases(spine),
        )

    for item in sheet.items:
        marks = f"[{item.marks}]" if item.marks else "[—]"
        print(f"{item.label:<10} {KIND_LABELS[item.kind]:<22} {marks:<5} "
              f"{item.command_word or '—':<10} "
              f"{'diagram' if item.requires_diagram else ''}")
        print(f"           {item.text.replace(chr(10), ' ')[:88]}")
        if item.options:
            print(f"           options: {', '.join(sorted(item.options))}")
        if retriever is not None:
            hits = [h for h in retriever.search(item.full_text(), k=4)
                    if h.source != "chapter"]
            if hits:
                print(f"           topic:   {hits[0].topic_code} {hits[0].topic_title} "
                      "(closest match — shown to the student on the solved item)")
            else:
                print("           topic:   no AS syllabus match — flagged in the UI")
            confident = item_topic(item, retriever)
            if confident:
                print(f"           coverage: {confident} — counts toward AI Coach "
                      "priority")
            else:
                print("           coverage: not confident enough to log — either no "
                      "match, below the score floor, or too close to call between "
                      "topics. This item will NOT move anything on the AI Coach page.")
        note = command_word_note(item, spine)
        if note:
            print(f"           asks:    {note[:80]}")
        print()

    if retriever is not None:
        counts = coverage_counts(sheet.items, retriever)
        print("--- what this sheet would add to AI Coach's topic-coverage signal ---")
        if counts:
            for code, n in sorted(counts.items()):
                title = spine.topic(code).title if spine.topic(code) else ""
                print(f"  {code:<6} {title:<45} {n} item(s)")
        else:
            print("  Nothing — no item on this sheet matched a topic confidently "
                  "enough to log. This is common for short or generic sheets; it "
                  "does not mean the sheet failed to solve.")
        if args.log:
            if counts:
                store.record_worksheet_topics(counts)
                print(f"\n  Logged. store.worksheet_topic_frequency() now returns:")
                for code, n in sorted(store.worksheet_topic_frequency().items()):
                    print(f"    {code:<6} {n}")
            else:
                print("\n  Nothing to log.")
        else:
            print("\n  (dry run — pass --log to actually write this to the "
                  "database, same as uploading it on the Worksheet Helper page)")
        print()

    if args.prompt:
        wanted = next((i for i in sheet.items if i.label == args.prompt), None)
        if wanted is None:
            print(f"No item labelled {args.prompt!r}. "
                  f"Available: {', '.join(i.label for i in sheet.items)}")
            return 1
        lines: list[str] = []
        if retriever is not None:
            lines = [h.text for h in retriever.search(wanted.full_text(), k=6)
                     if h.source == "syllabus"][:8]
        print("=" * 72)
        print(f"PROMPT FOR {wanted.label} — nothing is sent, this is just the text")
        print("=" * 72)
        print(build_prompt(
            wanted,
            spine=spine,
            syllabus_lines=lines,
            excluded=out_of_scope_terms(spine),
            stimulus=sheet.preamble,
        ))

    return 0


if __name__ == "__main__":
    sys.exit(main())
