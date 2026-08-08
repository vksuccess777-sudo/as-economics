"""Explain an AS Economics concept, grounded in the syllabus and the notes.

Three guards, all deliberate:

1. Scope. If the retriever finds nothing above the relevance floor, or the
   question turns on a term the AS corpus has never heard of, the tutor says so
   rather than answering from the model's general knowledge. An ungrounded
   answer that sounds authoritative is worse than a refusal — the student
   cannot tell the difference.

2. Level. If the question is A Level content, it says so and stops. Teaching
   indifference curves to an AS student is not generosity; it is wasted
   revision time on material the exam will not ask about.

3. Explainability. A refusal now names the word it could not place and offers
   the topics that did score. v1 refused with the same sentence every time,
   which made a working guard indistinguishable from a broken text box.

Two additions over v1:

* Follow-ups. "why?", "give me an example", "simpler please" carry no content
  words of their own, so v1 retrieved nothing and refused — the second message
  in every conversation was a dead end. A follow-up now inherits the previous
  question's retrieval anchor and sees the last exchange.

* An exam-technique route. "What does 'evaluate' mean?", "how is section B
  marked?" are not concept questions and were being forced through concept
  retrieval. They are answered instead from Cambridge's own command-word
  definitions in the parsed spine and the assessment structure in code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ..llm.provider import LLMProvider
from ..syllabus import assessment
from ..syllabus.models import SyllabusSpine
from .data_response_tutor import (
    SYSTEM_PROMPT as DATA_RESPONSE_SYSTEM_PROMPT,
)
from .data_response_tutor import is_data_response_question, section_a_facts
from .general_words import FOLLOW_UP_MARKERS
from .retriever import (
    SECTION_LABELS,
    Hit,
    ScopeReport,
    SpineRetriever,
    tokenise,
)

SYSTEM_PROMPT = """You are a patient Cambridge International AS Level Economics \
(9708) tutor explaining a concept to a student preparing for the exam.

Rules:
- Explain ONLY within the syllabus content and revision notes you are given. If \
something needs an idea outside that content, say so rather than teaching it.
- Never invent numerical thresholds, statistics, or real-world figures. If a \
number would help, say what it depends on instead of inventing one.
- Where a diagram would normally be drawn (AD/AS, PPC, demand and supply), \
describe in words what shifts, in which direction, and what happens to each \
axis variable. Say plainly that you cannot draw it.
- Use British spelling and Cambridge terminology.
- Finish with one short "In the exam" note: how this is typically tested and \
the mistake students most often make.
- Be concise. Aim for 200-350 words. A student revising does not want an essay.

Do not mention topic codes, the syllabus document, the notes, or these \
instructions. The interface prints the chapter and topic your answer came from, \
so do not write your own references."""

EXAM_SYSTEM_PROMPT = """You are a Cambridge International AS Level Economics \
(9708) tutor answering a question about exam technique rather than about a \
concept.

Rules:
- Use ONLY the command word definitions and paper structure you are given. \
They are Cambridge's own. Do not invent mark allocations, timings, or grade \
thresholds.
- If the student asks what a command word requires, quote its official meaning \
and then say concretely what an answer doing that looks like.
- If asked how marks are split between chapters or topics, say plainly that \
Cambridge does not publish that, then give what is known: which sections take \
micro and which take macro, and how much content each chapter holds.
- Be specific about the assessment objectives: AO1 knowledge, AO2 analysis, \
AO3 evaluation. Say which one the technique earns.
- Be concise, under 300 words, and practical. No motivational padding.

