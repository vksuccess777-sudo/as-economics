"""Open-licensed datasets: the only external content this project stores.

A dataset is a directory:

    data/reference/datasets/<slug>/
        data.csv
        manifest.json      <- source id, exact URL, licence, date downloaded

No manifest, no dataset. That is enforced here rather than written down
somewhere, and the source id is resolved through the registry, so a CSV
attributed to a link-only source cannot load at all.

The point of all this is one screen: Paper 2 Section A. A data response
question is made of real numbers, and real numbers are the one kind of
external content whose licences actually permit reuse.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .registry import Registry, RegistryError, load_registry

DEFAULT_DATASETS_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "reference" / "datasets"
)

REQUIRED_MANIFEST_KEYS = ("slug", "title", "source", "url", "licence", "accessed_on")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NUMBER = re.compile(r"-?\d[\d,]*\.?\d*")


class DatasetError(ValueError):
    """A dataset is missing, unlicensed or malformed."""


def normalise_number(text: str) -> str | None:
    """'1,234.50 %' -> '1234.5'. Used to compare figures across formats."""
    match = NUMBER.search(str(text))
    if not match:
        return None
    raw = match.group(0).replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    return f"{value:g}"


@dataclass(frozen=True)
class Table:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def as_markdown(self) -> str:
        head = "| " + " | ".join(self.headers) + " |"
        rule = "| " + " | ".join("---" for _ in self.headers) + " |"
        body = ["| " + " | ".join(r) + " |" for r in self.rows]
        return "\n".join([head, rule, *body])

    def as_text(self) -> str:
        """Plain-text rendering for the prompt — cheaper and less likely to be
        reformatted by the model than markdown."""
        widths = [
            max(len(self.headers[i]), *(len(r[i]) for r in self.rows))
            for i in range(len(self.headers))
        ]
        lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(self.headers))]
        for row in self.rows:
            lines.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(row)))
        return "\n".join(lines)

    def numbers(self) -> set[str]:
        out = set()
        for row in self.rows:
            for cell in row:
                value = normalise_number(cell)
                if value is not None:
                    out.add(value)
        for header in self.headers:
            value = normalise_number(header)
            if value is not None:
                out.add(value)
        return out


@dataclass(frozen=True)
class Dataset:
    slug: str
    title: str
    source_id: str
    url: str
    licence: str
    accessed_on: str
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    notice: str
    source_name: str
    region: str | None = None
    units: str | None = None
    notes: str | None = None

    def table(self, *, columns: list[str] | None = None, max_rows: int = 10) -> Table:
        """A Section A table is small: a handful of columns, under a dozen rows.

        Handing the model 40 years of data produces a stimulus that reads
        like a spreadsheet dump and parts that cherry-pick invisibly.
        """
        if columns:
            missing = [c for c in columns if c not in self.headers]
            if missing:
                raise DatasetError(f"columns not in {self.slug}: {missing}")
            idx = [self.headers.index(c) for c in columns]
        else:
            idx = list(range(len(self.headers)))
        rows = self.rows[-max_rows:] if max_rows else self.rows
        return Table(
            headers=tuple(self.headers[i] for i in idx),
            rows=tuple(tuple(r[i] for i in idx) for r in rows),
        )

    def attribution(self) -> str:
        return (
            f"{self.source_name} — {self.title}. {self.licence}. "
            f"Retrieved {self.accessed_on} from {self.url}"
        )

    def short_attribution(self) -> str:
        return f"Source: {self.source_name}, {self.licence}"


def _validate_manifest(raw: dict, registry: Registry) -> None:
    for key in REQUIRED_MANIFEST_KEYS:
        if not str(raw.get(key) or "").strip():
            raise DatasetError(
                f"dataset manifest is missing {key!r}. Nothing lands in "
                "data/reference/ without a full manifest line."
            )
    if not DATE.match(str(raw["accessed_on"])):
        raise DatasetError("accessed_on must be YYYY-MM-DD")

    source = registry.require_data_source(str(raw["source"]))

    url = str(raw["url"])
    if not url.startswith("https://"):
        raise DatasetError("dataset url must be https and must be the exact page it came from")
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    if not host.endswith(source.host) and not source.host.endswith(host):
        raise DatasetError(
            f"dataset says source {source.id!r} ({source.host}) but the URL is on "
            f"{host}. Attribute it to where it actually came from."
        )

    licence = str(raw["licence"])
    from .registry import OPEN_DATA_LICENCES

    if licence not in OPEN_DATA_LICENCES:
        raise DatasetError(
            f"licence {licence!r} is not an allowed open licence. If the page "
            "really says that, this data does not belong here."
        )


def load_dataset(
    slug: str,
    *,
    datasets_dir: str | Path | None = None,
    registry: Registry | None = None,
) -> Dataset:
    root = Path(datasets_dir or DEFAULT_DATASETS_DIR) / slug
    manifest_path = root / "manifest.json"
    csv_path = root / "data.csv"

    if not root.exists():
        raise DatasetError(f"no dataset directory at {root}")
    if not manifest_path.exists():
        raise DatasetError(
            f"{slug} has data but no manifest.json — it cannot be used. Run "
            "`python scripts/add_dataset.py` to record where it came from."
        )
    if not csv_path.exists():
        raise DatasetError(f"{slug} has no data.csv")

    registry = registry or load_registry()
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    _validate_manifest(raw, registry)
    source = registry.get(str(raw["source"]))

    with csv_path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        rows = [[cell.strip() for cell in row] for row in reader if any(c.strip() for c in row)]
    if len(rows) < 3:
        raise DatasetError(f"{slug} has fewer than two data rows — nothing to compare")

    headers, body = rows[0], rows[1:]
    width = len(headers)
    ragged = [i for i, r in enumerate(body, start=2) if len(r) != width]
    if ragged:
        raise DatasetError(f"{slug} data.csv has ragged rows at lines {ragged[:5]}")

    return Dataset(
        slug=str(raw["slug"]),
        title=str(raw["title"]),
        source_id=source.id,
        url=str(raw["url"]),
        licence=str(raw["licence"]),
        accessed_on=str(raw["accessed_on"]),
        headers=tuple(headers),
        rows=tuple(tuple(r) for r in body),
        notice=source.notice or "",
        source_name=source.name,
        region=(raw.get("region") or None),
        units=(raw.get("units") or None),
        notes=(raw.get("notes") or None),
    )


def available_datasets(
    datasets_dir: str | Path | None = None,
    registry: Registry | None = None,
) -> list[str]:
    """Slugs that load cleanly. A directory that fails validation is skipped
    here and reported by scripts/check_data_response.py, so a half-finished
    dataset cannot silently become a question."""
    root = Path(datasets_dir or DEFAULT_DATASETS_DIR)
    if not root.exists():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        try:
            load_dataset(child.name, datasets_dir=root, registry=registry)
        except (DatasetError, RegistryError, json.JSONDecodeError, OSError):
            continue
        out.append(child.name)
    return out
