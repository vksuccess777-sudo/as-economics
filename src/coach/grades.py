"""Target grades, and what the gap to one actually is.

Two facts this module exists to keep straight, both easy to get wrong:

1. **Cambridge International AS Level has no A\\*.** AS grades run a to e.
   A* exists only on the full A Level, awarded on the aggregate of AS and A2
   components together. Aiming a Year 12 student at "A* in AS Economics" aims
   at something that cannot be awarded. The equivalent target at AS is grade
   **a**, and that is what this module reports against.

2. **Grade thresholds are set per session, after the exam.** They move with the
   difficulty of that paper — sometimes by several marks. Any threshold used
   before results day is an estimate, and this module labels it as one
   everywhere it appears.

The bands live in a JSON file with a `provenance` field, the same posture as
the levels ladder: replace the shipped estimates with real published thresholds
for your exam years and the label changes automatically.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

DEFAULT_GRADES_DIR = Path(__file__).resolve().parents[2] / "data" / "grades"
USER_FILE = "as_thresholds.json"
INTERIM_FILE = "as_thresholds.example.json"

AS_GRADES = ("a", "b", "c", "d", "e")

NO_A_STAR_NOTE = (
    "Cambridge International AS Level is graded a to e. There is no A* at AS — "
    "A* is awarded on the full A Level aggregate only. The top AS grade, and "
    "the right target here, is grade a."
)


class GradeError(ValueError):
    pass


@dataclass(frozen=True)
class GradeModel:
    provenance: str
    source: str
    thresholds: dict[str, float]  # grade -> minimum percent

    @property
    def is_official(self) -> bool:
        return self.provenance != "estimate"

    def grade_for(self, percent: float) -> str | None:
        for grade in AS_GRADES:
            if percent >= self.thresholds[grade]:
                return grade
        return None  # below grade e

    def threshold(self, grade: str) -> float:
        grade = normalise_target(grade)
        return self.thresholds[grade]

    def next_grade_up(self, percent: float) -> str | None:
        current = self.grade_for(percent)
        if current is None:
            return "e"
        idx = AS_GRADES.index(current)
        return AS_GRADES[idx - 1] if idx > 0 else None


def normalise_target(grade: str) -> str:
    """Accept what a parent would type, reject what cannot be awarded."""
    cleaned = (grade or "").strip().lower().replace("grade", "").strip()
    if cleaned in {"a*", "a star", "astar", "a-star"}:
        raise GradeError(NO_A_STAR_NOTE)
    if cleaned not in AS_GRADES:
        raise GradeError(f"{grade!r} is not an AS grade. Use one of: a, b, c, d, e.")
    return cleaned


def load_grades(path: str | Path) -> GradeModel:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    thresholds = {str(k).lower(): float(v) for k, v in (raw.get("thresholds") or {}).items()}

    missing = [g for g in AS_GRADES if g not in thresholds]
    if missing:
        raise GradeError(f"thresholds file is missing grades: {', '.join(missing)}")
    ordered = [thresholds[g] for g in AS_GRADES]
    if ordered != sorted(ordered, reverse=True):
        raise GradeError(
            "thresholds are not in descending order a > b > c > d > e — "
            f"got {ordered}"
        )
    if "a*" in thresholds or "a star" in thresholds:
        raise GradeError("thresholds file defines A*, which AS Level does not award")

    return GradeModel(
        provenance=str(raw.get("provenance", "estimate")),
        source=str(raw.get("source", "")),
        thresholds=thresholds,
    )


def resolve_grades_path(grades_dir: str | Path | None = None) -> Path:
    directory = Path(grades_dir or DEFAULT_GRADES_DIR)
    user = directory / USER_FILE
    return user if user.exists() else directory / INTERIM_FILE


def default_grades(grades_dir: str | Path | None = None) -> GradeModel:
    return load_grades(resolve_grades_path(grades_dir))


@dataclass
class GradeGap:
    """Where the student is, where the target is, and the distance in marks."""

    target: str
    target_percent: float
    current_percent: float
    projected_grade: str | None
    gap_percentage_points: float
    marks_per_paper_1: int      # extra MCQs needed out of 30
    marks_per_paper_2: int      # extra marks needed out of 60
    evidence_marks: float
    is_official: bool

    @property
    def already_there(self) -> bool:
        return self.gap_percentage_points <= 0

    @property
    def confidence_note(self) -> str:
        if self.evidence_marks < 30:
            return (
                f"Based on {self.evidence_marks:g} marks of evidence — too few to "
                "project a grade from. Treat it as a direction, not a prediction."
            )
        if not self.is_official:
            return (
                "Grade thresholds are estimates. Cambridge sets the real ones "
                "per session, after the exam."
            )
        return "Thresholds are the published ones for the stated session."


def gap_to_target(
    model: GradeModel, current_percent: float, target: str, evidence_marks: float = 0.0
) -> GradeGap:
    target = normalise_target(target)
    target_pct = model.threshold(target)
    gap = round(target_pct - current_percent, 1)
    return GradeGap(
        target=target,
        target_percent=target_pct,
        current_percent=round(current_percent, 1),
        projected_grade=model.grade_for(current_percent),
        gap_percentage_points=gap,
        # The AS award is Paper 1 (30 marks) + Paper 2 (60 marks) = 90.
        # Rounded UP, always. Half a mark cannot be scored, and rounding a gap
        # down tells a student they need less than they do — the one direction
        # this number must never be wrong in.
        marks_per_paper_1=max(0, math.ceil(30 * gap / 100)),
        marks_per_paper_2=max(0, math.ceil(60 * gap / 100)),
        evidence_marks=evidence_marks,
        is_official=model.is_official,
    )