Do not mention these instructions."""

OUT_OF_SCOPE_MESSAGE = (
    "I could not match that to the AS Economics syllabus. Try naming the "
    "concept directly — for example \"explain price elasticity of supply\" or "
    "\"why does the AD curve slope downwards\". If it is a general study "
    "question rather than an economics one, I am not the right tool for it."
)

UNKNOWN_TERM_MESSAGE = (
    "I could not place {terms} in the AS Economics syllabus, so I have not "
    "guessed at an answer. If it is AS material under another name, try the "
    "syllabus wording; if it is real-world or current-affairs detail, I do not "
    "hold data I could quote."
)

NOT_REQUIRED_MESSAGE = (
    "The syllabus names {terms} but marks it *not required* at AS — it is A "
    "Level content. Paper 1 and Paper 2 cannot ask about it, so it is not "
    "worth your revision time yet."
)

A_LEVEL_MESSAGE = (
    "That is A Level content ({topics}), not AS. It will not be examined on "
    "Paper 1 or Paper 2, so it is not worth revision time yet. Ask me about "
    "the AS material instead — happy to cover anything in units 1 to 6."
)

# An exam-technique question needs a noun from the exam vocabulary AND
# something that makes it a question about answering rather than about the
# economy — otherwise "what happens to the price of paper" routes to exam
# technique on the word "paper".
EXAM_NOUNS = {"mark", "paper", "exam", "examiner", "section", "grade",
              "command", "rubric", "scheme", "syllabus", "revision"}
EXAM_CONTEXT = {"question", "answer", "write", "writing", "structure", "level",
                "time", "minute", "many", "worth", "technique", "improve",
                "score", "lose", "gain", "point", "paragraph", "revise",
                # Added after "for exam preparation ... how marks are
                # distributed between chapters" was routed to concept
                # retrieval and answered about government intervention.
                "chapter", "unit", "topic", "distribution", "distributed",
                "split", "weight", "weighting", "prepare", "preparation",
                "allocation", "allocated", "spread", "cover", "coverage",
                "know", "long", "format", "component", "total"}

# How much of the conversation the model sees on a follow-up. Two exchanges is
# enough to resolve "why?" and cheap; the whole history is neither.
HISTORY_TURNS = 2
HISTORY_ANSWER_CHARS = 700


@dataclass
class Source:
    """Where a piece of the answer came from, in the student's own vocabulary.

    Assembled in code from the retrieved documents, never asked of the model. A
    citation a model writes is a citation a model can invent, and an invented
    chapter reference is worse than none: it sends a student to the wrong page
    and looks authoritative doing it.
    """

    unit_code: str
    unit_title: str
    topic_code: str
    topic_title: str
    outcomes: list[str] = field(default_factory=list)
    note_sections: list[str] = field(default_factory=list)

    @property
    def chapter(self) -> str:
        return f"Chapter {self.unit_code} · {self.unit_title}"

    @property
    def is_chapter(self) -> bool:
        return not self.topic_code

    @property
    def topic(self) -> str:
        if self.is_chapter:
            return "whole chapter"
        return f"{self.topic_code} {self.topic_title}"

    def detail(self) -> str:
        parts = []
        if self.outcomes:
            parts.append("syllabus " + ", ".join(self.outcomes))
        if self.note_sections:
            parts.append(
                "notes: " + ", ".join(
                    SECTION_LABELS.get(s, s) for s in self.note_sections
                )
            )
        return " · ".join(parts)


def build_sources(hits: list[Hit]) -> list[Source]:
    """Group hits into one entry per topic, strongest topic first.

    A chapter hit becomes an entry of its own only if nothing inside that
    chapter matched — otherwise "Chapter 4" would sit above "4.3 Aggregate
    Demand and Aggregate Supply" saying strictly less.
    """
    order: list[str] = []
    by_topic: dict[str, Source] = {}
    chapters: dict[str, Source] = {}
    for hit in hits:
        if hit.source == "chapter":
            chapters.setdefault(
                hit.unit_code,
                Source(
                    unit_code=hit.unit_code,
                    unit_title=hit.unit_title,
                    topic_code="",
                    topic_title="",
                ),
            )
            continue
        if hit.topic_code not in by_topic:
            by_topic[hit.topic_code] = Source(
                unit_code=hit.unit_code or hit.topic_code.split(".")[0],
                unit_title=hit.unit_title,
                topic_code=hit.topic_code,
                topic_title=hit.topic_title,
            )
            order.append(hit.topic_code)
        source = by_topic[hit.topic_code]
        if hit.source == "syllabus" and hit.ref not in source.outcomes:
            source.outcomes.append(hit.ref)
        elif hit.source == "note" and hit.ref not in source.note_sections:
            source.note_sections.append(hit.ref)
    sources = [by_topic[code] for code in order]
    covered = {s.unit_code for s in sources}
    return sources + [c for u, c in chapters.items() if u not in covered]


@dataclass
class Explanation:
    text: str
    in_scope: bool
    topics: list[tuple[str, str]] = field(default_factory=list)
    provider: str | None = None
    a_level_topics: list[tuple[str, str]] = field(default_factory=list)
    kind: str = "concept"  # "concept" | "exam" | "refusal"
    sources: list[Source] = field(default_factory=list)
    resolved: dict[str, str] = field(default_factory=dict)
    unsupported_terms: list[str] = field(default_factory=list)
    scope: ScopeReport | None = None
    used_notes: bool = False
    followed_up: bool = False

    @property
    def is_refusal(self) -> bool:
        return not self.in_scope

    @property
    def suggestions(self) -> list[tuple[str, str]]:
        """Topics that scored even though the question was refused."""
        return self.scope.near_misses[:4] if self.scope else []


class ConceptTutor:
    # Read by the page as a stale-server check: a Streamlit process started
    # before this upgrade has the old class cached in sys.modules and will not
    # have this attribute.
    SUPPORTS_HISTORY = True
    SUPPORTS_DATA_RESPONSE = True

    def __init__(
        self,
        provider: LLMProvider,
        spine: SyllabusSpine,
        *,
        a_level_spine: SyllabusSpine | None = None,
        documents=None,
        excluded_phrases=None,
    ):
        self.provider = provider
        self.spine = spine
        self.retriever = SpineRetriever(
            spine, documents, excluded_phrases=excluded_phrases
        )
        # Optional. When present, an out-of-scope question can be diagnosed as
        # "that's A Level" rather than the unhelpful "I don't know".
        self.a_level = SpineRetriever(a_level_spine) if a_level_spine else None

    # ------------------------------------------------------------ context

    def build_context(self, hits: list[Hit]) -> str:
        """Syllabus outcomes first, then note detail, each labelled.

        The order is the point. The outcomes fix the boundary of what may be
        said; the notes supply the explanation. Reversing them lets a fluent
        note pull the answer past the syllabus edge.
        """
        chapters = [h for h in hits if h.source == "chapter"]
        syllabus = [h for h in hits if h.source == "syllabus"]
        notes = [h for h in hits if h.source == "note"]

        lines: list[str] = []
        for hit in chapters:
            lines.append(
                f"Chapter {hit.unit_code} of the AS course is \"{hit.unit_title}\", "
                f"covering: {hit.text.split('. ', 1)[-1]}"
            )
        if chapters:
            lines.append("")
        if syllabus:
            lines.append("Syllabus outcomes:")
            current = None
            for hit in syllabus:
                if hit.topic_code != current:
                    lines.append(f"\n{hit.topic_title}:")
                    current = hit.topic_code
                text = hit.outcome.searchable_text() if hit.outcome else hit.text
                lines.append(f"  - {text}")
        if notes:
            lines.append("\nRevision notes on these topics:")
            for hit in notes:
                lines.append(f"\n{hit.topic_title} — {hit.ref.replace('_', ' ')}:")
                lines.append(f"  {hit.text[:900]}")
        return "\n".join(lines).strip()

    def exam_context(self) -> str:
        words = "\n".join(
            f"  {word}: {meaning}"
            for word, meaning in sorted(self.spine.command_words.items())
        )
        papers = []
        for paper in assessment.PAPERS.values():
            sections = "; ".join(
                f"Section {s.key} {s.label} ({s.marks} marks)"
                for s in paper.sections
            )
            papers.append(
                f"  {paper.label}: {paper.minutes} minutes, {paper.marks} marks, "
                f"{paper.percent_of_as}% of the AS award. {sections}"
            )
        weights = ", ".join(
            f"{ao} {assessment.AO_TITLES[ao]} {pct}%"
            for ao, pct in assessment.AO_WEIGHTS_AS_LEVEL.items()
        )

        # Which chapters can be asked where. Cambridge publishes no per-topic
        # mark distribution, and inventing one would be the most damaging
        # possible answer to "how are marks split between chapters" — a
        # student would revise to it. What IS true is the micro/macro routing
        # of Paper 2 and the number of outcomes each chapter carries, so both
        # are given, each labelled for what it is.
        chapters = []
        for unit in self.spine.units:
            focus = assessment.section_focus_for_unit(unit.code)
            section = {"micro": "Paper 2 Section B", "macro": "Paper 2 Section C"}.get(
                focus, "Paper 2"
            )
            outcomes = sum(len(t.outcomes) for t in unit.topics)
            chapters.append(
                f"  Chapter {unit.code} {unit.title}: {len(unit.topics)} topics, "
                f"{outcomes} learning outcomes, {focus}, essays fall in {section}"
            )
        total_outcomes = sum(
            len(t.outcomes) for u in self.spine.units for t in u.topics
        )

        return (
            "Cambridge command words and their official meanings:\n"
            f"{words}\n\nAssessment structure:\n" + "\n".join(papers)
            + f"\n\nAssessment objective weighting across AS: {weights}."
            + "\n\nSections B and C of Paper 2 are marked with a levels-based "
            "mark scheme, not points. AS Level is graded a to e; there is no "
            "A* at AS."
            + "\n\nThe chapters of the AS course:\n" + "\n".join(chapters)
            + f"\n\nThe outcome counts above total {total_outcomes} and describe "
            "how much CONTENT each chapter holds. Cambridge does not publish a "
            "mark distribution across chapters, and Paper 1 can draw on any of "
            "them, so outcome counts are a guide to revision effort and must "
            "not be presented as mark weightings. Say so if asked."
        )

    # ------------------------------------------------------------ routing

    def is_exam_question(self, question: str) -> bool:
        tokens = set(tokenise(question))
        if not tokens & EXAM_NOUNS:
            return False
        if tokens & EXAM_CONTEXT:
            return True
        lowered = question.lower()
        return any(w.lower() in lowered for w in self.spine.command_words)

    def is_follow_up(self, question: str, history: Sequence[dict] | None) -> bool:
        """A short message that leans on the previous one.

        Not "did retrieval fail" — that would let any unrecognised question
        inherit the last topic and be answered as if it were in scope.
        """
        if not history:
            return False
        tokens = tokenise(question)
        if not tokens:
            return True
        if len(tokens) > 6:
            return False
        stemmed_markers = {t for t in tokens if t in FOLLOW_UP_MARKERS}
        # Every content word is either a follow-up marker or ordinary English.
        return bool(stemmed_markers) and not self.retriever.unknown_terms(question)

    def _history_block(self, history: Sequence[dict]) -> str:
        recent = list(history)[-HISTORY_TURNS:]
        parts = []
        for turn in recent:
            answer = (turn.get("answer") or "")[:HISTORY_ANSWER_CHARS]
            parts.append(f"Student asked: {turn.get('question', '')}\nYou answered: {answer}")
        return "\n\n".join(parts)

    # ------------------------------------------------------------ explain

    def explain(
        self,
        question: str,
        *,
        k: int = 8,
        history: Sequence[dict] | None = None,
    ) -> Explanation:
        # Checked BEFORE the exam route. "How are the marks split in Section
        # A" satisfies both, and the Section A facts are the more specific
        # answer — the general exam context knows the paper totals but not
        # the part shapes, the caps or the calculate rule.
        if is_data_response_question(question):
            return self._data_response_answer(question, history)
        if self.is_exam_question(question):
            return self._exam_answer(question, history)

        follow_up = self.is_follow_up(question, history)
        anchor = question
        if follow_up:
            previous = [t for t in history if t.get("in_scope")]
            if previous:
                # Retrieve on the question that worked, not on "why?".
                anchor = previous[-1].get("question", question)

        hits = self.retriever.search(anchor, k=k)
        report = self.retriever.scope_report(anchor, hits)

        if not report.in_scope and report.reason != "partial":
            return self._refuse(anchor if follow_up else question, report)

        prompt = f"""Syllabus content and notes you may draw on:

