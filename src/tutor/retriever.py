"""Find the syllabus outcomes relevant to a question.

Deliberately lexical, not embedding-based. The AS spine holds 131 outcomes —
small enough that scoring every one costs nothing, and a keyword match is
reproducible in a way a vector search is not. No new dependency, no model
download, no index to rebuild when the syllabus changes.

The relevance floor matters more than the ranking: a question the spine cannot
answer must be refused, not answered confidently from the model's own
knowledge. That is the same failure mode as a retrieval engine with no
similarity threshold.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from ..syllabus.models import LearningOutcome, SyllabusSpine

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "as", "by", "at", "from", "is", "are", "was", "were", "be", "been",
    "it", "its", "this", "that", "these", "those", "what", "which", "who",
    "how", "why", "when", "where", "does", "do", "did", "can", "could", "would",
    "should", "will", "shall", "may", "might", "must", "i", "you", "me", "my",
    "explain", "describe", "define", "tell", "about", "between", "difference",
    "meaning", "means", "understand", "help",
}

# Below this, the spine does not really cover the question.
RELEVANCE_FLOOR = 0.08

# Fraction of the question's content words that must exist anywhere in the AS
# vocabulary. This is the guard that score alone cannot provide: "indifference
# curves" scores well against "Demand and supply curves" on the shared word
# "curves", even though "indifference" appears nowhere in AS content. The
# distinctive term being absent is the signal, not the shared one being present.
MIN_VOCABULARY_COVERAGE = 0.6


def _stem(word: str) -> str:
    """Crudest possible plural stripping, applied to corpus and query alike.

    Linguistic correctness does not matter here; consistency does. Students
    write "the demand curve" while the syllabus writes "demand curves", and
    without this they are different tokens and the question falls out of scope.
    Words ending -ss or -us are left alone so "surplus" and "process" survive.
    """
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenise(text: str) -> list[str]:
    words = re.findall(r"[a-z]+", (text or "").lower())
    return [_stem(w) for w in words if w not in STOPWORDS and len(w) > 2]


@dataclass
class Hit:
    outcome: LearningOutcome
    topic_code: str
    topic_title: str
    score: float


class SpineRetriever:
    def __init__(self, spine: SyllabusSpine):
        self.spine = spine
        self._docs: list[tuple[LearningOutcome, str, str, Counter]] = []
        df: Counter = Counter()

        for topic in spine.iter_topics():
            for outcome in topic.outcomes:
                # The topic title is part of the searchable text: an outcome
                # like "definition of inflation" only makes sense under
                # "Price stability".
                tokens = tokenise(f"{topic.title} {outcome.searchable_text()}")
                counts = Counter(tokens)
                self._docs.append((outcome, topic.code, topic.title, counts))
                df.update(set(tokens))

        n = max(len(self._docs), 1)
        self._idf = {term: math.log(1 + n / (1 + count)) for term, count in df.items()}
        self._vocabulary = set(df)

    def search(self, query: str, k: int = 6) -> list[Hit]:
        q_tokens = tokenise(query)
        if not q_tokens:
            return []
        q_counts = Counter(q_tokens)

        hits: list[Hit] = []
        for outcome, topic_code, topic_title, counts in self._docs:
            total = sum(counts.values()) or 1
            score = sum(
                (counts[term] / total) * self._idf.get(term, 0.0) * weight
                for term, weight in q_counts.items()
            )
            if score > 0:
                hits.append(Hit(outcome, topic_code, topic_title, score))

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    def vocabulary_coverage(self, query: str) -> float:
        """Fraction of the question's content words known to the syllabus."""
        tokens = tokenise(query)
        if not tokens:
            return 0.0
        known = sum(1 for t in set(tokens) if t in self._vocabulary)
        return known / len(set(tokens))

    def is_in_scope(self, query: str, hits: list[Hit] | None = None) -> bool:
        hits = self.search(query) if hits is None else hits
        if not hits or hits[0].score < RELEVANCE_FLOOR:
            return False
        return self.vocabulary_coverage(query) >= MIN_VOCABULARY_COVERAGE

    def topics_covered(self, hits: list[Hit]) -> list[tuple[str, str]]:
        seen: dict[str, str] = {}
        for hit in hits:
            seen.setdefault(hit.topic_code, hit.topic_title)
        return sorted(seen.items())
