"""Split worksheet text into items, in code, with no model involved.

This is the part everyone is tempted to hand to an LLM ("here is a worksheet,
list the questions"). Two reasons not to:

1.  A model asked to extract items from a long document silently truncates.
    You get eight well-formed items from a worksheet of fourteen and no signal
    that anything is missing. The same failure has already appeared twice in
    this project - free-form notes skipping the evaluation section, and a
    subset assertion that could not see extra pages. Here it would be worse,
    because the student would work through a solution set that quietly omits
    the questions they most needed.

2.  Numbering, mark allocations and option letters are typography. `[4]` and
    `(a)` are unambiguous. Regexes get them right every time, cost nothing,
    and can be tested against real layouts.

So structure is deterministic and only the ECONOMICS is asked of a model.

Every source line carries its index through the whole builder, and the
Worksheet reports which lines ended up somewhere. That is not decoration: the
first version of this file silently discarded sibling parts - question 1(a)
and 1(b) vanished and only 1(c) survived - and the coverage number is what
made it visible on the first realistic worksheet.
"""

from __future__ import annotations

import re

from .models import Item, Worksheet

# "1." / "1)" / "Question 1" / "Q1" - must be followed by real text, so a bare
# year like "2024." at the start of a line is not read as question 2024.
TOP_LEVEL = re.compile(
    r"^\s*(?:(?:question|q)\s*)?(\d{1,2})\s*[.):]\s+(?=\S)", re.IGNORECASE
)
# A number on a line of its own: "Question 1", "Q2", "3." - common on
# worksheets built from a paper, where the parts start on the next line.
TOP_LEVEL_BARE = re.compile(
    r"^\s*(?:(?:question|q)\s*(\d{1,2})|(\d{1,2})\s*[.)])\s*$", re.IGNORECASE
)
# "(a)" / "a)" / "a." - lowercase only. Parts stop at h so they can never
# collide with the roman numerals below.
PART = re.compile(r"^\s*\(?([a-h])\s*[.)]\s+(?=\S)")
SUBPART = re.compile(r"^\s*\(?((?:i|ii|iii|iv|v|vi|vii|viii|ix|x))\s*[.)]\s+(?=\S)")
# "A ..." / "A) ..." / "A. ..." - uppercase, which is what separates an MCQ
# option from a part label on the same page.
OPTION = re.compile(r"^\s*([A-H])\s*[.)]?\s+(?=\S)")

# "[4]" or "(4 marks)" or "[4 marks]" - Cambridge uses the bracketed form,
# school worksheets use both.
MARKS = re.compile(r"[\[(]\s*(\d{1,2})\s*(?:marks?|m)?\s*[\])]", re.IGNORECASE)

FURNITURE = re.compile(
    r"^\s*(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s*/\s*\d+|-\s*\d+\s*-)\s*$",
    re.IGNORECASE,
)

# Deliberately narrow. An earlier version matched any mention of a curve, which
# flagged "which of the following shifts the supply curve of wheat" - an MCQ
# needing no drawing at all. A diagram is required when the question asks for
# one, so the test is for the instruction, not for the vocabulary.
DIAGRAM_HINT = re.compile(
    r"\b(?:diagram|graph|figure)\b|\b(?:draw|sketch|plot|illustrate|shade)\b",
    re.IGNORECASE,
)

# An MCQ needs a real set of alternatives. Three is the floor: two lettered
# lines are far more likely to be parts (a) and (b) upper-cased by an OCR pass.
MIN_OPTIONS = 3

UNSEGMENTED_CHARS = 400


def _clean(text: str) -> list[str]:
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        if FURNITURE.match(line):
            line = ""
        lines.append(line)
    return lines


def _marks_in(line: str) -> int | None:
    """Last bracketed number on the line - mark allocations sit at the end."""
    found = MARKS.findall(line)
    return int(found[-1]) if found else None


def strip_marks(text: str) -> str:
    return MARKS.sub("", text).strip()


