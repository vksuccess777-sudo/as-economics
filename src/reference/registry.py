"""The licence registry: which external sources exist and what may be done
with each.

The whole Tier 2 / Tier 3 policy is one field. `use` is either:

    "link_only"  the student may be sent there; no code path ever reads it
    "data"       a dataset may be placed under data/reference/datasets/ and
                 rendered inside a Paper 2 Section A stimulus

That split is not about how good a source is. ZNotes and tutor2u are good.
It is about what a licence permits and what the app actually needs: numbers
are reusable and are what a data-response question is made of; explanations
are not reusable, and this app already writes its own from the parsed spine.

A source with `use: "data"` must carry a licence from OPEN_DATA_LICENCES.
That is deliberately a hard gate rather than a warning — "data" is the only
value that lets bytes into the repository, so an unrecognised licence there
has to stop the load, not decorate it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_plus, urlsplit

DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[2] / "data" / "reference" / "manifest.json"
)

USES = ("link_only", "data")

# Licences under which a dataset may be committed here. Attribution is always
# required in practice, which is why `notice` is mandatory for a data source.
OPEN_DATA_LICENCES = {
    "CC BY 4.0",
    "CC BY 3.0 IGO",
    "CC BY-SA 4.0",
    "CC0 1.0",
    "OGL v3",
    "OECD Terms",
    "IMF Terms of Use",
    "RBI Terms",
    "Government Open Data Licence - India",
    "Public domain",
}

REQUIRED_KEYS = ("id", "name", "use", "licence", "home")
ALLOWED_KEYS = {
    *REQUIRED_KEYS,
    "licence_url",
    "search_url",
    "notice",
    "checked_on",
    "why_link_only",
    "caution",
}


class RegistryError(ValueError):
    """The manifest is malformed. Loud, because silence here means an
    unlicensed source quietly becoming usable."""


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    use: str
    licence: str
    home: str
    licence_url: str | None = None
    search_url: str | None = None
    notice: str | None = None
    checked_on: str | None = None
    why_link_only: str | None = None
    caution: str | None = None

    @property
    def is_data(self) -> bool:
        return self.use == "data"

    @property
    def host(self) -> str:
        return urlsplit(self.home).netloc.lower().removeprefix("www.")

    def search_link(self, query: str) -> str | None:
        """A live search URL scoped to this source.

        This exists so the link-out feature works with an empty links.json.
        A search URL is built from a template and a query, so it cannot go
        stale the way a hand-copied deep link does.
        """
        if not self.search_url:
            return None
        return self.search_url.replace("{query}", quote_plus(query.strip()))

    def attribution(self) -> str:
        bits = [self.name, self.licence]
        return " — ".join(b for b in bits if b)


@dataclass(frozen=True)
class Registry:
    sources: tuple[Source, ...]

    def __post_init__(self) -> None:
        ids = [s.id for s in self.sources]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise RegistryError(f"duplicate source ids: {sorted(dupes)}")

    def get(self, source_id: str) -> Source:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise RegistryError(f"unknown source {source_id!r} — add it to manifest.json")

    def has(self, source_id: str) -> bool:
        return any(s.id == source_id for s in self.sources)

    def link_only(self) -> list[Source]:
        return [s for s in self.sources if s.use == "link_only"]

    def data_sources(self) -> list[Source]:
        return [s for s in self.sources if s.is_data]

    def require_data_source(self, source_id: str) -> Source:
        """Gate for anything that wants to READ a source rather than link to it.

        This is the single place a link-only source is stopped from becoming
        a corpus. Every dataset load goes through here.
        """
        source = self.get(source_id)
        if not source.is_data:
            raise RegistryError(
                f"{source.name} is registered as {source.use!r}: it may be linked "
                "to, never read. Its licence does not permit its content being "
                "stored or reused here."
            )
        return source


def _validate_raw(raw: dict) -> None:
    unknown = set(raw) - ALLOWED_KEYS
    if unknown:
        raise RegistryError(
            f"source {raw.get('id')!r} has unexpected keys {sorted(unknown)} — "
            "the key set is closed so source TEXT cannot be smuggled in here"
        )
    for key in REQUIRED_KEYS:
        if not str(raw.get(key) or "").strip():
            raise RegistryError(f"source {raw.get('id')!r} is missing {key!r}")

    use = raw["use"]
    if use not in USES:
        raise RegistryError(f"source {raw['id']!r} has use={use!r}, expected one of {USES}")

    home = str(raw["home"])
    if not home.startswith("https://"):
        raise RegistryError(f"source {raw['id']!r} home must be https")

    if use == "data":
        if raw["licence"] not in OPEN_DATA_LICENCES:
            raise RegistryError(
                f"source {raw['id']!r} is marked as data but its licence "
                f"{raw['licence']!r} is not in the allow-list. Either the licence "
                "is wrong or this source is link_only."
            )
        if not str(raw.get("notice") or "").strip():
            raise RegistryError(
                f"source {raw['id']!r} is a data source with no attribution "
                "notice — every one of them needs the line printed under the table"
            )

    search_url = raw.get("search_url")
    if search_url and "{query}" not in search_url:
        raise RegistryError(f"source {raw['id']!r} search_url has no {{query}} placeholder")


def load_registry(path: str | Path | None = None) -> Registry:
    path = Path(path or DEFAULT_MANIFEST)
    if not path.exists():
        raise RegistryError(
            f"source manifest not found at {path}. Nothing external can be used "
            "without it — that is the point of it."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise RegistryError("manifest has no sources")

    sources = []
    for raw in raw_sources:
        if not isinstance(raw, dict):
            raise RegistryError("each source must be an object")
        _validate_raw(raw)
        sources.append(Source(**{k: raw.get(k) for k in ALLOWED_KEYS if k in raw}))
    return Registry(tuple(sources))
