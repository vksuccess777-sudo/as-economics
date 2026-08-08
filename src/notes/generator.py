"""Generate revision notes for a syllabus topic — the knowledge base.

Same posture as every other generator here: batch only, syllabus-grounded,
validated before it is stored. A note is written once and read forever, so
opening a topic to revise spends nothing.

The note has a fixed set of sections rather than free prose. Two reasons:

1. The page can render sections without parsing prose, and the Coach can pull
   the "common mistakes" of a weak topic without reading the whole note.
2. A fixed shape is checkable. A model asked for free notes writes whatever
   length it feels like and quietly omits the section that is hardest — which,
   for AS Economics, is always evaluation. The validator here rejects a note
   missing any required section, so the hard part cannot be skipped.

What this deliberately does NOT do: ingest third-party revision sites. The
grounding claim in this system is "everything traces to the official syllabus
spine". Mixing in scraped notes breaks that claim and the licence.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..llm.provider import LLMProvider
from ..store.db import Store
from ..syllabus.models import SyllabusSpine, Topic

# Every section is required. `evaluation` is required even for a micro topic
# where evaluation feels unnatural — Paper 2 gives 25% of the AS mark to AO3,
# and a revision note that skips it teaches the student to skip it too.
REQUIRED_SECTIONS = (
    "definitions",      # [{term, meaning}]
    "core_ideas",       # [str] the chains of reasoning that carry marks
    "diagrams",         # [{name, what_to_label, what_shifts}]
    "evaluation",       # [str] usable judgement lines
    "common_mistakes",  # [str] what loses marks
    "exam_notes",       # [str] how it is tested
)

MIN_ITEMS = {
    "definitions": 3,
    "core_ideas": 3,
    "evaluation": 2,
    "common_mistakes": 2,
    "exam_notes": 1,
}


class NoteValidationError(ValueError):
    """A generated note was rejected with a reason. Never silently repaired."""


SYSTEM_PROMPT = """You are an experienced Cambridge International AS Level \
Economics (9708) teacher writing revision notes for one topic.

Rules:
- Cover ONLY the learning outcomes you are given. Do not teach A Level material \
(utility, indifference curves, the multiplier, market structures beyond the AS \
content). A student revising does not need to know what is not examined.
- Never invent statistics, country figures, dates or real-world numbers. Real \
examples may be named in general terms only.
- Definitions must be precise enough to earn a definition mark: a clause, not a \
paragraph.
- Core ideas must be CHAINS, written as a sequence of causes and effects ending \
in an effect on a named variable. "Higher interest rates reduce consumption" is \
half a chain; say why and what happens next.
- Diagrams: name the diagram, what must be labelled, and what shifts. Do not \
attempt ASCII art.
- Evaluation lines must be usable in an essay: what the answer depends on, and \
why it could go the other way.
- Common mistakes are the specific errors AS candidates make on this topic.
- Use British spelling and Cambridge terminology.
- Be concise. This is a revision note, not a textbook chapter.

