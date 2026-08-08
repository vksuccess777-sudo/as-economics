"""Diagrams, handled by declaration rather than by looking at a drawing.

This closes the gap recorded in the README. AS Economics answers lean on
labelled diagrams — supply and demand, PPC, AD/AS, external cost and benefit —
and a text-only marker is blind to them. Three options were on the table:

  1. Ignore diagrams. Rejected: the marker would systematically over-reward
     prose and under-reward the student who did the right thing on paper.
  2. Photograph the diagram and mark it with a vision model. Rejected for now:
     hand-drawn axes and shifted curves are exactly the case vision models read
     unreliably, and a confidently wrong reading of a correct diagram is worse
     than no reading at all.
  3. Ask the student to DECLARE the diagram in structured form: which diagram,
     which curve moves, in which direction, and what happens to each axis
     variable. Checked deterministically against the question's expected spec.

Option 3 is implemented here. It costs nothing, it is unambiguous, and the
declaration itself is the discipline the mark scheme rewards — naming the shift,
its direction, and the resulting movement in each axis variable. The student
still draws the diagram on paper; the declaration is what the marker can see,
and the tool says so plainly rather than pretending to have seen the drawing.

The consequence is enforced in code, not by the model: if a question requires a
diagram and the declaration is missing or wrong, AO2 is capped. A model asked
to be strict about a missing diagram will forgive a fluent answer; a cap will
not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..diagrams.catalogue import CATALOGUE

# Diagram vocabulary, DERIVED from the rendering catalogue rather than written
# out here. The previous hand-written version offered `external_cost` and
# `external_benefit` as AS content; externalities are A Level (topic 7.4) in
# the 2026-2028 syllabus and the word appears nowhere in the AS spine. A
# student could have been offered — and this marker could have capped AO2 for
# not drawing — a diagram off their course.
#
# Deriving it means the declaration dropdown, the marker's context and the
# thing actually drawn on screen cannot disagree, and `diagrams.scope` filters
# the catalogue against the parsed syllabus.
DIAGRAM_TYPES: dict[str, dict[str, str]] = {
    entry.key: {
        "label": entry.label,
        "x_axis": entry.x_axis,
        "y_axis": entry.y_axis,
    }
    for entry in CATALOGUE
}

# Keys written into question rubrics before the catalogue existed. Accepted so
# an older banked essay still validates; never offered in the UI.
LEGACY_ALIASES = {
    "price_ceiling": "maximum_price",
    "price_floor": "minimum_price",
}


def canonical_type(key: str) -> str:
    return LEGACY_ALIASES.get((key or "").strip(), (key or "").strip())


CURVES = (
    "demand", "supply", "AD", "SRAS", "LRAS", "PPC",
)
DIRECTIONS = ("right", "left", "none")
EFFECTS = ("rise", "fall", "unchanged", "indeterminate")

# The cap applied when a required diagram is absent or materially wrong.
# Level 1 on the AO2 ladder: a chain of reasoning was attempted but is
# incomplete — which is exactly what an answer missing its diagram is.
AO2_CAP_NO_DIAGRAM = 1
AO2_CAP_WRONG_DIAGRAM = 1
AO2_CAP_WRONG_DIRECTION = 2


@dataclass(frozen=True)
class Shift:
    curve: str
    direction: str  # right | left | none

    def normalised(self) -> "Shift":
        return Shift(self.curve.strip().upper(), self.direction.strip().lower())

    def as_dict(self) -> dict[str, str]:
        return {"curve": self.curve, "direction": self.direction}


@dataclass(frozen=True)
class DiagramSpec:
    """What the question expects. Stored in question.rubric as JSON."""

    diagram_type: str
    shifts: tuple[Shift, ...] = ()
    effects: dict[str, str] = field(default_factory=dict)  # axis variable -> EFFECTS
    required: bool = True

    @classmethod
    def from_dict(cls, raw: dict | None) -> "DiagramSpec | None":
        if not raw:
            return None
        return cls(
            diagram_type=str(raw.get("diagram_type", "")),
            shifts=tuple(
                Shift(str(s.get("curve", "")), str(s.get("direction", "none")))
                for s in raw.get("shifts", [])
            ),
            effects={str(k): str(v) for k, v in (raw.get("effects") or {}).items()},
            required=bool(raw.get("required", True)),
        )

    def as_dict(self) -> dict:
        return {
            "diagram_type": self.diagram_type,
            "shifts": [s.as_dict() for s in self.shifts],
            "effects": dict(self.effects),
            "required": self.required,
        }

    @property
    def label(self) -> str:
        return DIAGRAM_TYPES.get(self.diagram_type, {}).get(
            "label", self.diagram_type or "diagram"
        )


@dataclass(frozen=True)
class DiagramDeclaration:
    """What the student says they drew."""

    diagram_type: str
    shifts: tuple[Shift, ...] = ()
    effects: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict | None) -> "DiagramDeclaration | None":
        if not raw:
            return None
        return cls(
            diagram_type=str(raw.get("diagram_type", "")),
            shifts=tuple(
                Shift(str(s.get("curve", "")), str(s.get("direction", "none")))
                for s in raw.get("shifts", [])
            ),
            effects={str(k): str(v) for k, v in (raw.get("effects") or {}).items()},
        )

    def as_dict(self) -> dict:
        return {
            "diagram_type": self.diagram_type,
            "shifts": [s.as_dict() for s in self.shifts],
            "effects": dict(self.effects),
        }


@dataclass
class DiagramCheck:
    """Deterministic verdict. No model involved anywhere in this file."""

    required: bool
    declared: bool
    type_correct: bool = False
    shifts_correct: bool = False
    effects_correct: bool = False
    ao2_cap: int | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def fully_correct(self) -> bool:
        return (
            self.declared
            and self.type_correct
            and self.shifts_correct
            and self.effects_correct
        )

    def summary(self) -> str:
        """One line, written for the marker's context and for the student."""
        if not self.required:
            return "No diagram was required for this question."
        if not self.declared:
            return "A diagram was required and none was declared."
        if self.fully_correct:
            return "A correct diagram was declared: type, shifts and effects all match."
        return "A diagram was declared but it is wrong: " + "; ".join(self.notes)


