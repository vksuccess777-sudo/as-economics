"""The diagrams have to be right, and a student cannot check them.

The load-bearing tests here are the agreement ones: a caption saying "price
rises" must come from the same computed point as the line that was drawn. A
renderer that quietly draws a leftward shift under a rightward caption would
teach a student to lose marks, and it would look fine.
"""

from __future__ import annotations

import re

import pytest

from src.config import settings
from src.diagrams import scope
from src.diagrams.canvas import (
    HEIGHT,
    WIDTH,
    Canvas,
    DiagramError,
    Line,
    Point,
    intersect,
)
from src.diagrams.catalogue import (
    AD,
    CATALOGUE,
    DEMAND,
    SUPPLY,
    BY_KEY,
    DiagramEntry,
    ad_as,
    render,
    supply_demand,
)
from src.marking.diagram import DIAGRAM_TYPES, canonical_type
from src.syllabus.models import SyllabusSpine


# ------------------------------------------------------------- geometry


def test_two_lines_cross_where_the_algebra_says():
    up = Line(Point(0, 0), Point(100, 100))
    down = Line(Point(0, 100), Point(100, 0))
    crossing = intersect(up, down)
    assert crossing.x == pytest.approx(50)
    assert crossing.y == pytest.approx(50)


def test_parallel_lines_are_an_error_not_a_guess():
    a = Line(Point(0, 0), Point(100, 50))
    b = Line(Point(0, 20), Point(100, 70))
    with pytest.raises(DiagramError):
        intersect(a, b)


def test_a_vertical_line_still_crosses_a_sloping_one():
    vertical = Line(Point(60, 0), Point(60, 100))
    crossing = intersect(vertical, DEMAND)
    assert crossing.x == pytest.approx(60)
    assert crossing.y == pytest.approx(DEMAND.y_at(60))


def test_shifting_right_moves_every_point_right():
    moved = DEMAND.shifted(18)
    assert moved.a.x == DEMAND.a.x + 18
    assert moved.b.x == DEMAND.b.x + 18


def test_the_canvas_puts_the_origin_at_the_bottom_left():
    c = Canvas("q", "p")
    assert c.py(0) > c.py(100)      # y grows upward on screen
    assert c.px(0) < c.px(100)


# --------------------------------------------- the direction actually drawn


def _lines(svg: str) -> list[tuple[float, float, float, float]]:
    return [
        tuple(float(v) for v in m)
        for m in re.findall(
            r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"',
            svg,
        )
    ]


def _dashed_line(svg: str) -> tuple[float, float, float, float]:
    """The shifted curve is the only solid dashed 2px line."""
    match = re.search(
        r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)" '
        # Stroke width is a styling choice and must not be part of the match,
        # or a legibility tweak silently turns this into "no curve found".
        r'stroke="#[0-9A-Fa-f]{6}" stroke-width="[\d.]+" fill="none" stroke-dasharray',
        svg,
    )
    assert match, "no shifted curve found"
    return tuple(float(v) for v in match.groups())


def test_a_rightward_demand_shift_is_drawn_above_a_leftward_one():
    """Curves are clipped to the plot width, so a horizontal shift of a
    downward-sloping curve shows up as a vertical difference on screen. A
    right-shifted demand curve sits HIGHER — smaller y in SVG pixels — at
    every x. Asserting on x here would pass trivially and prove nothing."""
    right = _dashed_line(supply_demand(shift="demand", direction="right"))
    left = _dashed_line(supply_demand(shift="demand", direction="left"))
    assert right[1] < left[1], "right shift is not drawn above the left shift"
    assert right[3] < left[3]


def test_the_shift_is_horizontal_in_data_space():
    """The screen check above is the consequence; this is the cause."""
    assert DEMAND.shifted(18).y_at(50) > DEMAND.y_at(50)
    assert DEMAND.shifted(-18).y_at(50) < DEMAND.y_at(50)


def test_a_rightward_demand_shift_raises_price_and_quantity():
    svg = supply_demand(shift="demand", direction="right")
    assert "price rises" in svg
    assert "quantity rises" in svg


def test_a_leftward_demand_shift_lowers_both():
    svg = supply_demand(shift="demand", direction="left")
    assert "price falls" in svg
    assert "quantity falls" in svg


def test_a_rightward_supply_shift_lowers_price_and_raises_quantity():
    """The one students most often get backwards."""
    svg = supply_demand(shift="supply", direction="right")
    assert "price falls" in svg
    assert "quantity rises" in svg


def test_the_caption_and_the_intersection_cannot_disagree():
    """Both come from the same computed point, so this is structural."""
    moved = DEMAND.shifted(18)
    before = intersect(DEMAND, SUPPLY)
    after = intersect(moved, SUPPLY)
    assert after.y > before.y
    assert "price rises" in supply_demand(shift="demand", direction="right")


def test_ad_shifting_right_raises_the_price_level_and_output():
    svg = ad_as(shift="AD", direction="right")
    assert "price level rises" in svg
    assert "real output rises" in svg


def test_sras_shifting_left_raises_prices_and_cuts_output():
    """Stagflation, and the sign error is easy to make."""
    svg = ad_as(shift="SRAS", direction="left")
    assert "price level rises" in svg
    assert "real output falls" in svg


def test_an_unknown_direction_is_rejected():
    with pytest.raises(DiagramError):
        supply_demand(shift="demand", direction="sideways")


def test_an_unknown_diagram_is_rejected():
    with pytest.raises(DiagramError):
        render("externality")


# --------------------------------------------------------- every diagram


