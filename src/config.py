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

    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

    mistral_api_key: str | None = os.getenv("MISTRAL_API_KEY")
    mistral_model: str = os.getenv("MISTRAL_MODEL", "mistral-small-latest")

    llm_fallback_order: str = os.getenv("LLM_FALLBACK_ORDER", "groq,gemini,mistral")


settings = Settings()

_bootstrap_error: str | None = None
_bootstrap_attempted = False


def _bootstrap_spine_from_secrets() -> None:
    """Recreate the gitignored syllabus spine on Streamlit Community Cloud.

    data/syllabus_spine.json is deliberately kept out of GitHub (Cambridge
    copyright — see .gitignore), so a fresh cloud checkout never has it. Instead
    of committing it, a base64 copy lives in the app's Secrets (private to the
    deployment, never in git) and gets rebuilt into a real file on first run.
    No-ops locally, since the real file already exists there, and no-ops if
    the secret isn't set (e.g. running locally without Streamlit secrets).
    """
    global _bootstrap_error, _bootstrap_attempted
    _bootstrap_attempted = True
    if settings.spine_path.exists():
        return
    try:
        import base64

        import streamlit as st

        encoded = st.secrets.get("SYLLABUS_SPINE_B64") if hasattr(st, "secrets") else None
        if not encoded:
            _bootstrap_error = "secret not found or empty at bootstrap time"
            return
        settings.spine_path.parent.mkdir(parents=True, exist_ok=True)
        decoded = base64.b64decode(encoded)
        settings.spine_path.write_bytes(decoded)
        if not settings.spine_path.exists():
            _bootstrap_error = "write_bytes returned but file still doesn't exist"
    except ImportError:
        _bootstrap_error = "streamlit not importable at this point"
    except Exception as exc:  # noqa: BLE001 - we want to surface this, not hide it
        _bootstrap_error = f"{type(exc).__name__}: {exc}"


_bootstrap_spine_from_secrets()