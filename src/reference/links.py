"""Sending the student somewhere else, safely.

Two kinds of link come out of here:

  curated  someone opened the page, checked it was the right thing, and put
           the URL in data/reference/links.json
  search   built in code from a template in the manifest and the topic title

The second exists because the first does not scale and does rot. A curated
link is better when it exists; a search link is always there and is never
wrong about where it goes.

Three validations matter, all of them structural:

  * the topic code must be in the PARSED SPINE. A links file that names a
    topic Cambridge does not have is a links file written from memory.
  * the source id must be in the manifest, so nothing appears on screen
    without a licence and an attribution line behind it.
  * the URL's host must match the source's host. Otherwise a link labelled
    "Khan Academy" could point anywhere, and the attribution printed under
    it would be a lie.

Nothing here stores a word of anyone's content. The allowed key set is
closed to exactly {topic, source, title, url}, which is what makes "we only
link, we never copy" a property of the file format rather than a promise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .registry import Registry, RegistryError, Source

DEFAULT_LINKS = (
    Path(__file__).resolve().parents[2] / "data" / "reference" / "links.json"
)

ALLOWED_LINK_KEYS = {"topic", "source", "title", "url"}
MAX_TITLE_CHARS = 120


class LinksError(ValueError):
    """The links file is malformed."""


@dataclass(frozen=True)
class Link:
    topic: str
    source: str
    title: str
    url: str


@dataclass(frozen=True)
class LinkOut:
    """One row as the UI shows it."""

    label: str
    url: str
    source_name: str
    licence: str
    kind: str  # "curated" | "search"
    notice: str | None = None

    @property
    def is_search(self) -> bool:
        return self.kind == "search"


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _validate_link(raw: dict, registry: Registry, topic_codes: set[str]) -> Link:
    if not isinstance(raw, dict):
        raise LinksError("each link must be an object")
    unknown = set(raw) - ALLOWED_LINK_KEYS
    if unknown:
        raise LinksError(
            f"link has unexpected keys {sorted(unknown)}. Only "
            f"{sorted(ALLOWED_LINK_KEYS)} are allowed — this file holds links, "
            "never other people's words."
        )
    missing = [k for k in ALLOWED_LINK_KEYS if not str(raw.get(k) or "").strip()]
    if missing:
        raise LinksError(f"link is missing {missing}: {raw}")

    topic = str(raw["topic"]).strip()
    if topic not in topic_codes:
        raise LinksError(
            f"link names topic {topic!r}, which is not in the parsed syllabus "
            "spine. The spine is the authority — fix the link, not the spine."
        )

    source_id = str(raw["source"]).strip()
    if not registry.has(source_id):
        raise LinksError(f"link names source {source_id!r}, which is not in manifest.json")
    source = registry.get(source_id)

    url = str(raw["url"]).strip()
    if not url.startswith("https://"):
        raise LinksError(f"link url must be https: {url!r}")
    if not _host(url).endswith(source.host):
        raise LinksError(
            f"link claims source {source_id!r} ({source.host}) but points at "
            f"{_host(url)} — the attribution under it would be wrong"
        )

    title = str(raw["title"]).strip()
    if len(title) > MAX_TITLE_CHARS:
        raise LinksError(
            f"link title is {len(title)} characters. A title identifies a page; "
            "anything longer is a summary of it, which is the thing this file "
            "must not hold."
        )
    return Link(topic=topic, source=source_id, title=title, url=url)


@dataclass
class LinkSet:
    registry: Registry
    links: tuple[Link, ...] = ()

    def curated_for(self, topic_code: str) -> list[Link]:
        return [ln for ln in self.links if ln.topic == topic_code]

    def go_deeper(
        self,
        topic_code: str,
        topic_title: str,
        *,
        query: str | None = None,
        sources: list[str] | None = None,
        max_search: int = 4,
    ) -> list[LinkOut]:
        """What the 'Go deeper' panel shows for one topic.

        Curated links first, then one search link per link-only source. The
        search query defaults to the topic title, so it is the syllabus'
        wording that goes out, not a paraphrase of it.
        """
        out: list[LinkOut] = []
        for link in self.curated_for(topic_code):
            source = self.registry.get(link.source)
            out.append(
                LinkOut(
                    label=link.title,
                    url=link.url,
                    source_name=source.name,
                    licence=source.licence,
                    kind="curated",
                    notice=source.notice,
                )
            )

        wanted = sources or [s.id for s in self.registry.link_only()]
        covered = {ln.source for ln in self.curated_for(topic_code)}
        search_query = (query or topic_title).strip()
        added = 0
        for source_id in wanted:
            if added >= max_search:
                break
            if source_id in covered:
                continue
            source = self.registry.get(source_id)
            url = source.search_link(search_query)
            if not url:
                continue
            out.append(
                LinkOut(
                    label=f"Search {source.name} for “{search_query}”",
                    url=url,
                    source_name=source.name,
                    licence=source.licence,
                    kind="search",
                    notice=source.notice,
                )
            )
            added += 1
        return out

    @staticmethod
    def notices(rows: list[LinkOut]) -> list[str]:
        """Attribution lines that must appear when these rows are shown.

        Khan Academy's licence requires a specific line whenever its material
        is surfaced elsewhere. Deduplicated, order preserved.
        """
        seen: list[str] = []
        for row in rows:
            if row.notice and row.notice not in seen:
                seen.append(row.notice)
        return seen


def load_links(
    registry: Registry,
    topic_codes: set[str],
    path: str | Path | None = None,
) -> LinkSet:
    path = Path(path or DEFAULT_LINKS)
    if not path.exists():
        # An absent links file is not an error: search links still work.
        return LinkSet(registry=registry, links=())
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_links = payload.get("links", [])
    if not isinstance(raw_links, list):
        raise LinksError("links must be a list")
    links = tuple(_validate_link(raw, registry, topic_codes) for raw in raw_links)
    return LinkSet(registry=registry, links=links)


def build_linkset(spine, path: str | Path | None = None, registry: Registry | None = None):
    """Convenience for the pages: registry + links, validated against a spine."""
    from .registry import load_registry

    reg = registry or load_registry()
    try:
        return load_links(reg, set(spine.topic_codes), path)
    except (LinksError, RegistryError):
        raise


__all__ = [
    "Link",
    "LinkOut",
    "LinkSet",
    "LinksError",
    "Source",
    "build_linkset",
    "load_links",
]
