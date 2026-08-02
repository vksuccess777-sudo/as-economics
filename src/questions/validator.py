"""Deterministic validation for generated MCQs.

Every rule here is a real failure mode of model-generated multiple choice.
None of them need an LLM to detect, so validation is free and reproducible.
A question that fails is rejected with a reason, never silently repaired —
a repaired question is an unreviewed question.
"""

from __future__ import annotations

import re

from .models import OPTION_KEYS, MCQItem

# Cambridge does not use these forms in 9708 Paper 1. Models reach for them
# constantly because they are easy to write.
BANNED_OPTION_PATTERNS = (
    re.compile(r"^\s*(all|none)\s+of\s+the\s+above", re.IGNORECASE),
    re.compile(r"^\s*both\s+[a-d]\s+and\s+[a-d]", re.IGNORECASE),
    re.compile(r"^\s*[a-d]\s+and\s+[a-d]\s+only", re.IGNORECASE),
)

# Phrases that betray a question written about the syllabus rather than about
# economics.
BANNED_STEM_PATTERNS = (
    re.compile(r"\baccording to the syllabus\b", re.IGNORECASE),
    re.compile(r"\bwhich of the following statements about topic\b", re.IGNORECASE),
    re.compile(r"\bas defined in (the )?(unit|topic|section)\b", re.IGNORECASE),
)

MIN_STEM_CHARS = 25
MAX_STEM_CHARS = 600
MIN_OPTION_CHARS = 1
MAX_OPTION_CHARS = 220

# If the correct option is much longer than every distractor, the question is
# answerable on length alone. 1.6x is deliberately lenient; anything above it
# is a real tell.
MAX_CORRECT_LENGTH_RATIO = 1.6


class ValidationError(ValueError):
    """Raised with a human-readable reason for rejection."""


def _normalise(text: str) -> str:
    """Collapse whitespace, lowercase, and drop trailing punctuation.

    Order matters: stripping the full stop before the trailing space left
    "the tax ." and "the tax" looking like different options, which is exactly
    the near-duplicate this check exists to catch.
    """
    collapsed = re.sub(r"\s+", " ", text or "").strip().lower()
    return re.sub(r"[\s.;,:]+$", "", collapsed)


def validate(item: MCQItem, *, known_topic_codes: set[str] | None = None) -> None:
    """Raise ValidationError on the first problem found."""
    stem = (item.stem or "").strip()
    if len(stem) < MIN_STEM_CHARS:
        raise ValidationError(f"stem too short ({len(stem)} chars)")
    if len(stem) > MAX_STEM_CHARS:
        raise ValidationError(f"stem too long ({len(stem)} chars)")
    for pattern in BANNED_STEM_PATTERNS:
        if pattern.search(stem):
            raise ValidationError("stem refers to the syllabus rather than to economics")

    if set(item.options) != set(OPTION_KEYS):
        raise ValidationError(f"options must be exactly {list(OPTION_KEYS)}, got {sorted(item.options)}")

    if item.answer_key not in OPTION_KEYS:
        raise ValidationError(f"answer_key {item.answer_key!r} is not one of {list(OPTION_KEYS)}")

    seen: dict[str, str] = {}
    for key in OPTION_KEYS:
        text = (item.options[key] or "").strip()
        if len(text) < MIN_OPTION_CHARS:
            raise ValidationError(f"option {key} is empty")
        if len(text) > MAX_OPTION_CHARS:
            raise ValidationError(f"option {key} too long ({len(text)} chars)")
        for pattern in BANNED_OPTION_PATTERNS:
            if pattern.search(text):
                raise ValidationError(f"option {key} uses a banned combination form")
        norm = _normalise(text)
        if norm in seen:
            raise ValidationError(f"options {seen[norm]} and {key} are duplicates")
        seen[norm] = key

    correct_len = len(item.options[item.answer_key].strip())
    longest_distractor = max(
        len(item.options[k].strip()) for k in OPTION_KEYS if k != item.answer_key
    )
    if longest_distractor and correct_len / longest_distractor > MAX_CORRECT_LENGTH_RATIO:
        raise ValidationError(
            "correct option is much longer than every distractor "
            f"({correct_len} vs {longest_distractor} chars) — answerable on length alone"
        )

    missing_rationales = [k for k in OPTION_KEYS if not (item.rationales.get(k) or "").strip()]
    if missing_rationales:
        raise ValidationError(f"missing rationale for {', '.join(missing_rationales)}")

    if not item.topic_code:
        raise ValidationError("topic_code is required")
    if known_topic_codes is not None and item.topic_code not in known_topic_codes:
        raise ValidationError(f"topic_code {item.topic_code!r} is not in the syllabus spine")


def is_valid(item: MCQItem, *, known_topic_codes: set[str] | None = None) -> bool:
    try:
        validate(item, known_topic_codes=known_topic_codes)
    except ValidationError:
        return False
    return True