def _opener(line: str) -> tuple[str, str, int] | None:
    """Which kind of label, if any, this line starts with.

    Order matters. Roman numerals are tested before lowercase parts because
    "(i)" would otherwise never be reached, and options are tested last because
    a lone capital letter is the weakest signal of the four.
    """
    match = TOP_LEVEL.match(line)
    if match:
        return ("top", match.group(1), match.end())
    match = TOP_LEVEL_BARE.match(line)
    if match:
        return ("top", match.group(1) or match.group(2), match.end())
    match = SUBPART.match(line)
    if match:
        return ("sub", match.group(1).lower(), match.end())
    match = PART.match(line)
    if match:
        return ("part", match.group(1).lower(), match.end())
    match = OPTION.match(line)
    if match:
        return ("option", match.group(1).upper(), match.end())
    return None


LEVEL_ORDER = {"top": 0, "part": 1, "sub": 2}


def label_chain(line: str) -> tuple[list[tuple[str, str]], str]:
    """Consume every label at the head of a line, outermost first.

    Worksheets print nested labels inline as often as they stack them:

        1 (a) (i) Define the term minimum price. (2 marks)

    Reading only the first label makes "(i) Define ..." the body of part (a),
    and then the "(ii)" on the next line looks like the FIRST sub-part, so (i)
    is absorbed as a stem and disappears. Consuming the whole chain up front
    is what keeps it an item.

    Each label must be strictly deeper than the last, which stops "A" in
    "(a) A firm ..." being read as a multiple-choice option.
    """
    chain: list[tuple[str, str]] = []
    rest = line
    deepest = -1
    while True:
        opener = _opener(rest)
        if opener is None or opener[0] == "option":
            break
        kind, value, end = opener
        if LEVEL_ORDER[kind] <= deepest:
            break
        chain.append((kind, value))
        deepest = LEVEL_ORDER[kind]
        rest = rest[end:]
    return chain, rest


def _label(number: str, part: str, subpart: str) -> str:
    label = number or "?"
    if part:
        label += f"({part})"
    if subpart:
        label += f"({subpart})"
    return label


class _Builder:
    """Accumulates (line number, text) pairs into the item currently open.

    Line numbers travel with the text so that anything the builder loses can be
    counted afterwards. Without them a dropped item is invisible.
    """

    def __init__(self) -> None:
        self.items: list[Item] = []
        self.preamble: list[tuple[int, str]] = []
        self.current: Item | None = None
        self.buffer: list[tuple[int, str]] = []
        self.number = ""
        self.part = ""
        self.subpart = ""
        self.context = ""  # stem inherited by the parts currently being read
        self.assigned: set[int] = set()

    def open(self, kind: str, value: str, text: str, line_no: int) -> None:
        if kind == "top":
            self.close()
            self.number, self.part, self.subpart = value, "", ""
            self.context = ""
        elif kind == "part":
            self._make_room(for_level="part")
            self.part, self.subpart = value, ""
        elif kind == "sub":
            self._make_room(for_level="sub")
            self.subpart = value

        self.current = Item(
            label=_label(self.number, self.part, self.subpart),
            text="",
            number=self.number,
            part=self.part,
            subpart=self.subpart,
            context=self.context,
            line_start=line_no,
            line_end=line_no,
        )
        self.buffer = [(line_no, text)] if text.strip() else []
        # A label line with nothing after it ("Question 1") is still a line
        # that was read and understood, so it counts as placed. Leaving it out
        # made a clean parse report 87% coverage and raised a false warning.
        self.assigned.add(line_no)

    def _make_room(self, *, for_level: str) -> None:
        """Deal with whatever is open before a part or sub-part starts.

        Two cases, and conflating them is what lost 1(a) and 1(b):

        - the open item is the PARENT STEM ("Identify, in each case, a policy
          measure for the following examples of market failure.") - not
          answerable on its own, so it becomes the shared context for the parts
          that follow and is never emitted as an item of its own;
        - the open item is a SIBLING already read in full - a real answer,
          which must be closed and kept.
        """
        if self.current is None:
            return

        is_parent_stem = (
            (for_level == "part" and not self.current.part)
            or (for_level == "sub" and not self.current.subpart)
        )

        if is_parent_stem:
            stem = "\n".join(t for _, t in self.buffer).strip()
            self.assigned |= {n for n, t in self.buffer if t.strip()}
            self.context = "\n".join(p for p in (self.context, stem) if p.strip())
            self.current = None
            self.buffer = []
        else:
            self.close()

    def close(self) -> None:
        if self.current is None:
            self.buffer = []
            return
        text = "\n".join(t for _, t in self.buffer).strip()
        self.current.text = strip_marks(text)
        self.current.requires_diagram = bool(
            DIAGRAM_HINT.search(self.current.text)
            or DIAGRAM_HINT.search(self.current.context)
        )
        self.assigned |= {n for n, t in self.buffer if t.strip()}
        self.items.append(self.current)
        self.current = None
        self.buffer = []

    def append(self, line_no: int, line: str) -> None:
        if self.current is None:
            self.preamble.append((line_no, line))
            if line.strip():
                self.assigned.add(line_no)
        else:
            self.buffer.append((line_no, line))
            self.current.line_end = line_no


