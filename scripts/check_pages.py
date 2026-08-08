#!/usr/bin/env python3
"""What will Streamlit actually put in the sidebar?

Two failure modes, both silent, both of which have cost a build cycle here:

1.  NOTHING APPEARS. Streamlit builds the sidebar by globbing `pages/*.py`
    NEXT TO THE ENTRY SCRIPT. If a zip extraction flattened the folders the
    glob returns nothing, and you get a working app with no navigation --
    which reads as "the feature was never built".

2.  TOO MUCH APPEARS. A zip cannot delete files. Unzipping an increment over
    the repo replaces and adds, so a screen that has been merged away stays
    on disk and keeps showing in the sidebar next to its replacement. The
    tests passed the whole time, because they only ever asked whether the
    expected screens were present -- never whether anything else was.

    python scripts/check_pages.py
    python scripts/check_pages.py --remove-retired   # deletes case 2 for you

No network, no tokens.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE_NAME = re.compile(r"^(\d+)_[A-Za-z0-9_\-]+\.py$")

EXPECTED = {
    "1_MCQ_Practice.py": "sit a timed Paper 1 mock",
    "2_Concept_Tutor.py": "ask about a concept",
    "3_Essay_Practice.py": "write a Paper 2 essay and get it marked",
    "4_AI_Coach.py": "progress, diagnosis, target grade, revision plan, reset",
    "5_Knowledge_Base.py": "revision notes per topic",
    "6_Worksheet_Helper.py": "upload a school worksheet and work through it",
    "7_Mock_Test.py": "sit a full Cambridge-pattern mock, filtered by chapter/unit",
}

# Screens that used to exist and have been folded into another one. Listed by
# name so the tooling can tell "left over from an older zip" apart from "a file
# I have not been told about", and say something useful about each.
RETIRED = {
    "4_Progress.py": "merged into 4_AI_Coach.py — its scoreboard, AO table, "
                     "command-word table and sitting history are in the "
                     "'Deeper breakdown' expander there",
    "6_Coach.py": "merged into 4_AI_Coach.py — target grade, diagnosis and "
                  "plan are the body of that page",
    "7_Data_Response.py": "withdrawn at the user's request — Paper 2 Section A "
                          "needs a real dataset registered first, and that was "
                          "not wanted. The engine (src/questions/data_response.py, "
                          "src/marking/points_marker.py, the scripts and their "
                          "tests) is untouched, so restoring the screen is a "
                          "matter of putting the page file back",
}


def _delete_command(names: list[str]) -> str:
    """The removal spelled out for the shell he is actually standing in."""
    posix = " ".join(f"pages/{n}" for n in names)
    windows = " ".join(f"pages\\{n}" for n in names)
    ps = ", ".join(f"'pages\\{n}'" for n in names)
    return (
        "Delete them:\n"
        f"      python scripts/check_pages.py --remove-retired\n"
        f"      Windows CMD:  del {windows}\n"
        f"      PowerShell:   Remove-Item {ps}\n"
        f"      macOS/Linux:  rm {posix}"
    )


def remove_retired(pages_dir: Path) -> list[str]:
    removed = []
    for name in sorted(RETIRED):
        target = pages_dir / name
        if target.exists():
            target.unlink()
            removed.append(name)
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--remove-retired",
        action="store_true",
        help="delete merged-away screens left behind by an unzip",
    )
    args = parser.parse_args(argv)

    print(f"Repo root:      {ROOT}")
    print(f"Working dir:    {Path.cwd()}")
    print(f"Entry script:   {ROOT / 'Home.py'}"
          f"{'' if (ROOT / 'Home.py').exists() else '   <-- MISSING'}")

    try:
        import streamlit

        print(f"Streamlit:      {streamlit.__version__}")
    except ImportError:
        print("Streamlit:      NOT INSTALLED — pip install -r requirements.txt")
        return 1

    pages_dir = ROOT / "pages"

    if args.remove_retired:
        if not pages_dir.is_dir():
            print("\nNo pages/ directory — nothing to remove.")
        else:
            removed = remove_retired(pages_dir)
            print()
            if removed:
                for name in removed:
                    print(f"Removed         pages/{name}")
                print("\nRestart Streamlit for the sidebar to change:")
                print("    Ctrl+C, then  streamlit run Home.py")
            else:
                print("No retired screens on disk. Nothing to remove.")

    print()

    problems: list[str] = []

    if not pages_dir.exists():
        print("pages/          MISSING")
        problems.append(
            "There is no pages/ directory next to Home.py. Streamlit has nothing "
            "to build a sidebar from."
        )
        found: list[str] = []
    elif not pages_dir.is_dir():
        problems.append("pages exists but is a file, not a directory.")
        found = []
    else:
        found = sorted(p.name for p in pages_dir.glob("*.py"))
        print(f"pages/          {len(found)} file(s) Streamlit will load:")
        for name in found:
            if name in EXPECTED:
                note = "  — " + EXPECTED[name]
            elif name in RETIRED:
                note = "   <-- RETIRED, should have been deleted"
            else:
                note = "   <-- not a known screen"
            flag = "" if PAGE_NAME.match(name) else "   <-- name will not sort as a page"
            print(f"                  {name}{note}{flag}")
        if not found:
            problems.append("pages/ exists but holds no .py files.")

        missing = [n for n in EXPECTED if n not in found]
        if missing:
            problems.append("Expected pages not found: " + ", ".join(missing))

        # A zip cannot delete. This is what is left over from the last one.
        leftover = [n for n in found if n in RETIRED]
        if leftover:
            detail = "\n".join(f"        {n} — {RETIRED[n]}" for n in leftover)
            problems.append(
                "Screens that were merged away are still on disk, so the sidebar "
                "shows them beside their replacement:\n"
                f"{detail}\n"
                f"      {_delete_command(leftover)}"
            )

        unknown = [n for n in found if n not in EXPECTED and n not in RETIRED]
        if unknown:
            problems.append(
                "Unrecognised screen(s) in pages/: " + ", ".join(unknown) + ".\n"
                "      If they are real, add them to EXPECTED in this script and "
                "to EXPECTED_PAGES in tests/test_app_entrypoints.py.\n"
                "      If they are leftovers, delete them."
            )

        # Two files sharing a number is the visible symptom of a stale copy:
        # Streamlit shows both and their order is arbitrary.
        by_number: dict[str, list[str]] = defaultdict(list)
        for name in found:
            match = PAGE_NAME.match(name)
            if match:
                by_number[match.group(1)].append(name)
        clashes = {num: names for num, names in by_number.items() if len(names) > 1}
        if clashes:
            detail = "; ".join(
                f"{num}: {' and '.join(names)}" for num, names in sorted(clashes.items())
            )
            problems.append(
                "Two screens share a sidebar position, so their order is "
                f"arbitrary — {detail}"
            )

    stray = sorted(p.name for p in ROOT.glob("*.py") if PAGE_NAME.match(p.name))
    if stray:
        print()
        print("Page files sitting at the repo root instead of in pages/:")
        for name in stray:
            print(f"                  {name}")
        problems.append(
            "Your extraction flattened the folders. Move these into pages/:\n"
            "      Windows:  move [0-9]_*.py pages\\\n"
            "      PowerShell: Move-Item -Path '[0-9]_*.py' -Destination pages\\"
        )

    # Running from the wrong directory does not break page discovery, but it
    # does break `from src...` imports, which looks like the same thing.
    if not (Path.cwd() / "src").exists():
        problems.append(
            f"You are not in the repo root. cd to {ROOT} before running "
            "`streamlit run Home.py`."
        )

    print()
    if problems:
        print("PROBLEMS")
        for i, p in enumerate(problems, start=1):
            print(f"  {i}. {p}")
        print()
        print("If you cannot get the sidebar to appear, run the single-file")
        print("fallback instead — same screens, no pages/ mechanism at all:")
        print("    streamlit run app_single.py")
        return 1

    print(f"All {len(EXPECTED)} screens will appear in the sidebar, and nothing else.")
    print("Start with:")
    print("    streamlit run Home.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
