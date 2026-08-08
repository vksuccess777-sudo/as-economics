#!/usr/bin/env python3
"""Verify the foundation is wired up. Run this before anything else.

Checks, in order: syllabus PDF present -> spine generated -> database
initialised -> each configured LLM provider (Groq, Gemini, Mistral) actually
reachable.

Each provider check makes a real (tiny) call rather than just checking the
key exists, because a key that is set but invalid fails identically to no
key at the point where it matters.
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

    from src.llm.provider import GeminiProvider, GroqProvider, MistralProvider

    provider_checks = [
        ("groq", settings.groq_api_key, "GROQ_API_KEY",
         lambda: GroqProvider(settings.groq_api_key, settings.groq_model),
         settings.groq_model),
        ("gemini", settings.gemini_api_key, "GEMINI_API_KEY",
         lambda: GeminiProvider(settings.gemini_api_key, settings.gemini_model),
         settings.gemini_model),
        ("mistral", settings.mistral_api_key, "MISTRAL_API_KEY",
         lambda: MistralProvider(settings.mistral_api_key, settings.mistral_model),
         settings.mistral_model),
    ]
    order = [n.strip().lower() for n in settings.llm_fallback_order.split(",") if n.strip()]

    any_configured = False
    for name, key, env_name, factory, model in provider_checks:
        if not key:
            print(f"{WARN}  {name:<18} {env_name} not set — skipped")
            continue
        any_configured = True
        try:
            provider = factory()
            resp = provider.generate("Reply with the single word: ready.", max_tokens=10)
            in_order = "" if name in order else "  (not in LLM_FALLBACK_ORDER — won't be used)"
            print(f"{OK}  {name:<18} {model} -> {resp.text.strip()[:40]!r}{in_order}")
        except Exception as exc:  # noqa: BLE001
            print(f"{BAD}  {name:<18} {type(exc).__name__}: {exc}")
            failures += 1

    if not any_configured:
        print(f"{BAD}  llm                 no provider keys set at all "
              "(copy .env.example to .env and fill in at least one)")
        failures += 1

    print()
    print("All checks passed." if not failures else f"{failures} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
