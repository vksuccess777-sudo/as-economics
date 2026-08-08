"""Draw an economics diagram in code, as SVG text.

WHY NOT LET THE MODEL DRAW. A model asked to emit SVG produces something that
looks like a diagram and is wrong in ways a student cannot detect: axes
labelled one way and lines drawn the other, a curve labelled "shifts right"
that goes left, dashed guides that miss the intersection they claim to mark.
A wrong diagram is worse than no diagram, because it gets copied into an exam
answer. So the model's only job is choosing WHICH diagram and WHAT shifts —
which it is reliable at — and every coordinate on the page is computed here.

The consequence worth stating: if the caption says the price level rises, the
intersection is higher, because both come from the same computed point.

NO NEW DEPENDENCY. An SVG is a string. There is no matplotlib here, nothing to
install, and nothing that behaves differently on Windows.

Data coordinates run 0-100 on both axes with the origin bottom left, which is
how the diagrams are actually reasoned about ("equilibrium moves up and to the
right"). `Canvas` is the only thing that knows about pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

WIDTH = 720
HEIGHT = 520
LEFT = 110
RIGHT = 80
TOP = 50
BOTTOM = 88

# Fixed hexes, not CSS variables: the SVG is rendered inside an <img>, so the
# host page's variables do not reach it. These read acceptably on both a white
# and a near-black background, and the style block below flips the neutrals for
# dark mode — media queries DO apply inside an embedded SVG document.
INK = "#55544f"
MUTED = "#8a8983"
BLUE = "#378ADD"
TEAL = "#1D9E75"
CORAL = "#D85A30"
AMBER = "#BA7517"
PURPLE = "#7F77DD"

STYLE = (
    "<style>"
    ".ink{stroke:%s}.inkf{fill:%s}.muted{stroke:%s}.mutedf{fill:%s}"
    "text{font-family:system-ui,-apple-system,'Segoe UI',sans-serif}"
    "@media (prefers-color-scheme:dark){"
    ".ink{stroke:#c2c0b6}.inkf{fill:#c2c0b6}"
    ".muted{stroke:#9c9a92}.mutedf{fill:#9c9a92}}"
    "</style>"
) % (INK, INK, MUTED, MUTED)


class DiagramError(ValueError):
    pass


@dataclass(frozen=True)
class Point:
    x: float
    y: float


@dataclass(frozen=True)
class Line:
    """A straight line through two points in data space."""

    a: Point
    b: Point

    @property
    def slope(self) -> float:
        if self.b.x == self.a.x:
            raise DiagramError("vertical line has no slope")
        return (self.b.y - self.a.y) / (self.b.x - self.a.x)

    @property
    def is_vertical(self) -> bool:
        return self.a.x == self.b.x

    def y_at(self, x: float) -> float:
        return self.a.y + self.slope * (x - self.a.x)

    def shifted(self, dx: float) -> "Line":
        """Move the whole line horizontally. Right is positive."""
        return Line(Point(self.a.x + dx, self.a.y), Point(self.b.x + dx, self.b.y))

    def raised(self, dy: float) -> "Line":
        return Line(Point(self.a.x, self.a.y + dy), Point(self.b.x, self.b.y + dy))


def intersect(one: Line, other: Line) -> Point:
    """Where two lines cross, in data space. Parallel lines are an error."""
    if one.is_vertical and other.is_vertical:
        raise DiagramError("two vertical lines never cross")
    if one.is_vertical:
        return Point(one.a.x, other.y_at(one.a.x))
    if other.is_vertical:
        return Point(other.a.x, one.y_at(other.a.x))
    if abs(one.slope - other.slope) < 1e-9:
        raise DiagramError("parallel lines never cross")
    x = (other.a.y - one.a.y + one.slope * one.a.x - other.slope * other.a.x) / (
        one.slope - other.slope
    )
    return Point(x, one.y_at(x))


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


@dataclass
class Canvas:
    """Data space in, SVG text out."""

    x_label: str
    y_label: str
    caption: str = ""
    parts: list[str] = field(default_factory=list)

    # ---- coordinate mapping ------------------------------------------

    def px(self, x: float) -> float:
        return LEFT + (x / 100.0) * (WIDTH - LEFT - RIGHT)

    def py(self, y: float) -> float:
        return HEIGHT - BOTTOM - (y / 100.0) * (HEIGHT - TOP - BOTTOM)

    def point(self, p: Point) -> tuple[float, float]:
        return self.px(p.x), self.py(p.y)

    # ---- primitives ---------------------------------------------------

    def _text(self, x: float, y: float, body: str, *, size: int = 16,
              anchor: str = "start", colour: str | None = None,
              weight: int = 400) -> None:
        fill = f'fill="{colour}"' if colour else ""
        cls = "" if colour else ' class="inkf"'
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" '
            f'font-weight="{weight}" text-anchor="{anchor}" {fill}{cls}>'
            f"{_esc(body)}</text>"
        )

    def axes(self) -> None:
        x0, y0 = self.px(0), self.py(0)
        self.parts.append(
            f'<line x1="{x0:.1f}" y1="{self.py(100):.1f}" x2="{x0:.1f}" '
            f'y2="{y0:.1f}" class="ink" stroke-width="2"/>'
        )
        self.parts.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{self.px(100):.1f}" '
            f'y2="{y0:.1f}" class="ink" stroke-width="1.5"/>'
        )
        self._text(x0, self.py(100) - 12, self.y_label, size=15, anchor="middle")
        self._text(self.px(100) + 6, y0 + 4, self.x_label, size=15)

    def curve(self, line: Line, label: str, colour: str, *,
              dashed: bool = False, x_from: float = 5, x_to: float = 95) -> None:
        """A straight curve, clipped to the plot and labelled at its end."""
        if line.is_vertical:
            ax, ay = self.px(line.a.x), self.py(4)
            bx, by = self.px(line.a.x), self.py(96)
            lx, ly = bx, by - 8
            anchor = "middle"
        else:
            a = Point(x_from, line.y_at(x_from))
            b = Point(x_to, line.y_at(x_to))
            ax, ay = self.point(a)
            bx, by = self.point(b)
            end = b if b.y > 2 else a
            lx, ly = self.point(end)
            lx, ly = lx + 6, ly + 4
            anchor = "start"
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.parts.append(
            f'<line x1="{ax:.1f}" y1="{ay:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
            f'stroke="{colour}" stroke-width="2.6" fill="none"{dash}/>'
        )
        if label:
            self._text(lx, ly, label, size=17, anchor=anchor, colour=colour,
                       weight=500)

    def guides(self, p: Point, x_label: str, y_label: str) -> None:
        """Dashed drop-lines to both axes, with the labels the marker wants."""
        x, y = self.point(p)
        x0, y0 = self.px(0), self.py(0)
        self.parts.append(
            f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
            f'class="muted" stroke-width="1" stroke-dasharray="4 4"/>'
        )
        self.parts.append(
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y0:.1f}" '
            f'class="muted" stroke-width="1" stroke-dasharray="4 4"/>'
        )
        self.parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" class="inkf"/>')
        if y_label:
            self._text(x0 - 8, y + 4, y_label, size=15, anchor="end")
        if x_label:
            self._text(x, y0 + 18, x_label, size=15, anchor="middle")

    def area(self, points: list[Point], colour: str, label: str = "",
             opacity: float = 0.18) -> None:
        coords = " ".join(f"{self.px(p.x):.1f},{self.py(p.y):.1f}" for p in points)
        self.parts.append(
            f'<polygon points="{coords}" fill="{colour}" '
            f'fill-opacity="{opacity}" stroke="none"/>'
        )
        if label:
            cx = sum(p.x for p in points) / len(points)
            cy = sum(p.y for p in points) / len(points)
            self._text(self.px(cx), self.py(cy) + 4, label, size=15,
                       anchor="middle", colour=colour, weight=500)

    def path(self, points: list[Point], label: str, colour: str,
             *, dashed: bool = False) -> None:
        """A freehand curve through computed points (PPC, and nothing else)."""
        coords = " ".join(f"{self.px(p.x):.1f},{self.py(p.y):.1f}" for p in points)
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        self.parts.append(
            f'<polyline points="{coords}" fill="none" stroke="{colour}" '
            f'stroke-width="2"{dash}/>'
        )
        if label:
            last = points[-1]
            self._text(self.px(last.x) + 6, self.py(last.y) + 4, label,
                       size=17, colour=colour, weight=500)

    def arrow(self, start: Point, end: Point, colour: str) -> None:
        x1, y1 = self.point(start)
        x2, y2 = self.point(end)
        self.parts.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{colour}" stroke-width="1.5" marker-end="url(#dgarrow)"/>'
        )

    def box(self, cx: float, cy: float, w: float, h: float, label: str,
            colour: str) -> None:
        x, y = self.px(cx) - w / 2, self.py(cy) - h / 2
        self.parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{w}" height="{h}" rx="6" '
            f'fill="{colour}" fill-opacity="0.12" stroke="{colour}" '
            f'stroke-width="1"/>'
        )
        self._text(self.px(cx), self.py(cy) + 4, label, size=16, anchor="middle",
                   colour=colour, weight=500)

    def note(self, text: str) -> None:
        self._text(WIDTH / 2, HEIGHT - 20, text, size=15, anchor="middle")

    # ---- output --------------------------------------------------------

    def svg(self, title: str, description: str) -> str:
        marker = (
            '<defs><marker id="dgarrow" viewBox="0 0 10 10" refX="8" refY="5" '
            'markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            '<path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" '
            'stroke-width="1.5" stroke-linecap="round"/></marker></defs>'
        )
        body = "".join(self.parts)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" '
            f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img">'
            f"<title>{_esc(title)}</title><desc>{_esc(description)}</desc>"
            f"{STYLE}{marker}{body}</svg>"
        )
