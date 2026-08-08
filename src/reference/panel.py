"""The 'Go deeper' panel, shared by the knowledge base and the tutor.

Deliberately small and deliberately dull. It renders links and the attribution
lines their licences require, and nothing else. If this file ever grows a
function that reads what is on the other end of a link, the policy has been
broken.

The framing line matters as much as the links: a student needs to know they
are leaving a tool that is scoped to their syllabus for sites that are not.
Khan Academy and CORE are not written to 9708 and will happily teach A Level
or undergraduate material.
"""

from __future__ import annotations

from functools import lru_cache

import streamlit as st

from .links import LinkSet, LinksError, load_links
from .registry import RegistryError, load_registry

WARNING = (
    "These sites are not written to the 9708 AS syllabus — some of what they "
    "cover is A Level or degree level. Use them for a second explanation, and "
    "let the notes here decide what is examinable."
)


@lru_cache(maxsize=1)
def _linkset(topic_codes: tuple[str, ...]) -> LinkSet | None:
    try:
        registry = load_registry()
        return load_links(registry, set(topic_codes))
    except (RegistryError, LinksError, OSError, ValueError):
        return None


def go_deeper(
    spine,
    topic_code: str,
    topic_title: str,
    *,
    query: str | None = None,
    expanded: bool = False,
) -> None:
    linkset = _linkset(tuple(spine.topic_codes))
    if linkset is None:
        st.caption(
            "Link-out sources are unavailable — `data/reference/manifest.json` "
            "is missing or malformed. Run `python scripts/check_links.py`."
        )
        return

    rows = linkset.go_deeper(topic_code, topic_title, query=query)
    if not rows:
        return

    with st.expander("Go deeper — other sites", expanded=expanded):
        st.caption(WARNING)
        for row in rows:
            suffix = "" if row.is_search else f" · {row.licence}"
            st.markdown(f"- [{row.label}]({row.url}) — {row.source_name}{suffix}")
        for notice in LinkSet.notices(rows):
            st.caption(notice)
