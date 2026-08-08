"""Score a mock sitting against the marks Cambridge actually sets.

Paper 1 was already reported as a paper — "24 / 30" — because the MCQ marker
returns a paper-shaped result. Paper 2 was not: its three sections were
reported one at a time and nothing added them up, so a sitting that scored 34
on Sections B and C with Section A skipped showed three tidy metrics and no
statement that 20 marks of the paper had never been asked. This module makes
both papers report the same way.

TWO DENOMINATORS, AND THE DIFFERENCE MATTERS. A component has

  * `official_marks` — what Cambridge sets: Paper 1 is 30, each Paper 2
    section is 20, so Paper 2 is 60 and the AS aggregate is 90.
  * `set_marks` — what this sitting actually put in front of the student,
    which is smaller whenever the bank could not supply a full paper.

Scoring only against `set_marks` flatters: 34/40 reads as 85% when the paper
is out of 60 and the student answered 57% of it. Scoring only against
`official_marks` blames the student for questions nobody asked. So both are
computed, the official total is the headline (a paper is out of 60 whether or
not the bank was ready), and any shortfall is stated in marks rather than
buried in a percentage.

Nothing here touches Streamlit, the database or a model. It takes awarded and
set marks per component and does arithmetic — the same invariant as everywhere
else in this project: the model judges, the code counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ..syllabus import assessment

# Mock stage key -> (paper key, section key). The stage keys are the strings
# the Mock Test page already uses for its flow, so the page needs no
# translation table of its own.
COMPONENTS: dict[str, tuple[str, str]] = {
    "paper1": ("paper_1", "mcq"),
    "section_a": ("paper_2", "A"),
    "section_b": ("paper_2", "B"),
    "section_c": ("paper_2", "C"),
}

COMPONENT_LABELS = {
    "paper1": "Paper 1 — Multiple Choice",
    "section_a": "Section A — Data response",
    "section_b": "Section B — Micro essay",
    "section_c": "Section C — Macro essay",
}

# Which components each choice on the setup screen puts in the sitting.
EXAM_TYPES: dict[str, tuple[str, ...]] = {
    "paper1": ("paper1",),
    "paper2": ("section_a", "section_b", "section_c"),
    "full": ("paper1", "section_a", "section_b", "section_c"),
}


class MockReportError(ValueError):
    pass


def official_marks(component: str) -> int:
    """What Cambridge sets for this component, read from the syllabus data."""
    try:
        paper_key, section_key = COMPONENTS[component]
    except KeyError:
        raise MockReportError(f"unknown mock component {component!r}") from None
    paper = assessment.PAPERS[paper_key]
    for section in paper.sections:
        if section.key == section_key:
            return section.marks
    raise MockReportError(f"{paper_key} has no section {section_key!r}")


def _percent(awarded: float, out_of: float) -> float:
    return round(100.0 * awarded / out_of, 1) if out_of else 0.0


@dataclass(frozen=True)
class ComponentScore:
    key: str
    label: str
    paper_key: str
    official_marks: int
    set_marks: int
    awarded: float
    sat: bool

    @property
    def not_set(self) -> int:
        """Marks Cambridge sets that this sitting never asked for."""
        return max(0, self.official_marks - self.set_marks)

    @property
    def is_full(self) -> bool:
        return self.sat and self.not_set == 0

    @property
    def percent(self) -> float:
        """Against the official total — the honest headline."""
        return _percent(self.awarded, self.official_marks)

    @property
    def percent_of_set(self) -> float:
        """Against what was actually asked — fair to the student, not to the paper."""
        return _percent(self.awarded, self.set_marks)


@dataclass(frozen=True)
class PaperScore:
    paper_key: str
    label: str
    minutes: int
    percent_of_as: int
    components: tuple[ComponentScore, ...]

    @property
    def official_marks(self) -> int:
        return sum(c.official_marks for c in self.components)

    @property
    def set_marks(self) -> int:
        return sum(c.set_marks for c in self.components)

    @property
    def awarded(self) -> float:
        return sum(c.awarded for c in self.components)

    @property
    def sat(self) -> bool:
        return any(c.sat for c in self.components)

    @property
    def is_full(self) -> bool:
        """Every component sat, and every mark of each one set."""
        return bool(self.components) and all(c.is_full for c in self.components)

    @property
    def not_set(self) -> int:
        return sum(c.not_set for c in self.components)

    @property
    def percent(self) -> float:
        return _percent(self.awarded, self.official_marks)

    @property
    def percent_of_set(self) -> float:
        return _percent(self.awarded, self.set_marks)

    @property
    def skipped(self) -> tuple[ComponentScore, ...]:
        return tuple(c for c in self.components if not c.sat)

    @property
    def short(self) -> tuple[ComponentScore, ...]:
        """Sat, but with fewer marks set than Cambridge would set."""
        return tuple(c for c in self.components if c.sat and c.not_set)


@dataclass(frozen=True)
class MockScore:
    exam_type: str
    papers: tuple[PaperScore, ...]

    @property
    def official_marks(self) -> int:
        return sum(p.official_marks for p in self.papers)

    @property
    def set_marks(self) -> int:
        return sum(p.set_marks for p in self.papers)

    @property
    def awarded(self) -> float:
        return sum(p.awarded for p in self.papers)

    @property
    def percent(self) -> float:
        return _percent(self.awarded, self.official_marks)

    @property
    def percent_of_set(self) -> float:
        return _percent(self.awarded, self.set_marks)

    @property
    def is_full(self) -> bool:
        return bool(self.papers) and all(p.is_full for p in self.papers)

    @property
    def covers_whole_as(self) -> bool:
        """Both papers in the sitting — 30 + 60 = the whole AS aggregate.

        Paper 1 is 33% of the award and Paper 2 the other 67%, and the raw
        marks are already in that ratio, so the aggregate percentage needs no
        weighting: 90 marks IS the AS total.
        """
        return {p.paper_key for p in self.papers} == set(assessment.PAPERS)

    @property
    def gradeable(self) -> bool:
        """Whether a grade estimate off this sitting means anything.

        A grade is awarded on the whole AS aggregate. Reporting one off a
        single paper, or off a paper the bank could only half fill, would put
        a letter on something that is not the thing the letter describes.
        """
        return self.covers_whole_as and self.is_full

    def paper(self, paper_key: str) -> PaperScore | None:
        return next((p for p in self.papers if p.paper_key == paper_key), None)

    def component(self, key: str) -> ComponentScore | None:
        for paper in self.papers:
            for component in paper.components:
                if component.key == key:
                    return component
        return None


def build_report(
    exam_type: str, sat: Mapping[str, tuple[float, int]]
) -> MockScore:
    """Assemble the report.

    `sat` maps a component key to (marks awarded, marks actually set). A
    component in this exam type but missing from `sat` was skipped — the bank
    had nothing to serve — and is reported as 0 out of its official marks,
    not quietly dropped from the denominator.
    """
    if exam_type not in EXAM_TYPES:
        raise MockReportError(f"unknown exam type {exam_type!r}")
    unknown = set(sat) - set(EXAM_TYPES[exam_type])
    if unknown:
        raise MockReportError(
            "results for components not in this sitting: " + ", ".join(sorted(unknown))
        )

    wanted = EXAM_TYPES[exam_type]
    by_paper: dict[str, list[ComponentScore]] = {}
    for key in wanted:
        paper_key, _ = COMPONENTS[key]
        awarded, set_marks = sat.get(key, (0.0, 0))
        by_paper.setdefault(paper_key, []).append(
            ComponentScore(
                key=key,
                label=COMPONENT_LABELS[key],
                paper_key=paper_key,
                official_marks=official_marks(key),
                set_marks=int(set_marks),
                awarded=float(awarded),
                sat=key in sat,
            )
        )

    papers = []
    for paper_key, components in by_paper.items():
        paper = assessment.PAPERS[paper_key]
        papers.append(
            PaperScore(
                paper_key=paper_key,
                label=paper.label,
                minutes=paper.minutes,
                percent_of_as=paper.percent_of_as,
                components=tuple(components),
            )
        )
    papers.sort(key=lambda p: p.paper_key)
    return MockScore(exam_type=exam_type, papers=tuple(papers))


def shortfall_notes(mock: MockScore) -> list[str]:
    """Plain sentences naming every mark the sitting could not set.

    Written here rather than in the page so the wording is testable and the
    same whichever screen reports it.
    """
    notes: list[str] = []
    for paper in mock.papers:
        for component in paper.skipped:
            notes.append(
                f"{component.label} was not sat — nothing was banked for this "
                f"selection, so {component.official_marks} marks of "
                f"{paper.label} could not be attempted."
            )
        for component in paper.short:
            notes.append(
                f"{component.label} set {component.set_marks} of its "
                f"{component.official_marks} marks — the bank was "
                f"{component.not_set} short."
            )
    return notes
