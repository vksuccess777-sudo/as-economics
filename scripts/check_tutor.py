"""Show what the Concept Tutor will accept, and why it refuses the rest.

Spends no tokens. Retrieval and the scope gate run entirely locally, so this
answers "is the text box broken?" without a single API call — which is the
question that went unanswered for a whole build cycle.

    python scripts/check_tutor.py                  # the standard question set
    python scripts/check_tutor.py --ask "what is deadweight loss"
    python scripts/check_tutor.py --no-notes       # spine only, for comparison
    python scripts/check_tutor.py --verbose        # show what was retrieved

A refusal is not automatically a bug: "explain indifference curves" SHOULD be
refused. What matters is the reason column. `unknown_terms` naming an ordinary
English word ("affect", "impose") is a false refusal — add the word to
src/tutor/general_words.py. `unknown_terms` naming a technical term the AS
course does not contain is the guard working.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.store.db import Store  # noqa: E402
from src.syllabus.models import SyllabusSpine  # noqa: E402
from src.tutor.corpus import excluded_phrases, load_note_documents  # noqa: E402
from src.tutor.explainer import ConceptTutor, build_sources  # noqa: E402
from src.tutor.retriever import SpineRetriever  # noqa: E402

# Real student phrasing, not syllabus phrasing. That distinction is the whole
# point: the starter buttons quote the syllabus verbatim and always matched,
# which is why the failure looked like "only the buttons work".
QUESTIONS = [
    # should be answered
    "why does the demand curve slope downwards",
    "what is meant by market failure and why does it happen",
    "how does a subsidy affect the market",
    "what happens to price when supply increases",
    "explain externalities in simple terms",
    "what is the difference between a tax and a subsidy",
    "what are the causes of unemployment",
    "explain the balance of payments",
    "why do governments impose maximum prices",
    "explain opportunity cost with an example",
    "what are the effects of a rise in interest rates",
    "explain PED and PES",
    "what is macroeconimics",
    "what is macro economics",
    "explain suply and demand",
    # exam technique — routed away from concept retrieval
    "what does evaluate mean in the exam",
    "how many marks is section B worth",
    "how should I structure a 12 mark answer",
    # should be refused
    "explain indifference curves",
    "what is deadweight loss",
    "what is photosynthesis",
    "how do I bake sourdough bread",
    "who is the president of India",
    "explain the multiplier",
    # partial — one unknown word beside a subject the syllabus does cover
    "how do i differentiate gdp and gnp",
    "difference between CPI and RPI",
    # was mangled into "example / prepared / knowledge / market"
    "for exam preparation how are marks distributed between chapters",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ask", help="check one question instead of the set")
    parser.add_argument("--no-notes", action="store_true",
                        help="search the syllabus spine only")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="print the top retrieved documents")
    args = parser.parse_args()

    if not settings.spine_path.exists():
        print("No syllabus spine. Run: python scripts/build_syllabus_spine.py")
        return 1
    spine = SyllabusSpine.load(settings.spine_path)

    documents = []
    if not args.no_notes:
        store = Store(settings.db_path)
        if store.is_initialised():
            documents = load_note_documents(store, spine)

    excluded = excluded_phrases(spine)
    retriever = SpineRetriever(spine, documents, excluded_phrases=excluded)
    counts = retriever.counts()
    print(
        f"Corpus: {counts['chapters']} chapters + {counts['syllabus']} syllabus "
        f"lines + {counts['notes']} note sections = {counts['documents']} "
        f"documents, {counts['vocabulary']} distinct terms"
    )
    print(
        "  not required at AS: "
        + "; ".join(" ".join(p) for p in excluded)
    )
    if counts["notes"] == 0 and not args.no_notes:
        print("  ! No notes loaded — run scripts/build_notes.py --all to widen matching")

    a_level_path = settings.spine_path.with_name("syllabus_spine_a.json")
    a_level = SyllabusSpine.load(a_level_path) if a_level_path.exists() else None
    if a_level is None:
        print("  ! No A Level spine — refusals cannot say \"that's A Level\".")
        print("    Build one: python scripts/build_syllabus_spine.py --level A "
              "--out data/syllabus_spine_a.json")

    tutor = ConceptTutor(
        None, spine, a_level_spine=a_level, documents=documents,
        excluded_phrases=excluded,
    )

    questions = [args.ask] if args.ask else QUESTIONS
    print()
    refused = 0
    for question in questions:
        if tutor.is_exam_question(question):
            print(f"  EXAM  {'exam technique':<16} {question}")
            continue
        report = retriever.scope_report(question)
        verdict = {"ok": "ANSWER", "partial": "PARTLY"}.get(report.reason, "REFUSE")
        if verdict == "REFUSE":
            refused += 1
        detail = report.reason
        if report.unknown_terms:
            detail += " " + ",".join(report.unknown_terms[:3])
        print(f"  {verdict}  {detail:<16} score={report.top_score:5.2f}  {question}")
        if report.resolved:
            reading = ", ".join(f"{k}->{v}" for k, v in report.resolved.items())
            print(f"           reading {reading}")
        if verdict != "REFUSE":
            for source in build_sources(report.hits)[:3]:
                print(f"           from {source.chapter} · {source.topic}")
        if args.verbose:
            for hit in report.hits[:4]:
                label = f"{hit.source}/{hit.ref}"
                print(f"           {hit.score:5.2f} {label:<22} {hit.text[:80]}")

    print(f"\n{len(questions) - refused} answered, {refused} refused.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
