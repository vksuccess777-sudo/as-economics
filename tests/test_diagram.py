"""Diagram checking is deterministic, so every case here is exact."""

from __future__ import annotations

from src.marking.diagram import (
    AO2_CAP_NO_DIAGRAM,
    DiagramDeclaration,
    DiagramSpec,
    Shift,
    apply_cap,
    check_diagram,
)

SPEC = DiagramSpec(
    diagram_type="supply_demand",
    shifts=(Shift("demand", "right"),),
    effects={"price": "rise", "quantity": "rise"},
    required=True,
)

CORRECT = DiagramDeclaration(
    diagram_type="supply_demand",
    shifts=(Shift("demand", "right"),),
    effects={"price": "rise", "quantity": "rise"},
)


def test_correct_declaration_passes():
    check = check_diagram(SPEC, CORRECT)
    assert check.fully_correct
    assert check.ao2_cap is None


def test_missing_declaration_caps_ao2():
    check = check_diagram(SPEC, None)
    assert check.declared is False
    assert check.ao2_cap == AO2_CAP_NO_DIAGRAM


def test_no_diagram_required_means_no_cap():
    check = check_diagram(None, None)
    assert check.required is False
    assert check.ao2_cap is None


def test_wrong_diagram_type_short_circuits():
    """Shifts on the wrong diagram are meaningless, so they are not reported."""
    check = check_diagram(SPEC, DiagramDeclaration(diagram_type="ad_as"))
    assert check.type_correct is False
    assert check.shifts_correct is False
    assert any("wrong diagram" in n for n in check.notes)


def test_shift_in_the_wrong_direction_is_named():
    wrong = DiagramDeclaration(
        diagram_type="supply_demand",
        shifts=(Shift("demand", "left"),),
        effects={"price": "rise", "quantity": "rise"},
    )
    check = check_diagram(SPEC, wrong)
    assert check.shifts_correct is False
    assert any("wrong direction" in n for n in check.notes)


def test_shifting_a_curve_that_should_not_move_is_caught():
    """The classic error: shifting both curves when only demand moved."""
    both = DiagramDeclaration(
        diagram_type="supply_demand",
        shifts=(Shift("demand", "right"), Shift("supply", "right")),
        effects={"price": "rise", "quantity": "rise"},
    )
    check = check_diagram(SPEC, both)
    assert check.shifts_correct is False
    assert any("should not move" in n for n in check.notes)


def test_curve_name_case_and_spacing_do_not_matter():
    """A student picking 'Demand' must not be marked wrong on capitalisation."""
    check = check_diagram(
        SPEC,
        DiagramDeclaration(
            diagram_type="supply_demand",
            shifts=(Shift(" Demand ", "Right"),),
            effects={"price": "RISE", "quantity": "rise"},
        ),
    )
    assert check.fully_correct


def test_right_shift_wrong_effect_is_caught():
    """Shift right but says price falls — the reasoning, not the drawing, is wrong."""
    wrong = DiagramDeclaration(
        diagram_type="supply_demand",
        shifts=(Shift("demand", "right"),),
        effects={"price": "fall", "quantity": "rise"},
    )
    check = check_diagram(SPEC, wrong)
    assert check.shifts_correct is True
    assert check.effects_correct is False


def test_cap_lowers_ao2_and_explains_itself():
    check = check_diagram(SPEC, None)
    capped, note = apply_cap({"AO1": 3, "AO2": 3}, check)
    assert capped["AO2"] == AO2_CAP_NO_DIAGRAM
    assert capped["AO1"] == 3, "the cap touches AO2 only"
    assert note and "capped" in note


def test_cap_never_raises_a_level():
    """A cap is a ceiling. A student already below it is not lifted to it."""
    check = check_diagram(SPEC, None)
    capped, note = apply_cap({"AO1": 1, "AO2": 0}, check)
    assert capped["AO2"] == 0
    assert note is None
