"""Configuration. Everything overridable from .env — no hardcoded model names.

Model IDs are read from the environment on purpose: providers retire dated
model snapshots on their own schedule, and a pinned ID is a time bomb.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))


@dataclass(frozen=True)
class Settings:
    subject: str = "economics"
    syllabus_code: str = os.getenv("SYLLABUS_CODE", "9708")
    syllabus_version: str = os.getenv("SYLLABUS_VERSION", "2026-2028")
    level: str = os.getenv("SYLLABUS_LEVEL", "AS")

    syllabus_pdf: Path = DATA_DIR / os.getenv("SYLLABUS_PDF", "9708-syllabus.pdf")
    spine_path: Path = DATA_DIR / "syllabus_spine.json"
    db_path: Path = DATA_DIR / "as-econ.sqlite3"

    groq_api_key: str | None = os.getenv("GROQ_API_KEY")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    llm_fallback_order: str = os.getenv("LLM_FALLBACK_ORDER", "groq")


settings = Settings()
