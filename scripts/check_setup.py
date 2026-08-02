#!/usr/bin/env python3
"""Verify the foundation is wired up. Run this before anything else.

Checks, in order: syllabus PDF present -> spine generated -> database
initialised -> Groq key present and the model actually reachable.

The Groq check makes a real (tiny) call rather than just checking the key
exists, because a key that is set but invalid fails identically to no key
at the point where it matters.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings  # noqa: E402
from src.store.db import Store  # noqa: E402
from src.syllabus.models import SyllabusSpine  # noqa: E402

OK, BAD, WARN = "  ok ", " FAIL", " warn"


def main() -> int:
    failures = 0

    print("as-econ setup check\n")

    if settings.syllabus_pdf.exists():
        size = settings.syllabus_pdf.stat().st_size // 1024
        print(f"{OK}  syllabus PDF        {settings.syllabus_pdf} ({size} KB)")
    else:
        print(f"{BAD}  syllabus PDF        missing: {settings.syllabus_pdf}")
        print("        download the 9708 syllabus from cambridgeinternational.org")
        failures += 1

    if settings.spine_path.exists():
        spine = SyllabusSpine.load(settings.spine_path)
        c = spine.counts()
        print(
            f"{OK}  syllabus spine      {c['units']} units, {c['topics']} topics, "
            f"{c['outcomes']} outcomes, {c['command_words']} command words"
        )
    else:
        print(f"{BAD}  syllabus spine      missing — run scripts/build_syllabus_spine.py")
        failures += 1

    store = Store(settings.db_path)
    if store.is_initialised():
        counts = store.counts()
        print(
            f"{OK}  database            {settings.db_path.name} "
            f"({counts['question']} questions, {counts['response']} responses)"
        )
    else:
        print(f"{WARN}  database            not initialised — creating it now")
        store.initialise()
        print(f"{OK}  database            created at {settings.db_path}")

    if not settings.groq_api_key:
        print(f"{BAD}  groq                GROQ_API_KEY not set (copy .env.example to .env)")
        failures += 1
    else:
        try:
            from src.llm.provider import GroqProvider

            provider = GroqProvider(settings.groq_api_key, settings.groq_model)
            resp = provider.generate("Reply with the single word: ready.", max_tokens=10)
            print(f"{OK}  groq                {settings.groq_model} -> {resp.text.strip()[:40]!r}")
        except Exception as exc:  # noqa: BLE001
            print(f"{BAD}  groq                {type(exc).__name__}: {exc}")
            failures += 1

    print()
    print("All checks passed." if not failures else f"{failures} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
