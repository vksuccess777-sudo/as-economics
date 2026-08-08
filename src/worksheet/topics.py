"""Which syllabus topics a worksheet touches — for coverage tracking only.

This is deliberately more cautious than the "closest match" used to attach a
note/practice link to a solved item in `solve.py`. There, a wrong guess costs
the student one bad button. Here, a wrong guess writes a row that skews the AI
Coach's priority arithmetic for every student session until it ages out — a
quieter, longer-lived mistake, so the bar for counting a match is higher.

The retriever is lexical (see `tutor/retriever.py`): a question can score
against a topic on one shared ordinary word — "make housing affordable for
low income families" scores against "national income statistics" purely on
"income". Two guards against exactly that:

1. MIN_LOG_SCORE — a floor well above noise, so a stray shared word rarely
   clears it on its own.
2. A cross-unit rival check: if the best-scoring topic in a DIFFERENT unit
   comes close enough to the top match, the item is genuinely ambiguous and
   is dropped. Sibling topics inside the SAME unit are not treated as rivals
   — on the real syllabus, "Demand and supply curves" (2.1) and "The
   interaction of demand and supply" (2.4) legitimately share most of their
   vocabulary, and demanding they separate by a wide margin threw away good
   matches without stopping the one collision (a different unit entirely)
   this exists to catch. Checked against the real 861-term corpus, not just
   the small parser-test fixture — the thresholds below are calibrated
   there.
"""

from __future__ import annotations

from collections import Counter

from ..tutor.retriever import SpineRetriever
from .models import Item

# The retriever's own floor (RELEVANCE_FLOOR = 0.08) marks "the corpus covers
# this at all". Coverage logging asks for more: "this item is confidently
# ABOUT this topic". On the real corpus, genuine topical matches score
# roughly 0.3-1.5; noise sits well under 0.2.
MIN_LOG_SCORE = 0.30

# A different-unit rival within this factor of the top score makes the match
# too close to call. Same-unit runners-up are ignored entirely (see module
# docstring) — this is deliberately about cross-topic confusion, not about
# the best match being a clean outright winner over its own neighbours.
RIVAL_MARGIN = 1.2


def item_topic(item: Item, retriever: SpineRetriever) -> str | None:
    """The one topic this item confidently belongs to, or None.

    None covers three cases the caller does not need to tell apart: nothing
    matched, the match was too weak, or a different-unit topic scored close
    enough that the item could plausibly belong to either.
    """
    hits = [h for h in retriever.search(item.full_text(), k=10) if h.source != "chapter"]
    if not hits:
        return None

    best_by_topic: dict[str, tuple[float, str]] = {}
    for hit in hits:
        current = best_by_topic.get(hit.topic_code)
        if current is None or hit.score > current[0]:
            best_by_topic[hit.topic_code] = (hit.score, hit.unit_code)

    ranked = sorted(best_by_topic.items(), key=lambda kv: kv[1][0], reverse=True)
    top_code, (top_score, top_unit) = ranked[0]
    if top_score < MIN_LOG_SCORE:
        return None

    rival_score = next(
        (score for _, (score, unit) in ranked[1:] if unit != top_unit), 0.0
    )
    if rival_score > 0 and top_score < rival_score * RIVAL_MARGIN:
        return None
    return top_code


def coverage_counts(items: list[Item], retriever: SpineRetriever) -> dict[str, int]:
    """Item count per confidently-matched topic. Text and answers never enter."""
    counts: Counter[str] = Counter()
    for item in items:
        code = item_topic(item, retriever)
        if code:
            counts[code] += 1
    return dict(counts)
