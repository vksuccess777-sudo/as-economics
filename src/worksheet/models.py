"""What a school worksheet looks like once it has been read.

A worksheet is not a paper. It has no mark scheme, no guaranteed numbering, no
fixed structure, and it may mix an MCQ block, a two-mark "identify" list and a
twelve-mark essay on one side of A4. Everything here is deliberately loose
about structure and strict about provenance: an item records what was printed
(marks, command word, label) separately from anything a model later says about
it, so the UI can never present a derived answer as if it came from a teacher.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Item kinds. These describe what the student has to DO, which is what decides
# the shape of a useful solution — a two-mark "identify" wants a named measure
# and one line of justification, a twelve-mark "discuss" wants a plan.
MCQ = "mcq"
SHORT = "short"
STRUCTURED = "structured"
ESSAY = "essay"
UNKNOWN = "unknown"

KIND_LABELS = {
    MCQ: "Multiple choice",
    SHORT: "Short answer",
    STRUCTURED: "Structured question",
    ESSAY: "Essay / extended answer",
    UNKNOWN: "Unclassified",
}


@dataclass
class Item:
    """One answerable thing on the worksheet.

    `context` holds the parent stem and any stimulus — for "identify, in each
    case, a policy measure for the following examples of market failure", the
    instruction is the context and each lettered case is its own Item. Solving
    (b) without the instruction above it is impossible, which is why context
    travels with the item rather than being left behind in the document.
    """

    label: str  # as printed: "3", "3(b)", "3(b)(ii)"
    text: str
    number: str = ""
    part: str = ""
    subpart: str = ""
    options: dict[str, str] = field(default_factory=dict)  # MCQ: {"A": "..."}
    marks: int | None = None
    kind: str = UNKNOWN
    command_word: str = ""
    context: str = ""
    requires_diagram: bool = False
    line_start: int = 0
    line_end: int = 0

    @property
    def is_mcq(self) -> bool:
        return self.kind == MCQ

    def full_text(self) -> str:
        """Everything a solver needs to read, stem included."""
        parts = [self.context.strip(), self.text.strip()]
        body = "\n".join(p for p in parts if p)
        if self.options:
            body += "\n" + "\n".join(
                f"{letter} {text}" for letter, text in sorted(self.options.items())
            )
        return body


@dataclass
class Worksheet:
    """A parsed worksheet plus an honest account of what parsing missed."""

    items: list[Item] = field(default_factory=list)
    preamble: str = ""
    source_name: str = ""
    source_kind: str = ""  # pdf | docx | text | image
    warnings: list[str] = field(default_factory=list)
    total_lines: int = 0
    placed_lines: int = 0

    @property
    def coverage(self) -> float:
        """Fraction of non-empty source lines that landed somewhere.

        Reported rather than asserted. A model asked to "extract the questions"
        from a long document will quietly return the first eight and stop, and
        nothing about the output looks wrong. Segmentation here is done in
        code precisely so this number can be computed and shown.
        """
        if not self.total_lines:
            return 0.0
        return self.placed_lines / self.total_lines

    @property
    def answerable(self) -> list[Item]:
        return [i for i in self.items if i.kind != UNKNOWN or i.text.strip()]

    def counts_by_kind(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        return counts

    @property
    def total_printed_marks(self) -> int | None:
        marks = [i.marks for i in self.items if i.marks]
        return sum(marks) if marks else None