def segment(text: str, *, source_name: str = "", source_kind: str = "text") -> Worksheet:
    """Turn worksheet text into items. No network, no tokens, no model."""
    lines = _clean(text)
    non_empty = {i for i, line in enumerate(lines) if line.strip()}

    builder = _Builder()
    option_rows: list[tuple[int, str, str]] = []

    def flush_options() -> None:
        nonlocal option_rows
        if option_rows and builder.current is not None:
            if len(option_rows) >= MIN_OPTIONS:
                builder.current.options = {letter: text for _, letter, text in option_rows}
                builder.assigned |= {n for n, _, _ in option_rows}
            else:
                # Too few to be alternatives - put the text back rather than
                # lose it. An OCR pass that upper-cases "(a)" lands here.
                for line_no, letter, text in option_rows:
                    builder.buffer.append((line_no, f"{letter} {text}"))
        option_rows = []

    for line_no, line in enumerate(lines):
        if not line.strip():
            builder.append(line_no, line)
            continue

        marks = _marks_in(line)
        opener = _opener(line)

        if opener and opener[0] == "option" and builder.current is not None:
            letter, end = opener[1], opener[2]
            option_rows.append((line_no, letter, strip_marks(line[end:].strip())))
            builder.current.line_end = line_no
            continue

        if opener and opener[0] != "option":
            flush_options()
            chain, rest = label_chain(line)
            for depth, (kind, value) in enumerate(chain):
                is_last = depth == len(chain) - 1
                builder.open(kind, value, rest if is_last else "", line_no)
            if marks is not None and builder.current is not None:
                builder.current.marks = marks
            continue

        if marks is not None and builder.current is not None and builder.current.marks is None:
            builder.current.marks = marks
        builder.append(line_no, line)

    flush_options()
    builder.close()

    preamble = "\n".join(t for _, t in builder.preamble).strip()

    sheet = Worksheet(
        items=[i for i in builder.items if i.text.strip() or i.options],
        preamble=preamble,
        source_name=source_name,
        source_kind=source_kind,
        total_lines=len(non_empty),
        placed_lines=len(builder.assigned & non_empty),
    )
    sheet.warnings = _warn(sheet)
    return sheet


def _warn(sheet: Worksheet) -> list[str]:
    warnings: list[str] = []

    if not sheet.items:
        warnings.append(
            "No numbered questions found. The text may be unnumbered prose, or a "
            "photo may have lost the numbering - you can still paste one question "
            "at a time."
        )
        return warnings

    longest = max(sheet.items, key=lambda i: len(i.text))
    if len(sheet.items) == 1 and len(longest.text) > UNSEGMENTED_CHARS:
        warnings.append(
            "The whole worksheet came through as a single question, which usually "
            "means the numbering did not survive extraction. Check the item below "
            "before solving."
        )

    numbers = [int(i.number) for i in sheet.items if i.number.isdigit()]
    if numbers:
        gaps = sorted(set(range(min(numbers), max(numbers) + 1)) - set(numbers))
        if gaps:
            warnings.append(
                "Numbering jumps at: "
                + ", ".join(str(g) for g in gaps)
                + ". Those questions are either missing from the upload or were "
                "not recognised."
            )

    if sheet.coverage < 0.95:
        missing = sheet.total_lines - sheet.placed_lines
        warnings.append(
            f"{missing} line(s) of the worksheet were not placed under any "
            "question - open the extracted text to see what was left out."
        )

    return warnings
