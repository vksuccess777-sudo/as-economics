"""Topic-coverage matching for worksheets: confident enough to log, or not.

The bar here is deliberately higher than the "closest match" shown to a
student in solve.py — a wrong guess here quietly nudges the AI Coach's
priorities for every session until it ages out, not just one button.
"""

from __future__ import annotations

import pytest

from src.syllabus.parser import parse_text
from src.tutor.retriever import SpineRetriever
from src.worksheet.classify import classify_all
from src.worksheet.models import Item
from src.worksheet.topics import coverage_counts, item_topic

from tests.fixtures import SYLLABUS_EXCERPT


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT, level="AS")


@pytest.fixture(scope="module")
def retriever(spine):
    return SpineRetriever(spine)


def _item(text: str, label: str = "1") -> Item:
    return Item(label=label, text=text)


def test_clear_match_returns_a_topic(retriever, spine):
    item = _item(
        "Explain the causes of a shift in the demand curve for a normal good."
    )
    classify_all([item], spine)
    assert item_topic(item, retriever) == "2.1"


def test_no_overlap_returns_none(retriever):
    item = _item("Describe the plot of your favourite film.")
    assert item_topic(item, retriever) is None


def test_weak_single_word_overlap_is_not_counted(retriever):
    # "produce" only lightly touches 1.1's "what/how/for whom to produce" —
    # nowhere near MIN_LOG_SCORE on its own, so this must not count.
    item = _item("Where does your local bakery produce its bread?")
    assert item_topic(item, retriever) is None


def test_coverage_counts_tally_by_topic(retriever, spine):
    items = [
        _item("Explain a cause of a shift in the demand curve.", "1"),
        _item("Explain a cause of a shift in the supply curve.", "2"),
        _item("What is opportunity cost? Give an example.", "3"),
        _item("Describe your favourite holiday destination.", "4"),
    ]
    classify_all(items, spine)
    counts = coverage_counts(items, retriever)
    assert counts.get("2.1") == 2
    assert "4" not in counts
    assert sum(counts.values()) <= len(items)


# ---- same-unit siblings vs cross-unit rivals -----------------------------


def test_same_unit_runner_up_does_not_block_a_match(retriever, spine):
    """2.4 scoring close to 2.1 is expected (both about demand & supply) and
    must not stop 2.1 from being logged — only a DIFFERENT unit's rival
    should be able to do that."""
    item = _item(
        "Explain a cause of a shift in the demand curve for a normal good."
    )
    classify_all([item], spine)
    assert item_topic(item, retriever) == "2.1"