{self.build_context(hits)}

Student's question: {question}"""
        if report.reason == "partial":
            terms = ", ".join(f'"{t}"' for t in report.unknown_terms)
            prompt += (
                f"\n\nNote: {terms} does not appear anywhere in the AS syllabus "
                "content above. Open by saying briefly that it is not part of "
                "the AS course, and do not explain it or define it. If the "
                "content above contains a related measure or idea the syllabus "
                "does use, name that one instead and answer the rest of the "
                "question with it."
            )
        if follow_up and history:
            prompt = (
                f"Earlier in this conversation:\n\n{self._history_block(history)}\n\n"
                + prompt
                + "\n\nThis is a follow-up. Answer it directly; do not repeat "
                "the previous explanation in full."
            )

        response = self.provider.generate(
            prompt, system=SYSTEM_PROMPT, max_tokens=900, temperature=0.3
        )
        return Explanation(
            text=response.text.strip(),
            in_scope=True,
            topics=self.retriever.topics_covered(hits),
            provider=response.provider,
            kind="concept",
            scope=report,
            used_notes=any(h.source == "note" for h in hits),
            followed_up=follow_up,
            sources=build_sources(hits),
            resolved=report.resolved,
            unsupported_terms=report.unknown_terms if report.reason == "partial" else [],
        )

    def _exam_answer(
        self, question: str, history: Sequence[dict] | None
    ) -> Explanation:
        prompt = f"""{self.exam_context()}

Student's question: {question}"""
        if history:
            prompt = (
                f"Earlier in this conversation:\n\n{self._history_block(history)}\n\n"
                + prompt
            )
        response = self.provider.generate(
            prompt, system=EXAM_SYSTEM_PROMPT, max_tokens=800, temperature=0.3
        )
        return Explanation(
            text=response.text.strip(),
            in_scope=True,
            kind="exam",
            provider=response.provider,
        )

    def _data_response_answer(
        self, question: str, history: Sequence[dict] | None
    ) -> Explanation:
        """Teach Section A from the observed shapes, not from the model's memory.

        Same posture as the exam route: everything factual in the prompt is
        assembled in code from the mark schemes and the parsed spine, so the
        model is arranging known facts rather than recalling a paper structure
        it may have half-remembered from another board.
        """
        prompt = f"""What is known about Paper 2 Section A:

{section_a_facts(self.spine)}

Student's question: {question}"""
        if history:
            prompt = (
                f"Earlier in this conversation:\n\n{self._history_block(history)}\n\n"
                + prompt
            )
        response = self.provider.generate(
            prompt, system=DATA_RESPONSE_SYSTEM_PROMPT, max_tokens=900, temperature=0.3
        )
        return Explanation(
            text=response.text.strip(),
            in_scope=True,
            kind="data_response",
            provider=response.provider,
        )

    def _refuse(self, question: str, report: ScopeReport) -> Explanation:
        if self.a_level and self.a_level.is_in_scope(question):
            a_hits = self.a_level.search(question, k=3)
            topics = self.a_level.topics_covered(a_hits)
            label = ", ".join(title for _, title in topics[:2])
            return Explanation(
                text=A_LEVEL_MESSAGE.format(topics=label),
                in_scope=False,
                a_level_topics=topics,
                kind="refusal",
                scope=report,
            )

        if report.reason == "not_required" and report.unknown_terms:
            terms = ", ".join(f'"{t}"' for t in report.unknown_terms[:2])
            return Explanation(
                text=NOT_REQUIRED_MESSAGE.format(terms=terms),
                in_scope=False,
                kind="refusal",
                scope=report,
            )

        if report.reason == "unknown_terms" and report.unknown_terms:
            terms = ", ".join(f'"{t}"' for t in report.unknown_terms[:3])
            text = UNKNOWN_TERM_MESSAGE.format(terms=terms)
            if report.suggestions:
                guesses = ", ".join(
                    f'"{k}" → "{v}"' for k, v in list(report.suggestions.items())[:2]
                )
                text += f" Did you mean {guesses}?"
        else:
            text = OUT_OF_SCOPE_MESSAGE

        return Explanation(text=text, in_scope=False, kind="refusal", scope=report)
