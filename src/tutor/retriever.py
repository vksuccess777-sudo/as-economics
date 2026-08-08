"""Find the syllabus content relevant to a question.

Deliberately lexical, not embedding-based. The AS spine holds 131 outcomes, 29
topics and 6 units, and the knowledge base 29 notes — small enough that scoring
every document costs nothing, and a keyword match is reproducible in a way a
vector search is not. No new dependency, no model download, no index to rebuild
when the syllabus changes.

The relevance floor matters more than the ranking: a question the corpus cannot
answer must be refused, not answered confidently from the model's own
knowledge. That is the same failure mode as a retrieval engine with no
similarity threshold.

Three corrections, each found by typing at it the way a student does:

1. The corpus is not the outcome lines alone. It is chapters (unit titles),
   outcomes, and the generated notes. "The Macroeconomy" is the name of unit 4
   and yet `macroeconomy` was in no document, so a question about half the
   course had nothing to match.

2. Vocabulary membership is resolved, not looked up. An exact-match test treats
   `macroeconimic`, `macro` and `macroeconomy` as three unknown words when they
   are one known idea spelt three ways. See `Vocabulary.resolve`.

3. Every hit carries where it came from, so the answer can cite chapter and
   topic instead of asserting.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..syllabus.models import LearningOutcome, SyllabusSpine
from .general_words import general_words

STOPWORDS = {
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "for",
    "with", "as", "by", "at", "from", "is", "are", "was", "were", "be", "been",
    "it", "its", "this", "that", "these", "those", "what", "which", "who",
    "how", "why", "when", "where", "does", "do", "did", "can", "could", "would",
    "should", "will", "shall", "may", "might", "must", "i", "you", "me", "my",
    "explain", "describe", "define", "tell", "about", "between", "difference",
    "meaning", "means", "understand", "help",
}

# Below this, the corpus does not really cover the question.
RELEVANCE_FLOOR = 0.08

# A question whose distinctive vocabulary is unknown is out of scope even if it
# scores. "indifference curves" scores against "Demand and supply curves" on
# the shared word "curves", though "indifference" appears nowhere in AS
# content. The distinctive term being ABSENT is the signal.
MAX_UNKNOWN_TERMS = 0

# Resolution thresholds. Deliberately conservative: each is a way for an
# off-syllabus word to be mistaken for an on-syllabus one, so each is set where
# the real AS vocabulary shows no collisions.
GENERAL_WORD_WEIGHT = 0.3

# Words that separate two things being asked about, rather than joining two
# words into one term. "gdp and gnp" is two subjects; "indifference curves" is
# one. See `blocked_span`.
COORDINATORS = frozenset(
    {"and", "or", "versus", "vs", "between", "compared", "against", "than",
     "with", "from", "plus", "also"}
)

MIN_PREFIX_MATCH = 4  # "macro" -> "macroeconomy"
MIN_SHARED_ROOT = 6  # "macroeconimic" ~ "macroeconomy"
TYPO_LEN = 5  # one wrong letter, from here up
TYPO_LEN_LONG = 8  # two wrong letters, from here up


def _stem(word: str) -> str:
    """Crude plural stripping, applied to corpus and query alike.

    Linguistic correctness does not matter here; consistency does. Students
    write "the demand curve" while the syllabus writes "demand curves", and
    without this they are different tokens.

    The -ies branch was a real bug: Cambridge writes "subsidies",
    "externalities", "monopolies"; stripping the trailing s alone produced
    "subsidie" while a student typing "subsidy" produced "subsidy", so the two
    never met and subsidies — core unit 3 content — read as off-syllabus.

    Words ending -ss or -us are left alone so "surplus" and "process" survive.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    # Sibilant plurals: "taxes" must reach "tax" and "losses" must reach
    # "loss". Stripping the trailing s alone gave "taxe" and "losse", the same
    # class of miss as the -ies bug above and just as invisible.
    if len(word) > 4 and word.endswith(("sses", "xes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenise(text: str) -> list[str]:
    words = re.findall(r"[a-z]+", (text or "").lower())
    return [_stem(w) for w in words if w not in STOPWORDS and len(w) > 2]


GENERAL_WORDS = general_words(_stem)


def _within(a: str, b: str, limit: int) -> bool:
    """Is the edit distance between a and b at most `limit`?

    Bounded Levenshtein, stopped early. Only ever called on short words against
    a few hundred candidates, so the naive implementation is the right one.
    """
    if abs(len(a) - len(b)) > limit:
        return False
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        if min(current) > limit:
            return False
        previous = current
    return previous[-1] <= limit


def _shared_prefix(a: str, b: str) -> int:
    n = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        n += 1
    return n


class Vocabulary:
    """The corpus's words, and the rules for recognising a student's spelling.

    Exact matching was the quiet cause of the worst refusals. `macroeconomics`,
    `macro` and `macroeconimics` are one idea spelt three ways, and only one of
    the three ever appears in Cambridge's prose. A student is not going to
    guess which.

    Resolution is reported, not silent: the question is rewritten in the
    corpus's own words for searching, and the substitution is handed back so
    the page can say "reading 'macroeconimics' as 'macroeconomy'". Silent
    correction would be worse than none — a student who has misunderstood a
    term deserves to see that the tutor answered a different one.
    """

    def __init__(self, terms: Iterable[str]):
        self._terms = set(terms)
        self._by_initial: dict[str, list[str]] = {}
        for term in self._terms:
            self._by_initial.setdefault(term[:1], []).append(term)

    def __contains__(self, token: str) -> bool:
        return token in self._terms

    def __len__(self) -> int:
        return len(self._terms)

    def __iter__(self):
        return iter(self._terms)

    def resolve(self, token: str) -> str | None:
        """The corpus term this token means, or None if there isn't one."""
        if token in self._terms:
            return token

        candidates = self._by_initial.get(token[:1], [])
        if not candidates:
            return None

        # A prefix of a corpus term: "macro" -> "macroeconomy". Requires real
        # length, or three-letter fragments would reach for anything.
        if len(token) >= MIN_PREFIX_MATCH:
            starts = [t for t in candidates if t.startswith(token)]
            if starts:
                return min(starts, key=len)

        # A shared root: "macroeconimic" and "macroeconomy" agree for nine
        # letters. Long agreement is hard to reach by accident.
        rooted = [t for t in candidates if _shared_prefix(token, t) >= MIN_SHARED_ROOT]
        if rooted:
            return max(rooted, key=lambda t: (_shared_prefix(token, t), -len(t)))

        # A typo: one wrong letter in a medium word, two in a long one.
        if len(token) >= TYPO_LEN:
            limit = 2 if len(token) >= TYPO_LEN_LONG else 1
            near = [t for t in candidates if _within(token, t, limit)]
            if near:
                return min(near, key=len)

        return None


@dataclass
class Document:
    """One searchable chunk: a chapter, a syllabus outcome, or a note section."""

    text: str
    topic_code: str
    topic_title: str
    source: str  # "chapter" | "syllabus" | "note"
    ref: str  # unit code, outcome code, or note section name
    outcome: LearningOutcome | None = None
    unit_code: str = ""
    unit_title: str = ""


@dataclass
class Hit:
    outcome: LearningOutcome | None
    topic_code: str
    topic_title: str
    score: float
    source: str = "syllabus"
    text: str = ""
    ref: str = ""
    unit_code: str = ""
    unit_title: str = ""


@dataclass
class ScopeReport:
    """Why a question was accepted or refused, in a form the UI can show.

    A refusal the student cannot interrogate looks like a broken text box.
    """

    in_scope: bool
    reason: str  # ok | no_tokens | below_floor | unknown_terms |
    #                not_required | partial
    top_score: float = 0.0
    unknown_terms: list[str] = field(default_factory=list)
    hits: list[Hit] = field(default_factory=list)
    resolved: dict[str, str] = field(default_factory=dict)
    suggestions: dict[str, str] = field(default_factory=dict)

    @property
    def near_misses(self) -> list[tuple[str, str]]:
        """Topics that scored, even if the question was refused."""
        seen: dict[str, str] = {}
        for hit in self.hits:
            seen.setdefault(hit.topic_code, hit.topic_title)
        return sorted(seen.items())


# ------------------------------------------------------------------ notes


NOTE_SECTIONS = ("definitions", "core_ideas", "diagrams", "evaluation",
                 "common_mistakes", "exam_notes")

SECTION_LABELS = {
    "definitions": "definitions",
    "core_ideas": "core ideas",
    "diagrams": "diagrams",
    "evaluation": "evaluation points",
    "common_mistakes": "common mistakes",
    "exam_notes": "exam notes",
}


def _flatten(value: Any) -> str:
    """Turn one note section into plain text, whatever shape it has."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v) for v in value)
    return ""


def note_documents(
    body: str | dict, *, topic_code: str, topic_title: str
) -> list[Document]:
    """One Document per note section, so a hit can name what it matched."""
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except (ValueError, TypeError):
            return []
    if not isinstance(body, dict):
        return []

    docs: list[Document] = []
    for section in NOTE_SECTIONS:
        text = _flatten(body.get(section)).strip()
        if text:
            docs.append(
                Document(
                    text=text,
                    topic_code=topic_code,
                    topic_title=topic_title,
                    source="note",
                    ref=section,
                )
            )
    return docs


# -------------------------------------------------------------- retriever


class SpineRetriever:
    def __init__(
        self,
        spine: SyllabusSpine,
        documents: Iterable[Document] | None = None,
        *,
        excluded_phrases: Iterable[Iterable[str]] | None = None,
    ):
        self.spine = spine
        # Terms Cambridge names but marks "not required" at AS — read off the
        # spine by the notes generator, never hard-coded here. They stay
        # searchable (the words do appear in the syllabus text) but a question
        # that turns on one is answered with "not required", which is more
        # useful to a student than either teaching it or refusing blankly.
        self.excluded_phrases = [list(p) for p in (excluded_phrases or ()) if p]
        self._docs: list[tuple[Document, Counter]] = []
        self._unit_of: dict[str, tuple[str, str]] = {}
        df: Counter = Counter()

        for unit in spine.units:
            for topic in unit.topics:
                self._unit_of[topic.code] = (unit.code, unit.title)

        # Chapters. A unit title is how a student names a whole area of the
        # course — "the macroeconomy", "international economic issues" — and it
        # appeared in no document until now, so "what is macroeconomics" had
        # nothing to match against half the syllabus.
        for unit in spine.units:
            titles = "; ".join(t.title for t in unit.topics)
            self._add(
                Document(
                    text=f"{unit.title}. {titles}",
                    topic_code=unit.code,
                    topic_title=unit.title,
                    source="chapter",
                    ref=unit.code,
                    unit_code=unit.code,
                    unit_title=unit.title,
                ),
                df,
            )

        for topic in spine.iter_topics():
            unit_code, unit_title = self._unit_of.get(topic.code, ("", ""))
            for outcome in topic.outcomes:
                # The topic title is part of the searchable text: an outcome
                # like "definition of inflation" only makes sense under
                # "Price stability".
                self._add(
                    Document(
                        text=f"{topic.title} {outcome.searchable_text()}",
                        topic_code=topic.code,
                        topic_title=topic.title,
                        source="syllabus",
                        ref=getattr(outcome, "code", topic.code),
                        outcome=outcome,
                        unit_code=unit_code,
                        unit_title=unit_title,
                    ),
                    df,
                )

        for doc in documents or []:
            if not doc.unit_code:
                doc.unit_code, doc.unit_title = self._unit_of.get(
                    doc.topic_code, ("", "")
                )
            self._add(doc, df)

        n = max(len(self._docs), 1)
        self._idf = {term: math.log(1 + n / (1 + count)) for term, count in df.items()}
        self._vocabulary = Vocabulary(df)

    def _add(self, doc: Document, df: Counter) -> None:
        tokens = tokenise(doc.text)
        counts = Counter(tokens)
        self._docs.append((doc, counts))
        df.update(set(tokens))

    # ---------------------------------------------------------- searching

    @property
    def vocabulary(self) -> Vocabulary:
        return self._vocabulary

    def counts(self) -> dict[str, int]:
        by_source: Counter = Counter(d.source for d, _ in self._docs)
        return {
            "documents": len(self._docs),
            "chapters": by_source["chapter"],
            "syllabus": by_source["syllabus"],
            "notes": by_source["note"],
            "vocabulary": len(self._vocabulary),
        }

    def resolve_query(self, query: str) -> tuple[list[str], dict[str, str], list[str]]:
        """Rewrite a question in the corpus's own words.

        Returns the searchable tokens, what was substituted for what, and the
        tokens nothing could be found for.
        """
        tokens: list[str] = []
        resolved: dict[str, str] = {}
        unknown: list[str] = []

        for token in tokenise(query):
            # Ordinary English is checked FIRST and never resolved. Resolving
            # it produced the worst output this tutor has given: "for exam
            # preparation ... how marks are distributed" was read as
            # "example / prepared / knowledge / market", because each of those
            # ordinary words happened to share a root with a syllabus term.
            # Approximate matching belongs only on words the corpus might
            # plausibly own.
            if token in GENERAL_WORDS:
                tokens.append(token)
                continue
            match = self._vocabulary.resolve(token)
            if match is not None:
                tokens.append(match)
                if match != token:
                    resolved[token] = match
            elif token not in unknown:
                unknown.append(token)

        return tokens, resolved, unknown

    def search(self, query: str, k: int = 6) -> list[Hit]:
        q_tokens, _, _ = self.resolve_query(query)
        if not q_tokens:
            return []
        # Ordinary English still scores, but softly. "in simple terms" should
        # not pull an answer toward "terms of trade" just because the syllabus
        # happens to use the word "terms" somewhere: the student meant nothing
        # by it. Downweighting rather than dropping, because a few of these
        # words — "goods", "rate", "level" — are load-bearing in economics.
        q_counts = Counter(q_tokens)
        for term in list(q_counts):
            if term in GENERAL_WORDS:
                q_counts[term] *= GENERAL_WORD_WEIGHT

        hits: list[Hit] = []
        for doc, counts in self._docs:
            total = sum(counts.values()) or 1
            score = sum(
                (counts[term] / total) * self._idf.get(term, 0.0) * weight
                for term, weight in q_counts.items()
            )
            if score > 0:
                hits.append(
                    Hit(
                        outcome=doc.outcome,
                        topic_code=doc.topic_code,
                        topic_title=doc.topic_title,
                        score=score,
                        source=doc.source,
                        text=doc.text,
                        ref=doc.ref,
                        unit_code=doc.unit_code,
                        unit_title=doc.unit_title,
                    )
                )

        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:k]

    # -------------------------------------------------------------- scope

    def unknown_terms(self, query: str) -> list[str]:
        """Query words that are neither in the corpus nor ordinary English.

        These are the words that carry a scope decision. Everything else in a
        student's sentence is scaffolding.
        """
        return self.resolve_query(query)[2]

    def vocabulary_coverage(self, query: str) -> float:
        """Fraction of the question's content words known to the corpus.

        A diagnostic — `scripts/check_tutor.py` prints it — never a gate.
        Coverage alone cannot tell "indifference" from "affect".
        """
        tokens = tokenise(query)
        if not tokens:
            return 0.0
        known = sum(1 for t in set(tokens) if self._vocabulary.resolve(t) is not None)
        return known / len(set(tokens))

    def spelling_suggestions(self, terms: Iterable[str]) -> dict[str, str]:
        """Best-effort "did you mean" for words that did not resolve.

        Looser than `resolve` on purpose: this only ever prints a suggestion,
        it never lets a question through.
        """
        out: dict[str, str] = {}
        for term in terms:
            if len(term) < TYPO_LEN:
                continue
            best = None
            for candidate in self._vocabulary:
                if abs(len(candidate) - len(term)) > 2:
                    continue
                limit = 2 if len(term) >= TYPO_LEN_LONG else 1
                if _shared_prefix(term, candidate) >= 3 and _within(term, candidate, limit):
                    if best is None or len(candidate) < len(best):
                        best = candidate
            if best:
                out[term] = best
        return out

    def scope_report(self, query: str, hits: list[Hit] | None = None) -> ScopeReport:
        tokens, resolved, unknown = self.resolve_query(query)
        hits = self.search(query) if hits is None else hits
        top = hits[0].score if hits else 0.0

        if not tokenise(query):
            return ScopeReport(False, "no_tokens", top, unknown, hits, resolved)
        excluded = self.excluded_in(tokens)
        if excluded:
            return ScopeReport(
                False, "not_required", top, excluded, hits, resolved,
            )
        if len(unknown) > MAX_UNKNOWN_TERMS:
            span = self.blocked_span(query, unknown[0])
            others = [
                token for token in tokens
                if token not in GENERAL_WORDS and token not in span
            ]
            if len(unknown) == 1 and others and top >= RELEVANCE_FLOOR * 2:
                # The question has a subject the syllabus owns and one word it
                # does not. Refusing outright answers nothing; answering
                # silently would teach the unknown term. It is answered around,
                # with the gap named.
                return ScopeReport(
                    False, "partial", top, [" ".join(span)], hits, resolved,
                    self.spelling_suggestions(unknown),
                )
            return ScopeReport(
                False, "unknown_terms", top, unknown, hits, resolved,
                self.spelling_suggestions(unknown),
            )
        if not hits or top < RELEVANCE_FLOOR:
            return ScopeReport(False, "below_floor", top, unknown, hits, resolved)
        return ScopeReport(True, "ok", top, unknown, hits, resolved)

    def blocked_span(self, query: str, unknown: str) -> list[str]:
        """The whole term an unknown word belongs to.

        This is what separates a question with one gap in it from a question
        that is nothing but a gap, and it does so structurally rather than
        statistically — an idf cut-off tuned on 308 documents means something
        else on 40, which makes it exactly the kind of constant that works
        today and misleads later.

        "indifference curves": the unknown word sits directly against a known
        one with nothing between them, so the term being asked about is the
        compound, and the compound is out of scope. Refuse.

        "gdp and gnp": a coordinator sits between them, so these are two
        things, one of which the syllabus covers. Answer that one and name the
        other as absent.
        """
        words = [
            _stem(w) for w in re.findall(r"[a-z]+", (query or "").lower())
        ]
        if unknown not in words:
            return [unknown]
        i = words.index(unknown)
        span = [unknown]
        for j in (i - 1, i + 1):
            if 0 <= j < len(words):
                neighbour = words[j]
                if neighbour in COORDINATORS or neighbour in STOPWORDS:
                    continue
                if len(neighbour) > 2 and neighbour not in GENERAL_WORDS:
                    span.insert(0 if j < i else len(span), neighbour)
        return span

    def excluded_in(self, tokens: list[str]) -> list[str]:
        """Which not-required phrases this question turns on, if any."""
        found: list[str] = []
        for phrase in self.excluded_phrases:
            n = len(phrase)
            for i in range(len(tokens) - n + 1):
                if tokens[i:i + n] == phrase:
                    found.append(" ".join(phrase))
                    break
        return found

    def is_in_scope(self, query: str, hits: list[Hit] | None = None) -> bool:
        return self.scope_report(query, hits).in_scope

    def topics_covered(self, hits: list[Hit]) -> list[tuple[str, str]]:
        seen: dict[str, str] = {}
        for hit in hits:
            if hit.source == "chapter":
                continue
            seen.setdefault(hit.topic_code, hit.topic_title)
        return sorted(seen.items())

    def unit_of(self, topic_code: str) -> tuple[str, str]:
        return self._unit_of.get(topic_code, ("", ""))
