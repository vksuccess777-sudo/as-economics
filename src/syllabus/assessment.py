"""Assessment structure for Cambridge International AS Level Economics 9708.

Factual exam metadata (durations, mark totals, section shapes, AO weightings)
taken from the 2026-2028 syllabus. Used to shape generated mock papers and to
weight marking.

Verify against the syllabus for the actual examination year before relying on
it — Cambridge revises these on a published cycle.
"""

from __future__ import annotations

from dataclasses import dataclass

SYLLABUS_CODE = "9708"
SYLLABUS_VERSION = "2026-2028"

# Assessment objectives. Economics has THREE (Business 9609 has four) —
# there is no separate "Application" AO here.
AO_TITLES = {
    "AO1": "Knowledge and understanding",
    "AO2": "Analysis",
    "AO3": "Evaluation",
}

# Percentage weighting of each AO, by component and for the AS award overall.
AO_WEIGHTS_AS_LEVEL = {"AO1": 35, "AO2": 40, "AO3": 25}
AO_WEIGHTS_BY_PAPER = {
    "paper_1": {"AO1": 47, "AO2": 40, "AO3": 13},
    "paper_2": {"AO1": 33, "AO2": 37, "AO3": 30},
}


@dataclass(frozen=True)
class Section:
    key: str
    label: str
    marks: int
    parts: int | None  # None = unstructured
    choose_from: int  # 1 = compulsory
    focus: str  # "mixed" | "micro" | "macro"


@dataclass(frozen=True)
class Paper:
    key: str
    label: str
    minutes: int
    marks: int
    percent_of_as: int
    sections: tuple[Section, ...]


PAPER_1 = Paper(
    key="paper_1",
    label="AS Level Multiple Choice",
    minutes=60,
    marks=30,
    percent_of_as=33,
    sections=(
        Section(
            key="mcq",
            label="30 multiple-choice questions",
            marks=30,
            parts=30,
            choose_from=1,
            focus="mixed",
        ),
    ),
)

PAPER_2 = Paper(
    key="paper_2",
    label="AS Level Data Response and Essays",
    minutes=120,
    marks=60,
    percent_of_as=67,
    sections=(
        # Section A has "approximately six parts" — treated as a hint to the
        # generator, not a hard contract.
        Section(
            key="A",
            label="Data response (compulsory)",
            marks=20,
            parts=6,
            choose_from=1,
            focus="mixed",
        ),
        Section(
            key="B",
            label="Essay, mainly microeconomics",
            marks=20,
            parts=2,
            choose_from=2,
            focus="micro",
        ),
        Section(
            key="C",
            label="Essay, mainly macroeconomics",
            marks=20,
            parts=2,
            choose_from=2,
            focus="macro",
        ),
    ),
)

PAPERS = {p.key: p for p in (PAPER_1, PAPER_2)}

# Sections B and C are marked against a levels-based mark scheme, not a
# points-based one. The marker must emit a LEVEL per AO; marks are derived
# from the level by code, never by the model.
LEVELS_BASED_SECTIONS = {("paper_2", "B"), ("paper_2", "C")}

# Micro/macro split of the AS units, used to route essay generation to the
# right section.
MICRO_UNITS = {"1", "2", "3"}
MACRO_UNITS = {"4", "5", "6"}


def section_focus_for_unit(unit_code: str) -> str:
    if unit_code in MICRO_UNITS:
        return "micro"
    if unit_code in MACRO_UNITS:
        return "macro"
    return "mixed"


def is_levels_based(paper_key: str, section_key: str) -> bool:
    return (paper_key, section_key) in LEVELS_BASED_SECTIONS


def total_as_marks() -> int:
    return sum(p.marks for p in PAPERS.values())