@pytest.mark.parametrize("entry", CATALOGUE, ids=lambda e: e.key)
def test_every_diagram_renders_valid_svg(entry: DiagramEntry):
    import xml.etree.ElementTree as ET

    kwargs = {"direction": "right"} if "direction" in entry.options else {}
    svg = entry.render(**kwargs)
    root = ET.fromstring(svg)          # raises if malformed
    assert root.tag.endswith("svg")
    assert root.attrib["role"] == "img"
    assert root.find("{http://www.w3.org/2000/svg}title") is not None


@pytest.mark.parametrize("entry", CATALOGUE, ids=lambda e: e.key)
def test_nothing_is_drawn_outside_the_viewbox(entry: DiagramEntry):
    kwargs = {"direction": "right"} if "direction" in entry.options else {}
    svg = entry.render(**kwargs)
    for x1, y1, x2, y2 in _lines(svg):
        # Read from the canvas, not hardcoded: resizing for legibility should
        # not require editing this test, only re-running it.
        for value in (x1, x2):
            assert -1 <= value <= WIDTH + 1, f"{entry.key} draws off the left/right edge"
        for value in (y1, y2):
            assert -1 <= value <= HEIGHT + 1, f"{entry.key} draws off the top/bottom edge"


@pytest.mark.parametrize("entry", CATALOGUE, ids=lambda e: e.key)
def test_every_diagram_labels_both_axes_or_is_a_schematic(entry: DiagramEntry):
    svg = entry.render(**({"direction": "right"} if "direction" in entry.options else {}))
    if entry.x_axis == "—":
        return
    assert entry.x_axis.split()[0].lower() in svg.lower()


def test_every_option_value_renders():
    for entry in CATALOGUE:
        for name, values in entry.options.items():
            for value in values:
                assert entry.render(**{name: value}).startswith("<svg")


# --------------------------------------------------------------- scope


def _spine() -> SyllabusSpine:
    if not settings.spine_path.exists():
        pytest.skip("needs a parsed spine — local to the user's machine")
    return SyllabusSpine.load(settings.spine_path)


def test_the_offered_set_comes_from_the_spine():
    spine = _spine()
    keys = {entry.key for entry in scope.in_scope(spine)}
    assert "supply_demand" in keys
    assert "ad_as" in keys
    assert "ppc" in keys


def test_an_a_level_diagram_would_be_dropped():
    """The bug this whole mechanism exists for.

    Externalities are A Level (topic 7.4) in the 2026-2028 syllabus and the
    word appears nowhere in the AS spine, so an entry requiring it must not
    survive the gate — however plausible it looks in the catalogue.
    """
    spine = _spine()
    fake = DiagramEntry(
        key="external_cost", label="Negative externality",
        topics=("3.1",), requires=("externality",), build=lambda: "<svg/>",
    )
    from src.diagrams import catalogue as module

    original = module.CATALOGUE
    module.CATALOGUE = original + (fake,)
    try:
        keys = {entry.key for entry in scope.in_scope(spine)}
    finally:
        module.CATALOGUE = original
    assert "external_cost" not in keys


def test_externality_diagrams_are_gone_from_the_marker_vocabulary():
    assert "external_cost" not in DIAGRAM_TYPES
    assert "external_benefit" not in DIAGRAM_TYPES


def test_older_rubric_keys_still_resolve():
    assert canonical_type("price_ceiling") == "maximum_price"
    assert canonical_type("price_floor") == "minimum_price"
    assert canonical_type("supply_demand") == "supply_demand"


def test_the_marker_vocabulary_is_exactly_the_catalogue():
    """Declaration dropdown, marker context and what is drawn cannot diverge."""
    assert set(DIAGRAM_TYPES) == set(BY_KEY)


def test_topics_route_to_the_right_diagram():
    spine = _spine()
    assert "ppc" in [e.key for e in scope.for_topic(spine, "1.5")]
    assert "ad_as" in [e.key for e in scope.for_topic(spine, "4.3")]
    assert "ad_as" in [e.key for e in scope.for_topic(spine, "4.3.2")]
    assert "exchange_rate" in [e.key for e in scope.for_topic(spine, "6.4")]


def test_an_unknown_topic_returns_nothing_rather_than_guessing():
    assert scope.for_topic(_spine(), "99.9") == ()
    assert scope.for_topic(_spine(), "") == ()


def test_every_catalogue_topic_exists_in_the_spine():
    """A diagram registered against a topic Cambridge does not have is a typo."""
    spine = _spine()
    codes = {t.code for t in spine.iter_topics()}
    for entry in CATALOGUE:
        for topic in entry.topics:
            assert topic in codes, f"{entry.key} points at missing topic {topic}"


# ------------------------------------------------------------- ranking


def test_the_diagram_the_question_is_about_comes_first():
    """Topic 3.2 carries five diagrams. Catalogue order showed the tax
    diagram for "what is a maximum price", which is worse than showing none."""
    spine = _spine()
    candidates = scope.for_topic(spine, "3.2")
    assert len(candidates) >= 4
    ranked = scope.rank_for_question(candidates, "what is a maximum price")
    assert ranked[0].key == "maximum_price"
    ranked = scope.rank_for_question(candidates, "how does a subsidy work")
    assert ranked[0].key == "subsidy"
    ranked = scope.rank_for_question(candidates, "explain buffer stock schemes")
    assert ranked[0].key == "buffer_stock"


def test_ranking_keeps_every_candidate():
    spine = _spine()
    candidates = scope.for_topic(spine, "3.2")
    # DiagramEntry carries an options dict, so it is unhashable — compare keys.
    ranked = [e.key for e in scope.rank_for_question(candidates, "anything")]
    assert sorted(ranked) == sorted(e.key for e in candidates)


def test_ranking_survives_an_empty_question():
    spine = _spine()
    candidates = scope.for_topic(spine, "3.2")
    assert len(scope.rank_for_question(candidates, "")) == len(candidates)