def _norm_shifts(shifts: tuple[Shift, ...]) -> set[tuple[str, str]]:
    return {(s.curve.strip().upper(), s.direction.strip().lower()) for s in shifts}


def check_diagram(
    spec: DiagramSpec | None, declaration: DiagramDeclaration | None
) -> DiagramCheck:
    if spec is None or not spec.required:
        return DiagramCheck(required=False, declared=declaration is not None)

    if declaration is None or not declaration.diagram_type:
        return DiagramCheck(
            required=True,
            declared=False,
            ao2_cap=AO2_CAP_NO_DIAGRAM,
            notes=[f"expected a {spec.label} diagram"],
        )

    check = DiagramCheck(required=True, declared=True)
    check.type_correct = (
        declaration.diagram_type.strip().lower() == spec.diagram_type.strip().lower()
    )
    if not check.type_correct:
        check.notes.append(
            f"wrong diagram — expected {spec.label}, declared "
            f"{DIAGRAM_TYPES.get(declaration.diagram_type, {}).get('label', declaration.diagram_type)}"
        )
        check.ao2_cap = AO2_CAP_WRONG_DIAGRAM
        return check  # nothing below this is meaningful on the wrong diagram

    expected_shifts = _norm_shifts(spec.shifts)
    declared_shifts = _norm_shifts(declaration.shifts)
    check.shifts_correct = expected_shifts == declared_shifts

    if not check.shifts_correct:
        expected_curves = {c for c, _ in expected_shifts}
        declared_curves = {c for c, _ in declared_shifts}
        wrong_direction = {
            c for c in expected_curves & declared_curves
            if dict(expected_shifts).get(c) != dict(declared_shifts).get(c)
        }
        if wrong_direction:
            check.notes.append(
                "shift in the wrong direction: " + ", ".join(sorted(wrong_direction))
            )
        missing = expected_curves - declared_curves
        if missing:
            check.notes.append("curve not shifted: " + ", ".join(sorted(missing)))
        extra = declared_curves - expected_curves
        if extra:
            check.notes.append("curve shifted that should not move: " + ", ".join(sorted(extra)))

    check.effects_correct = all(
        declaration.effects.get(var, "").strip().lower() == want.strip().lower()
        for var, want in spec.effects.items()
    )
    if not check.effects_correct:
        wrong = [
            f"{var} should {want}, declared {declaration.effects.get(var, 'nothing')}"
            for var, want in spec.effects.items()
            if declaration.effects.get(var, "").strip().lower() != want.strip().lower()
        ]
        check.notes.append("; ".join(wrong))

    if not check.fully_correct:
        check.ao2_cap = AO2_CAP_WRONG_DIRECTION
    return check


def apply_cap(levels: dict[str, int], check: DiagramCheck) -> tuple[dict[str, int], str | None]:
    """Enforce the diagram consequence on the model's levels.

    Returns the capped levels and a note explaining any change. The model is
    never asked to police this; a fluent answer talks a model out of strictness
    and cannot talk a comparison operator out of it.
    """
    if check.ao2_cap is None:
        return dict(levels), None
    current = int(levels.get("AO2", 0))
    if current <= check.ao2_cap:
        return dict(levels), None
    capped = dict(levels)
    capped["AO2"] = check.ao2_cap
    return capped, (
        f"AO2 capped at level {check.ao2_cap} (from {current}): {check.summary()}"
    )
