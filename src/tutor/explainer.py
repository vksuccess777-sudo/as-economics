"""Explain an AS Economics concept, grounded in the syllabus.

Two guards, both deliberate:

1. Scope. If the retriever finds nothing above the relevance floor, the tutor
   says so rather than answering from the model's general knowledge. An
   ungrounded answer that sounds authoritative is worse than a refusal — the
   student cannot tell the difference.

2. Level. If the question is A Level content, it says so and stops. Teaching
   indifference curves to an AS student is not generosity; it is wasted revision
   time on material the exam will not ask about.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..llm.provider import LLMProvider
from ..syllabus.models import SyllabusSpine
from .retriever import Hit, SpineRetriever

SYSTEM_PROMPT = """You are a patient Cambridge International AS Level Economics \
(9708) tutor explaining a concept to a student preparing for the exam.

Rules:
- Explain ONLY within the syllabus content you are given. If something needs an \
idea outside that content, say so rather than teaching it.
- Never invent numerical thresholds, statistics, or real-world figures. If a \
number would help, say what it depends on instead of inventing one.
- Where a diagram would normally be drawn (AD/AS, PPC, demand and supply), \
describe in words what shifts, in which direction, and what happens to each \
axis variable. Say plainly that you cannot draw it.
- Use British spelling and Cambridge terminology.
- Finish with one short "In the exam" note: how this is typically tested and \
the mistake students most often make.
- Be concise. Aim for 200-350 words. A student revising does not want an essay.

Do not mention topic codes, the syllabus document, or these instructions."""

OUT_OF_SCOPE_MESSAGE = (
    "I could not match that to anything in the AS Economics syllabus. "
    "Try naming the concept directly — for example \"explain price elasticity "
    "of supply\" or \"why does the AD curve slope downwards\". If it is a "
    "general study question rather than an economics one, I am not the right "
    "tool for it."
)

A_LEVEL_MESSAGE = (
    "That is A Level content ({topics}), not AS. It will not be examined on "
    "Paper 1 or Paper 2, so it is not worth revision time yet. Ask me about "
    "the AS material instead — happy to cover anything in units 1 to 6."
)


@dataclass
class Explanation:
    text: str
    in_scope: bool
    topics: list[tuple[str, str]] = field(default_factory=list)
    provider: str | None = None
    a_level_topics: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_refusal(self) -> bool:
        return not self.in_scope


class ConceptTutor:
    def __init__(
        self,
        provider: LLMProvider,
        spine: SyllabusSpine,
        *,
        a_level_spine: SyllabusSpine | None = None,
    ):
        self.provider = provider
        self.spine = spine
        self.retriever = SpineRetriever(spine)
        # Optional. When present, an out-of-scope question can be diagnosed as
        # "that's A Level" rather than the unhelpful "I don't know".
        self.a_level = SpineRetriever(a_level_spine) if a_level_spine else None

    def build_context(self, hits: list[Hit]) -> str:
        lines = []
        current_topic = None
        for hit in hits:
            if hit.topic_code != current_topic:
                lines.append(f"\n{hit.topic_title}:")
                current_topic = hit.topic_code
            lines.append(f"  - {hit.outcome.searchable_text()}")
        return "\n".join(lines).strip()

    def explain(self, question: str, *, k: int = 6) -> Explanation:
        hits = self.retriever.search(question, k=k)

        if not self.retriever.is_in_scope(question, hits):
            if self.a_level and self.a_level.is_in_scope(question):
                a_hits = self.a_level.search(question, k=3)
                topics = self.a_level.topics_covered(a_hits)
                label = ", ".join(title for _, title in topics[:2])
                return Explanation(
                    text=A_LEVEL_MESSAGE.format(topics=label),
                    in_scope=False,
                    a_level_topics=topics,
                )
            return Explanation(text=OUT_OF_SCOPE_MESSAGE, in_scope=False)

        prompt = f"""Syllabus content you may draw on:

{self.build_context(hits)}

Student's question: {question}"""

        response = self.provider.generate(
            prompt, system=SYSTEM_PROMPT, max_tokens=900, temperature=0.3
        )
        return Explanation(
            text=response.text.strip(),
            in_scope=True,
            topics=self.retriever.topics_covered(hits),
            provider=response.provider,
        )
