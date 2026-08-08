"""Every diagram Cambridge AS Economics 9708 actually asks for.

Each entry names the syllabus topics it belongs to and the terms that must
appear in the parsed spine for it to be in scope. That second field is the
important one: `scope.py` uses it to derive the offered set from
`data/syllabus_spine.json` rather than from this list, so a syllabus revision
changes what is offered with no code change.

That mechanism is here because the previous hand-written diagram list was
wrong. It offered external cost and external benefit diagrams as AS content;
they are A Level (topic 7.4) in the 2026-2028 syllabus, and "externality"
appears nowhere in the AS spine. A student could have been shown — and the
essay marker could have required — a diagram off their course.

Every builder returns SVG text with all coordinates computed. Where a
diagram has a direction ("demand rises", "AD shifts left"), the caption is
generated from the SAME computed points as the lines, so the two cannot
disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .canvas import (
    AMBER,
    BLUE,
    CORAL,
    PURPLE,
    TEAL,
    Canvas,
    DiagramError,
    Line,
    Point,
    intersect,
)

# Reference curves in data space. Chosen so equilibrium sits near the middle
# and a shift either way stays on the page.
DEMAND = Line(Point(10, 85), Point(90, 15))
SUPPLY = Line(Point(10, 15), Point(90, 85))
AD = Line(Point(10, 85), Point(90, 15))
SRAS = Line(Point(10, 20), Point(90, 80))

DIRECTIONS = ("right", "left", "none")


def _direction_shift(direction: str, size: float = 18.0) -> float:
    if direction not in DIRECTIONS:
        raise DiagramError(f"direction must be one of {DIRECTIONS}, got {direction!r}")
    return {"right": size, "left": -size, "none": 0.0}[direction]


def _movement(before: float, after: float) -> str:
    if after > before + 0.01:
        return "rises"
    if after < before - 0.01:
        return "falls"
    return "is unchanged"


# ---------------------------------------------------------------- builders


def supply_demand(*, shift: str = "demand", direction: str = "right") -> str:
    """Demand and supply, with one curve shifted and the new equilibrium found."""
    if shift not in {"demand", "supply", "none"}:
        raise DiagramError("shift must be demand, supply or none")
    dx = _direction_shift(direction)
    demand, supply = DEMAND, SUPPLY
    if shift == "demand":
        moved = demand.shifted(dx)
    elif shift == "supply":
        moved = supply.shifted(dx)
    else:
        moved = None

    first = intersect(demand, supply)
    second = (
        intersect(moved, supply) if shift == "demand"
        else intersect(demand, moved) if shift == "supply"
        else first
    )

    c = Canvas("Quantity", "Price")
    c.axes()
    c.curve(demand, "D", BLUE)
    c.curve(supply, "S", TEAL)
    if moved is not None and dx:
        c.curve(moved, "D₁" if shift == "demand" else "S₁", CORAL, dashed=True)
    c.guides(first, "Q", "P")
    if dx:
        c.guides(second, "Q₁", "P₁")
        c.note(
            f"{shift.capitalize()} shifts {direction}: price {_movement(first.y, second.y)}, "
            f"quantity {_movement(first.x, second.x)}"
        )
    else:
        c.note("Equilibrium is where the two curves cross")
    return c.svg(
        "Demand and supply",
        f"Price against quantity. {shift} shifts {direction}.",
    )


def surplus() -> str:
    """Consumer and producer surplus as the two triangles about equilibrium."""
    eq = intersect(DEMAND, SUPPLY)
    c = Canvas("Quantity", "Price")
    c.axes()
    c.area(
        [Point(0, DEMAND.y_at(0)), Point(0, eq.y), eq],
        BLUE, "Consumer surplus",
    )
    c.area(
        [Point(0, SUPPLY.y_at(0)), Point(0, eq.y), eq],
        TEAL, "Producer surplus",
    )
    c.curve(DEMAND, "D", BLUE)
    c.curve(SUPPLY, "S", TEAL)
    c.guides(eq, "Q", "P")
    c.note("Above the price and under D; below the price and over S")
    return c.svg("Consumer and producer surplus", "Two triangles about equilibrium.")


def indirect_tax() -> str:
    """A specific indirect tax as a parallel upward shift of supply."""
    taxed = SUPPLY.raised(20)
    before = intersect(DEMAND, SUPPLY)
    after = intersect(DEMAND, taxed)
    producer = Point(after.x, SUPPLY.y_at(after.x))

    c = Canvas("Quantity", "Price")
    c.axes()
    c.curve(DEMAND, "D", BLUE)
    c.curve(SUPPLY, "S", TEAL)
    c.curve(taxed, "S + tax", CORAL, dashed=True)
    c.area([Point(0, producer.y), Point(0, after.y), after, producer],
           AMBER, "Tax", opacity=0.2)
    c.guides(before, "Q", "P")
    c.guides(after, "Q₁", "P₁")
    c.guides(producer, "", "P꜀")
    c.note("P₁ − P is borne by consumers; P − P꜀ by producers")
    return c.svg("Indirect tax", "Supply shifts up by the tax; incidence splits.")


def subsidy() -> str:
    """A subsidy as a parallel downward shift of supply."""
    aided = SUPPLY.raised(-20)
    before = intersect(DEMAND, SUPPLY)
    after = intersect(DEMAND, aided)
    producer = Point(after.x, SUPPLY.y_at(after.x))

    c = Canvas("Quantity", "Price")
    c.axes()
    c.curve(DEMAND, "D", BLUE)
    c.curve(SUPPLY, "S", TEAL)
    c.curve(aided, "S + subsidy", CORAL, dashed=True)
    c.area([Point(0, after.y), Point(0, producer.y), producer, after],
           AMBER, "Subsidy", opacity=0.2)
    c.guides(before, "Q", "P")
    c.guides(after, "Q₁", "P₁")
    c.note("Price to consumers falls, quantity traded rises")
    return c.svg("Subsidy", "Supply shifts down by the subsidy.")


def _price_control(kind: str) -> str:
    eq = intersect(DEMAND, SUPPLY)
    level = eq.y - 22 if kind == "maximum" else eq.y + 22
    qd, qs = _qd_qs(level)
    short = qd - qs if kind == "maximum" else qs - qd
    label = "Shortage" if kind == "maximum" else "Surplus"

    c = Canvas("Quantity", "Price")
    c.axes()
    c.curve(DEMAND, "D", BLUE)
    c.curve(SUPPLY, "S", TEAL)
    c.curve(Line(Point(0, level), Point(100, level)),
            f"P {kind[:3]}", CORAL, x_from=0, x_to=95)
    c.guides(eq, "Q", "P")
    lo, hi = (qs, qd) if kind == "maximum" else (qd, qs)
    c.guides(Point(lo, level), "Qs" if kind == "maximum" else "Qd", "")
    c.guides(Point(hi, level), "Qd" if kind == "maximum" else "Qs", "")
    c.area([Point(lo, level), Point(hi, level),
            Point(hi, level + 6), Point(lo, level + 6)],
           AMBER, label, opacity=0.25)
    c.note(f"{label} of {abs(short):.0f} units at the controlled price")
    return c.svg(
        f"{kind.capitalize()} price",
        f"A {kind} price away from equilibrium creates a {label.lower()}.",
    )


def _qd_qs(level: float) -> tuple[float, float]:
    """Quantity demanded and supplied at a price, both computed from the curves."""
    qd = (level - DEMAND.a.y) / DEMAND.slope + DEMAND.a.x
    qs = (level - SUPPLY.a.y) / SUPPLY.slope + SUPPLY.a.x
    return qd, qs


def maximum_price() -> str:
    return _price_control("maximum")


def minimum_price() -> str:
    return _price_control("minimum")


def buffer_stock() -> str:
    """A price band: the agency buys at the floor and sells at the ceiling."""
    eq = intersect(DEMAND, SUPPLY)
    floor, ceiling = eq.y - 18, eq.y + 18
    qd_lo, qs_lo = _qd_qs(floor)
    qd_hi, qs_hi = _qd_qs(ceiling)

    c = Canvas("Quantity", "Price")
    c.axes()
    c.curve(DEMAND, "D", BLUE)
    c.curve(SUPPLY, "S", TEAL)
    c.curve(Line(Point(0, ceiling), Point(100, ceiling)), "Ceiling", CORAL,
            x_from=0, x_to=92)
    c.curve(Line(Point(0, floor), Point(100, floor)), "Floor", CORAL,
            x_from=0, x_to=92)
    c.area([Point(qd_hi, ceiling), Point(qs_hi, ceiling),
            Point(qs_hi, ceiling + 5), Point(qd_hi, ceiling + 5)],
           AMBER, "Buy into store", opacity=0.25)
    c.area([Point(qs_lo, floor - 5), Point(qd_lo, floor - 5),
            Point(qd_lo, floor), Point(qs_lo, floor)],
           PURPLE, "Sell from store", opacity=0.25)
    c.guides(eq, "Q", "P")
    c.note("Buy the surplus at the ceiling price, release stock at the floor")
    return c.svg("Buffer stock scheme",
                 "A price band with intervention at each edge.")


def elasticity_extremes() -> str:
    """Perfectly elastic and perfectly inelastic demand on one pair of axes."""
    c = Canvas("Quantity", "Price")
    c.axes()
    c.curve(Line(Point(0, 60), Point(100, 60)), "Perfectly elastic", BLUE,
            x_from=0, x_to=88)
    c.curve(Line(Point(45, 0), Point(45, 100)), "Perfectly inelastic", CORAL)
    c.curve(DEMAND, "Unit elastic region", TEAL, x_from=15, x_to=85)
    c.note("A flat curve is infinitely elastic; a vertical one has zero elasticity")
    return c.svg("Elasticity extremes", "Flat, vertical and sloping demand curves.")


def ped_along_demand() -> str:
    """PED varies along a straight-line demand curve — elastic top, inelastic foot."""
    mid = Point(50, DEMAND.y_at(50))
    c = Canvas("Quantity", "Price")
    c.axes()
    c.curve(DEMAND, "D", BLUE)
    c.guides(mid, "", "")
    c.area([Point(10, 85), mid, Point(10, mid.y)], CORAL, "Elastic", opacity=0.15)
    c.area([mid, Point(90, 15), Point(90, mid.y)], TEAL, "Inelastic", opacity=0.15)
    c.note("PED falls as you move down a straight-line demand curve; unity at the midpoint")
    return c.svg("Elasticity along a demand curve", "Elastic above the midpoint.")


def ppc(*, direction: str = "none") -> str:
    """A concave production possibility curve, optionally shifted outward."""
    dx = _direction_shift(direction, size=14.0)
    points = [Point(x, _ppc_y(x, 0)) for x in range(0, 101, 5)]
    c = Canvas("Good B", "Good A")
    c.axes()
    c.path(points, "PPC", TEAL)
    if dx:
        moved = [Point(x, _ppc_y(x, dx)) for x in range(0, 101, 5)]
        c.path(moved, "PPC₁", CORAL, dashed=True)
    c.guides(Point(35, _ppc_y(35, 0)), "", "")
    c.box(22, 22, 70, 24, "unemployed", PURPLE)
    c.note(
        "A shift outward is economic growth" if dx
        else "Points inside are unemployed resources; points beyond are unattainable"
    )
    return c.svg("Production possibility curve", "Concave frontier between two goods.")


def _ppc_y(x: float, dx: float) -> float:
    """Concave frontier: a quarter ellipse, so opportunity cost increases."""
    radius = 80.0 + dx
    if x >= radius:
        return 0.0
    return radius * (1 - (x / radius) ** 2) ** 0.5


def trading_possibility() -> str:
    """Specialisation and trade let a country consume beyond its own PPC."""
    own = [Point(0, 70), Point(70, 0)]
    trade = [Point(0, 95), Point(95, 0)]
    c = Canvas("Good B", "Good A")
    c.axes()
    c.path(own, "PPC", TEAL)
    c.path(trade, "Trading possibility curve", CORAL, dashed=True)
    c.guides(Point(35, 35), "", "")
    c.note("Trade allows consumption at a point beyond the production frontier")
    return c.svg("Trading possibility curve", "Trade line outside the PPC.")


def ad_as(*, shift: str = "AD", direction: str = "right",
          show_lras: bool = True) -> str:
    """AD/AS, the workhorse of the macro half of the course."""
    if shift not in {"AD", "SRAS", "LRAS", "none"}:
        raise DiagramError("shift must be AD, SRAS, LRAS or none")
    dx = _direction_shift(direction)
    ad, sras = AD, SRAS
    lras = Line(Point(72, 0), Point(72, 100))
    moved = None
    if shift == "AD":
        moved = ad.shifted(dx)
    elif shift == "SRAS":
        moved = sras.shifted(dx)
    elif shift == "LRAS":
        moved = lras.shifted(dx)

    first = intersect(ad, sras)
    if shift == "AD":
        second = intersect(moved, sras)
    elif shift == "SRAS":
        second = intersect(ad, moved)
    else:
        second = first

    c = Canvas("Real output", "Price level")
    c.axes()
    c.curve(ad, "AD", BLUE)
    c.curve(sras, "SRAS", TEAL)
    if show_lras:
        c.curve(lras, "LRAS", PURPLE)
    if moved is not None and dx and shift != "LRAS":
        c.curve(moved, f"{shift}₁", CORAL, dashed=True)
    if shift == "LRAS" and dx:
        c.curve(moved, "LRAS₁", CORAL, dashed=True)
    c.guides(first, "Y", "P")
    if dx and shift in {"AD", "SRAS"}:
        c.guides(second, "Y₁", "P₁")
        c.note(
            f"{shift} shifts {direction}: price level {_movement(first.y, second.y)}, "
            f"real output {_movement(first.x, second.x)}"
        )
    elif dx:
        c.note("LRAS shifts right: the economy's productive capacity increases")
    else:
        c.note("Macroeconomic equilibrium is where AD crosses AS")
    return c.svg("Aggregate demand and aggregate supply",
                 f"Price level against real output. {shift} shifts {direction}.")


def supply_side() -> str:
    return ad_as(shift="LRAS", direction="right")


def exchange_rate(*, direction: str = "right") -> str:
    """A floating exchange rate as the demand for and supply of a currency."""
    dx = _direction_shift(direction)
    demand, supply = DEMAND, SUPPLY
    moved = demand.shifted(dx)
    first = intersect(demand, supply)
    second = intersect(moved, supply)

    c = Canvas("Quantity of currency", "Exchange rate")
    c.axes()
    c.curve(demand, "D", BLUE)
    c.curve(supply, "S", TEAL)
    if dx:
        c.curve(moved, "D₁", CORAL, dashed=True)
    c.guides(first, "Q", "e")
    if dx:
        c.guides(second, "Q₁", "e₁")
        word = "appreciation" if second.y > first.y else "depreciation"
        c.note(f"Demand for the currency shifts {direction}: an {word}")
    return c.svg("Exchange rate determination",
                 "Demand and supply of a currency set a floating rate.")


def circular_flow() -> str:
    """The circular flow, with injections and leakages. A schematic, not a plot."""
    c = Canvas("", "")
    c.box(28, 72, 150, 46, "Households", BLUE)
    c.box(78, 72, 150, 46, "Firms", TEAL)
    c.arrow(Point(40, 80), Point(64, 80), BLUE)
    c.arrow(Point(64, 64), Point(40, 64), TEAL)
    c._text(c.px(52), c.py(86), "spending", size=12, anchor="middle")
    c._text(c.px(52), c.py(58), "income", size=12, anchor="middle")

    c.box(28, 26, 150, 40, "Leakages", CORAL)
    c.box(78, 26, 150, 40, "Injections", AMBER)
    c._text(c.px(28), c.py(14), "saving, tax, imports", size=12, anchor="middle")
    c._text(c.px(78), c.py(14), "investment, government, exports", size=12,
            anchor="middle")
    c.arrow(Point(28, 62), Point(28, 36), CORAL)
    c.arrow(Point(78, 36), Point(78, 62), AMBER)
    c.note("Income is in equilibrium when injections equal leakages")
    return c.svg("Circular flow of income",
                 "Households and firms with leakages and injections.")


# ---------------------------------------------------------------- catalogue


@dataclass(frozen=True)
class DiagramEntry:
    key: str
    label: str
    topics: tuple[str, ...]
    requires: tuple[str, ...]
    build: Callable[..., str]
    x_axis: str = "quantity"
    y_axis: str = "price"
    options: dict[str, tuple] = field(default_factory=dict)

    def render(self, **kwargs) -> str:
        return self.build(**kwargs)


CATALOGUE: tuple[DiagramEntry, ...] = (
    DiagramEntry(
        key="ppc", label="Production possibility curve",
        topics=("1.5",), requires=("production possibility",), build=ppc,
        x_axis="good B", y_axis="good A", options={"direction": DIRECTIONS},
    ),
    DiagramEntry(
        key="supply_demand", label="Demand and supply",
        topics=("2.1", "2.4"), requires=("demand", "supply"), build=supply_demand,
        options={"shift": ("demand", "supply", "none"), "direction": DIRECTIONS},
    ),
    DiagramEntry(
        key="ped_along_demand", label="Elasticity along a demand curve",
        topics=("2.2",), requires=("elasticity",), build=ped_along_demand,
    ),
    DiagramEntry(
        key="elasticity_extremes", label="Perfectly elastic and inelastic curves",
        topics=("2.2", "2.3"), requires=("elasticity",), build=elasticity_extremes,
    ),
    DiagramEntry(
        key="surplus", label="Consumer and producer surplus",
        topics=("2.5",), requires=("consumer surplus", "producer surplus"),
        build=surplus,
    ),
    DiagramEntry(
        key="indirect_tax", label="Indirect tax and its incidence",
        topics=("3.2",), requires=("indirect tax",), build=indirect_tax,
    ),
    DiagramEntry(
        key="subsidy", label="Subsidy",
        topics=("3.2",), requires=("subsid",), build=subsidy,
    ),
    DiagramEntry(
        key="maximum_price", label="Maximum price",
        topics=("3.2",), requires=("maximum and minimum",), build=maximum_price,
    ),
    DiagramEntry(
        key="minimum_price", label="Minimum price",
        topics=("3.2",), requires=("maximum and minimum",), build=minimum_price,
    ),
    DiagramEntry(
        key="buffer_stock", label="Buffer stock scheme",
        topics=("3.2",), requires=("buffer stock",), build=buffer_stock,
    ),
    DiagramEntry(
        key="circular_flow", label="Circular flow of income",
        topics=("4.2",), requires=("circular flow",), build=circular_flow,
        x_axis="—", y_axis="—",
    ),
    DiagramEntry(
        key="ad_as", label="Aggregate demand and aggregate supply",
        topics=("4.3", "4.4", "4.5", "4.6", "5.2", "5.3"),
        requires=("aggregate demand", "aggregate supply"), build=ad_as,
        x_axis="real output", y_axis="price level",
        options={"shift": ("AD", "SRAS", "none"), "direction": DIRECTIONS},
    ),
    DiagramEntry(
        key="supply_side", label="Supply-side policy shifting LRAS",
        topics=("5.4",), requires=("supply-side",), build=supply_side,
        x_axis="real output", y_axis="price level",
    ),
    DiagramEntry(
        key="trading_possibility", label="Trading possibility curve",
        topics=("6.1",), requires=("trading possibility",), build=trading_possibility,
        x_axis="good B", y_axis="good A",
    ),
    DiagramEntry(
        key="exchange_rate", label="Exchange rate determination",
        topics=("6.4",), requires=("exchange rate",), build=exchange_rate,
        x_axis="quantity of currency", y_axis="exchange rate",
        options={"direction": DIRECTIONS},
    ),
)

BY_KEY = {entry.key: entry for entry in CATALOGUE}


def render(key: str, **kwargs) -> str:
    try:
        entry = BY_KEY[key]
    except KeyError:
        raise DiagramError(f"no diagram called {key!r}") from None
    return entry.render(**kwargs)
