"""Put a diagram on a Streamlit page at a size a student can actually read.

`st.image` renders an SVG at its intrinsic size, which was too small, and the
obvious fixes are version-traps: `use_container_width` is deprecated and
`width="stretch"` needs a newer Streamlit than requirements.txt guarantees.
Inline HTML has neither problem — Streamlit passes an <svg> through untouched
and the SVG's own width="100%" then fills whatever box it is given.

So the size is set by the wrapper, in CSS, and the caller picks the box.
"""

from __future__ import annotations

# Label -> max width in pixels. None means fill the column edge to edge.
SIZES: dict[str, int | None] = {
    "Fit": 620,
    "Large": 900,
    "Full width": None,
}
DEFAULT_SIZE = "Large"


def as_html(svg: str, size: str = DEFAULT_SIZE) -> str:
    """Wrap a diagram for `st.markdown(..., unsafe_allow_html=True)`."""
    width = SIZES.get(size, SIZES[DEFAULT_SIZE])
    cap = f"max-width:{width}px;" if width else ""
    return (
        f'<div style="{cap}width:100%;margin:0.25rem 0 0.75rem 0;">{svg}</div>'
    )
