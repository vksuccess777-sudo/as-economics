#!/usr/bin/env python3
"""Read a Cambridge Principal Examiner Report into the knowledge base.

    python scripts/ingest_examiner_report.py --dry-run
    python scripts/ingest_examiner_report.py
    python scripts/ingest_examiner_report.py --pdf data/papers/other-report.pdf
    python scripts/ingest_examiner_report.py --show           # what is stored

`--dry-run` reads and segments the PDF and prints exactly which papers and
sections would be used, without calling a model or writing anything. Run it
first: it is how you check the AS-only filter did what it should.

What is stored is a PARAPHRASE. Cambridge's wording is read from your local
copy in data/papers/, held in memory for the length of this run, and never
written to the database or to disk. Any produced line that reuses a run of
eight words from the report is rejected.

Only AS components (9708/1x and 9708/2x) are read. A June report also covers
9708/31-43, which are A Level, and ingesting those would put out-of-scope
content into an AS knowledge base.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.llm.exceptions import AllProvidersRateLimitedError, LLMRateLimitError  # noqa: E402
from src.llm.provider import build_provider  # noqa: E402
from src.notes.examiner import (  # noqa: E402
    ExaminerError,
    ExaminerIngestor,
    IngestReport,
    read_pdf,
    split_observations,
    split_papers,
    strip_furniture,
)
from src.store.db import Store  # noqa: E402
from src.syllabus.models import SyllabusSpine  # noqa: E402

DEFAULT_PDF = settings.db_path.parent / "papers" / "june-2024-examiner-report.pdf"


def source_label(path: Path) -> str:
    """Where this came from, recorded on every line."""
    return f"{settings.syllabus_code} examiner report ({path.stem})"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pdf", type=Path, default=DEFAULT_PDF)
    ap.add_argument("--dry-run", action="store_true", help="read and segment only")
    ap.add_argument("--show", action="store_true", help="print what is already stored")
    ap.add_argument("--limit", type=int, help="stop after N observations")
    args = ap.parse_args()

    # Deliberately NOT opened before the dry run: initialising the store
    # creates the observed_mistake table, and a run that claims to write
    # nothing should write nothing at all.
    def open_store() -> Store:
        store = Store(settings.db_path)
        if not store.is_initialised():
            store.initialise()
        return store

    if args.show:
        store = open_store()
        rows = store.observed_mistakes()
        if not rows:
            print("Nothing ingested yet.")
            return 0
        print(f"{len(rows)} line(s) stored\n")
        for row in rows:
            where = row["topic_code"] or "general"
            print(f"  [{where:<8}] {row['text']}")
            print(f"  {'':<11} {row['paper']} · {row['ref']} · confidence {row['confidence']}")
        return 0

    if not args.pdf.exists():
        print(f"No report at {args.pdf}.")
        print("Download the Principal Examiner Report from cambridgeinternational.org")
        print("and save it under data/papers/ (git-ignored).")
        return 2
    if not settings.spine_path.exists():
        print("No syllabus spine. Run scripts/build_syllabus_spine.py first.")
        return 2

    spine = SyllabusSpine.load(settings.spine_path)

    try:
        text = strip_furniture(read_pdf(args.pdf))
        papers = split_papers(text)
    except ExaminerError as exc:
        print(f"REFUSED: {exc}")
        return 2

    report = IngestReport(papers_seen=len(papers))
    observations = []
    print(f"{len(papers)} component(s) in {args.pdf.name}:\n")
    for paper in papers:
        mark = "USE " if paper.is_as else "skip"
        print(f"  {mark} {paper.code}  {paper.level:<3} {paper.title}")
        if not paper.is_as:
            continue
        report.papers_used += 1
        found = split_observations(paper)
        observations.extend(found)
        for observation in found:
            print(f"         {observation.ref:<34} {observation.kind:<14} {len(observation.text):>5} chars")

    print(f"\n{len(observations)} observation(s) from {report.papers_used} AS paper(s).")

    if args.dry_run:
        print("\nDry run — nothing sent to a model, nothing written.")
        return 0

    if not observations:
        print("Nothing to ingest.")
        return 1

    store = open_store()

    try:
        ingestor = ExaminerIngestor(build_provider(settings), store, spine)
    except Exception as exc:  # noqa: BLE001
        print(f"No LLM provider available: {exc}")
        return 1

    try:
        report = ingestor.ingest(
            observations,
            source=source_label(args.pdf),
            report=report,
            limit=args.limit,
        )
    except (AllProvidersRateLimitedError, LLMRateLimitError) as exc:
        print(f"Stopped: {exc}")
        print(report.summary())
        return 1

    print("\n" + report.summary())
    for where, reason in report.rejected[:20]:
        print(f"  rejected {where}: {reason}")

    mapped = store.observed_mistake_topics()
    print(f"\nTopics with examiner-observed mistakes: {len(mapped)}")
    general = len(store.observed_mistakes(kind="technique"))
    print(f"General exam-technique lines: {general}")
    print("\nSee them in the Knowledge Base, under Common mistakes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