Return ONLY a JSON object. No prose, no markdown fences."""

SCHEMA = """The object must have exactly these keys:
  "definitions":     array of {"term": string, "meaning": string}   (at least 3)
  "core_ideas":      array of string, each a full causal chain      (at least 3)
  "diagrams":        array of {"name": string, "what_to_label": string,
                               "what_shifts": string}   (may be empty)
  "evaluation":      array of string                                (at least 2)
  "common_mistakes": array of string                                (at least 2)
  "exam_notes":      array of string                                (at least 1)"""

# Terms that are USUALLY A Level in 9708. This list only PROPOSES a rejection —
# the parsed spine decides. Hard-coding what is and is not AS content from
# memory is how the Gini coefficient, which outcome 3.3.2 explicitly names,
# got a correct note rejected.
A_LEVEL_TERMS = (
    "indifference curve",
    "budget line",
    "marginal utility",
    "multiplier",
    "monopolistic competition",
    "oligopol",
    "kinked demand",
    "game theory",
    "natural rate of unemployment",
    "phillips curve",
    "gini coefficient",
    "lorenz curve",
    "marginal revenue product",
)

A_LEVEL_CANDIDATES = re.compile(
    r"\b(" + "|".join(A_LEVEL_TERMS) + r")\w*\b", re.IGNORECASE
)

# The syllabus excludes content inline, in brackets: "injections and leakages
# (multiplier not required)". So a term appearing in the spine is not by itself
# proof that it is examinable — the bracket can take it back. Note the contrast
# with "Gini coefficient (calculation not required)", where what is excluded is
# the calculation, not the concept. Only the phrase inside the bracket is
# excluded, which is why this is parsed rather than pattern-matched.
NOT_REQUIRED = re.compile(r"\(([^)]*?)\bnot required\)", re.IGNORECASE)


def as_vocabulary(spine: SyllabusSpine) -> tuple[str, set[str]]:
    """What the AS syllabus actually covers, read off the spine.

    Returns the searchable AS text and the set of terms the syllabus names as
    not required. Both are derived, never hard-coded: when Cambridge revises
    the syllabus, regenerating the spine updates this with no code change.
    """
    lines: list[str] = []
    excluded: set[str] = set()

    for unit in spine.units:
        lines.append(unit.title)
        for topic in unit.topics:
            lines.append(topic.title)
            for outcome in topic.outcomes:
                for line in (outcome.text, *outcome.bullets):
                    for match in NOT_REQUIRED.finditer(line):
                        term = match.group(1).strip().lower()
                        if term:
                            excluded.add(term)
                    lines.append(NOT_REQUIRED.sub(" ", line))

    return " ".join(lines).lower(), excluded


def out_of_scope_terms(spine: SyllabusSpine) -> list[str]:
    """Terms the validator will reject, so the prompt can forbid them first.

    Derived from the same two inputs the validator uses — the AS vocabulary and
    the candidate list — which is what stops the prompt and the gate drifting
    apart. A prompt that forbids less than the validator rejects produces
    retries; a prompt that forbids more silently narrows the syllabus.
    """
    vocabulary, excluded = as_vocabulary(spine)
    return sorted(
        term for term in A_LEVEL_TERMS
        if term not in vocabulary or any(term in e or e in term for e in excluded)
    )


def not_required_lines(spine: SyllabusSpine, topic: Topic) -> list[str]:
    """Outcome lines in THIS topic that carry an inline exclusion.

    Quoted whole rather than reduced to the bracketed phrase, because
    "Gini coefficient (calculation not required)" and "injections and leakages
    (multiplier not required)" mean opposite things and only the full line
    shows which.
    """
    lines = []
    for outcome in topic.outcomes:
        for line in (outcome.text, *outcome.bullets):
            if NOT_REQUIRED.search(line):
                lines.append(line.strip())
    return lines


@dataclass
class Note:
    topic_code: str
    sections: dict[str, list] = field(default_factory=dict)

    def body_json(self) -> str:
        return json.dumps(self.sections, ensure_ascii=False)

    @classmethod
    def from_row(cls, row) -> "Note":
        return cls(topic_code=row["topic_code"], sections=json.loads(row["body"]))

    def section(self, key: str) -> list:
        return self.sections.get(key, [])

    def mistakes_text(self) -> list[str]:
        return [str(m) for m in self.section("common_mistakes")]


@dataclass
class NoteReport:
    requested: int = 0
    written: int = 0
    attempts: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        retried = f", attempts {self.attempts}" if self.attempts > 1 else ""
        return (
            f"requested {self.requested}, written {self.written}, "
            f"rejected {len(self.rejected)}{retried}"
        )


def build_prompt(
    topic: Topic,
    *,
    out_of_scope: list[str] | None = None,
    excluded_lines: list[str] | None = None,
    rejection: str | None = None,
) -> str:
    outcomes = "\n".join(f"- {o.code}: {o.searchable_text()}" for o in topic.outcomes)

    blocks = [
        "Write revision notes for the topic below.",
        f"\nTopic {topic.code}: {topic.title}",
        "\nLearning outcomes this topic covers — cover all of them, and nothing "
        f"beyond:\n{outcomes}",
    ]

    if excluded_lines:
        blocks.append(
            "\nThe syllabus limits some of these. Where a line says something is "
            "not required, that part is not examined and must not be taught:\n"
            + "\n".join(f"- {line}" for line in excluded_lines)
        )

    if out_of_scope:
        blocks.append(
            "\nNever mention these — they belong to the A Level half of this "
            "syllabus and will not be examined at AS:\n"
            + "\n".join(f"- {term}" for term in out_of_scope)
        )

    if rejection:
        blocks.append(
            f"\nYour previous attempt was rejected: {rejection}\nFix exactly that "
            "and keep everything else."
        )

    blocks.append(f"\n{SCHEMA}")
    return "\n".join(blocks)


def parse_response(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(),
                     flags=re.MULTILINE)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise NoteValidationError("response contained no JSON object")
        payload = json.loads(match.group(0))
    if not isinstance(payload, dict):
        raise NoteValidationError("expected a JSON object")
    return payload


def validate(note: Note, *, spine: SyllabusSpine | None = None) -> None:
    for key in REQUIRED_SECTIONS:
        if key not in note.sections:
            raise NoteValidationError(f"missing section {key!r}")
        if not isinstance(note.sections[key], list):
            raise NoteValidationError(f"section {key!r} is not a list")

    for key, minimum in MIN_ITEMS.items():
        if len(note.sections[key]) < minimum:
            raise NoteValidationError(
                f"section {key!r} has {len(note.sections[key])} items, needs {minimum}"
            )

    for d in note.sections["definitions"]:
        if not isinstance(d, dict) or not d.get("term") or not d.get("meaning"):
            raise NoteValidationError("a definition is missing its term or meaning")

    for d in note.sections["diagrams"]:
        if not isinstance(d, dict) or not d.get("name"):
            raise NoteValidationError("a diagram entry has no name")

    flat = json.dumps(note.sections).lower()
    vocabulary, excluded = as_vocabulary(spine) if spine else ("", set())

    for match in A_LEVEL_CANDIDATES.finditer(flat):
        term = match.group(1).lower()
        # Order matters. An explicit exclusion beats presence: the syllabus can
        # name a term only to say it is not required.
        if any(term in e or e in term for e in excluded):
            raise NoteValidationError(
                f"teaches content the syllabus marks not required ({term})"
            )
        if term in vocabulary:
            continue  # the AS syllabus covers it — the candidate list was wrong
        raise NoteValidationError(
            f"teaches A Level content ({term}) — it is not in the AS spine"
        )


def to_note(raw: dict, topic_code: str) -> Note:
    sections = {k: list(raw.get(k) or []) for k in REQUIRED_SECTIONS}
    return Note(topic_code=topic_code, sections=sections)


class NoteWriter:
    def __init__(self, provider: LLMProvider, store: Store, spine: SyllabusSpine):
        self.provider = provider
        self.store = store
        self.spine = spine
        self._out_of_scope = out_of_scope_terms(spine)

    def write_for_topic(self, topic_code: str, *, attempts: int = 2) -> NoteReport:
        """Write one note, retrying once with the rejection reason fed back.

        The retry exists because a rejection is cheap to diagnose and expensive
        for a person to chase: the reason is already a precise instruction, and
        making the human re-run the command to deliver it is work the loop can
        do. The deterministic gate is unchanged — a retry earns its way in, it
        is not waved through.
        """
        topic = self.spine.topic(topic_code)
        if topic is None:
            raise ValueError(f"topic {topic_code!r} is not in the spine")

        report = NoteReport(requested=1)
        excluded_lines = not_required_lines(self.spine, topic)
        rejection: str | None = None

        for attempt in range(max(1, attempts)):
            response = self.provider.generate(
                build_prompt(
                    topic,
                    out_of_scope=self._out_of_scope,
                    excluded_lines=excluded_lines,
                    rejection=rejection,
                ),
                system=SYSTEM_PROMPT,
                max_tokens=2000,
                # Nudged up on a retry: repeating the temperature that produced
                # a rejected note tends to reproduce the same note.
                temperature=0.3 if attempt == 0 else 0.6,
            )
            try:
                note = to_note(parse_response(response.text), topic.code)
                validate(note, spine=self.spine)
            except (NoteValidationError, ValueError, TypeError) as exc:
                rejection = str(exc)
                report.rejected.append((topic.code, f"attempt {attempt + 1}: {rejection}"))
                continue

            self.store.upsert_note(
                topic_code=note.topic_code,
                body=note.body_json(),
                syllabus_code=self.spine.syllabus_code,
                syllabus_version=self.spine.syllabus_version,
                model=response.model,
            )
            report.written = 1
            report.attempts = attempt + 1
            return report

        report.attempts = max(1, attempts)
        return report
