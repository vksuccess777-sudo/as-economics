"""Decide what each worksheet item is asking for.

The command word is the single most useful signal on a worksheet, and Cambridge
publishes the definitive list with definitions — which the parser already pulls
into `spine.command_words`. So the list is read from the spine, never written
here. A syllabus revision that adds or drops a command word updates this
module with no code change, which is the standing rule in this project after
the Gini incident.

What IS written here is the grouping of those words by the demand they place on
the student, because Cambridge does not publish that grouping and it is the
thing that decides the shape of a solution. Every name in a group is checked
against the real spine by a test, so the grouping can be wrong about emphasis
but can never invent a command word.
"""

from __future__ import annotations

import re

from src.syllabus.assessment import PAPER_2
from src.syllabus.models import SyllabusSpine

from .models import ESSAY, MCQ, SHORT, STRUCTURED, UNKNOWN, Item

# Words that ask for recall or a single named thing. A solution to one of these
# is an answer plus a line of justification, not an argument.
RECALL_WORDS = frozenset({"define", "state", "identify", "give", "describe", "outline"})

# Words that ask for a chain of reasoning (AO2).
ANALYTIC_WORDS = frozenset({"explain", "analyse", "calculate", "compare", "demonstrate"})

# Words that ask for a judgement (AO3). These carry the highest mark tariffs
# and are the ones where handing over a finished answer teaches least.
EVALUATIVE_WORDS = frozenset({"discuss", "evaluate", "assess", "justify", "comment", "consider"})

# The smallest Paper 2 essay part is 8 marks (part a); 12 is part b. Anything
# at or above the smaller of those is treated as extended writing regardless of
# its command word, because tariff drives the expected structure.
ESSAY_MIN_MARKS = min(
    section.marks // (section.parts or 1)
    for section in PAPER_2.sections
    if section.key in {"b", "c"}
) if any(s.key in {"b", "c"} for s in PAPER_2.sections) else 8

SHORT_MAX_MARKS = 4


def command_words(spine: SyllabusSpine) -> dict[str, str]:
    """{lowercase command word: Cambridge's own definition}, from the spine."""
    raw = getattr(spine, "command_words", None) or {}
    return {str(word).strip().lower(): str(meaning) for word, meaning in raw.items()}


def detect_command_word(text: str, spine: SyllabusSpine) -> str:
    """The command word the item opens with, else the first one it uses.

    Position matters: "explain why a subsidy might be preferred to a maximum
    price, and evaluate" opens with explain, and the opening word is the one
    that sets the tariff. A word appearing mid-sentence is a weaker signal, so
    it is only used when nothing leads the item.
    """
    words = command_words(spine)
    if not words or not text.strip():
        return ""

    stripped = text.strip().lstrip("([{ ").lower()
    for word in sorted(words, key=len, reverse=True):
        if re.match(rf"^{re.escape(word)}\b", stripped):
            return word

    lowered = text.lower()
    found = [
        (match.start(), word)
        for word in words
        if (match := re.search(rf"\b{re.escape(word)}\b", lowered))
    ]
    return min(found)[1] if found else ""


def classify(item: Item, spine: SyllabusSpine) -> Item:
    """Set kind and command_word on an item. Pure, deterministic, free."""
    # The command word often sits in the shared stem rather than in the part:
    # "Identify, in each case, a policy measure ..." followed by (a), (b), (c).
    # Checking only the part text leaves every one of those items unlabelled.
    item.command_word = detect_command_word(item.text, spine) or detect_command_word(
        item.context, spine
    )
    item.kind = _kind(item)
    return item


def _kind(item: Item) -> str:
    if len(item.options) >= 3:
        return MCQ

    word = item.command_word
    marks = item.marks

    if marks is not None and marks >= ESSAY_MIN_MARKS:
        return ESSAY
    if word in EVALUATIVE_WORDS and (marks is None or marks > SHORT_MAX_MARKS):
        return ESSAY
    if marks is not None and marks <= SHORT_MAX_MARKS:
        return SHORT
    if word in RECALL_WORDS:
        return SHORT
    if word in ANALYTIC_WORDS:
        return STRUCTURED
    if item.text.strip():
        return STRUCTURED
    return UNKNOWN


def classify_all(items: list[Item], spine: SyllabusSpine) -> list[Item]:
    return [classify(item, spine) for item in items]


def command_word_note(item: Item, spine: SyllabusSpine) -> str:
    """Cambridge's definition of this item's command word, verbatim.

    Shown to the student because the commonest reason a worksheet answer loses
    marks is answering a different command word from the one printed — writing
    a description when the paper said evaluate.
    """
    if not item.command_word:
        return ""
    meaning = command_words(spine).get(item.command_word, "")
    return f"{item.command_word.capitalize()} — {meaning}" if meaning else ""
