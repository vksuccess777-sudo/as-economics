"""Levels-based mark scheme: level -> marks, computed by code.

Sections B and C of Paper 2 are marked against levels descriptors, not a
points-based scheme. The single most important invariant in this system is
that a model NEVER emits a mark. It emits a *level* per assessment objective
with a justification; this module turns that level into marks by table lookup.

The ladder lives in a JSON file so it can be replaced with the real allocation
read off the Cambridge specimen Paper 2 mark scheme without touching code.
Two files are looked for, in order:

    data/levels/paper2_levels.json          your file, git-ignored
    data/levels/paper2_levels.example.json  the interim ladder shipped here

The interim ladder is *not* Cambridge's. Its descriptors are written from the
published AO definitions and its AO mark split is a modelling assumption. Every
ladder carries a `provenance` field, and every mark produced from an interim
ladder is labelled as indicative all the way through to the UI. Marking a
student against an uncalibrated ladder and presenting it as a Cambridge mark
would be the most damaging thing this tool could do.

Load-time invariant: for each part size, the sum of the maximum marks across
AO1, AO2 and AO3 must equal the part's total marks. A mis-edited ladder fails
loudly here rather than quietly marking a 12-mark part out of 11.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

AO_KEYS = ("AO1", "AO2", "AO3")

DEFAULT_LEVELS_DIR = Path(__file__).resolve().parents[2] / "data" / "levels"
USER_LADDER = "paper2_levels.json"
INTERIM_LADDER = "paper2_levels.example.json"


class LadderError(ValueError):
    """The ladder file is structurally wrong. Never silently corrected."""


@dataclass(frozen=True)
class AOBand:
    """One assessment objective within one part size."""

    ao: str
    max_marks: int
    marks_by_level: dict[int, int]
    descriptors: dict[int, str]

    @property
    def max_level(self) -> int:
        return max(self.marks_by_level)

    def marks_for(self, level: int) -> int:
        if level not in self.marks_by_level:
            raise LadderError(
                f"{self.ao}: level {level} is not on the ladder "
                f"(valid levels: {sorted(self.marks_by_level)})"
            )
        return self.marks_by_level[level]

    def descriptor(self, level: int) -> str:
        return self.descriptors.get(level, "")


@dataclass(frozen=True)
class PartLadder:
    """The ladder for one part size, e.g. an 8-mark part."""

    part_marks: int
    bands: dict[str, AOBand]

    def band(self, ao: str) -> AOBand:
        if ao not in self.bands:
            raise LadderError(f"no band for {ao} at {self.part_marks} marks")
        return self.bands[ao]

    def assessed_aos(self) -> list[str]:
        """AOs that can actually earn marks here.

        An 8-mark explain part carries no evaluation credit, so AO3 has a
        maximum of zero. Asking the marker to level an AO that cannot score is
        how you get a marker that hallucinates evaluation into a description.
        """
        return [ao for ao in AO_KEYS if ao in self.bands and self.bands[ao].max_marks > 0]

    def marks_for_levels(self, levels: dict[str, int]) -> int:
        total = 0
        for ao in self.assessed_aos():
            if ao not in levels:
                raise LadderError(f"no level supplied for {ao}")
            total += self.band(ao).marks_for(int(levels[ao]))
        return total


@dataclass(frozen=True)
class Ladder:
    provenance: str          # "interim" | "cambridge_mark_scheme" | ...
    source: str
    parts: dict[int, PartLadder]

    @property
    def is_calibrated(self) -> bool:
        return self.provenance != "interim"

    def part(self, part_marks: int) -> PartLadder:
        if part_marks not in self.parts:
            raise LadderError(
                f"no ladder for a {part_marks}-mark part "
                f"(have: {sorted(self.parts)})"
            )
        return self.parts[part_marks]

    def part_sizes(self) -> list[int]:
        return sorted(self.parts)


def _parse_part(part_marks: int, raw: dict) -> PartLadder:
    bands: dict[str, AOBand] = {}
    for ao in AO_KEYS:
        if ao not in raw:
            continue
        spec = raw[ao]
        try:
            marks_by_level = {int(k): int(v) for k, v in spec["levels"].items()}
        except (KeyError, TypeError, ValueError) as exc:
            raise LadderError(f"{part_marks}-mark {ao}: bad levels table") from exc

        max_marks = int(spec.get("max", max(marks_by_level.values(), default=0)))
        if marks_by_level and max(marks_by_level.values()) != max_marks:
            raise LadderError(
                f"{part_marks}-mark {ao}: top level awards "
                f"{max(marks_by_level.values())} but max is {max_marks}"
            )
        if 0 not in marks_by_level:
            raise LadderError(
                f"{part_marks}-mark {ao}: no level 0. An answer that earns "
                "nothing for this objective must be expressible."
            )
        descriptors = {
            int(k): str(v) for k, v in (spec.get("descriptors") or {}).items()
        }
        bands[ao] = AOBand(ao, max_marks, marks_by_level, descriptors)

    total = sum(b.max_marks for b in bands.values())
    if total != part_marks:
        raise LadderError(
            f"{part_marks}-mark part: AO maxima sum to {total}, not {part_marks}"
        )
    return PartLadder(part_marks=part_marks, bands=bands)


def load_ladder(path: str | Path) -> Ladder:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    parts_raw = raw.get("parts") or {}
    if not parts_raw:
        raise LadderError("ladder file defines no parts")
    parts = {int(k): _parse_part(int(k), v) for k, v in parts_raw.items()}
    return Ladder(
        provenance=str(raw.get("provenance", "interim")),
        source=str(raw.get("source", "")),
        parts=parts,
    )


def resolve_ladder_path(levels_dir: str | Path | None = None) -> Path:
    """Prefer the user's own ladder; fall back to the interim one."""
    directory = Path(levels_dir or DEFAULT_LEVELS_DIR)
    user = directory / USER_LADDER
    if user.exists():
        return user
    return directory / INTERIM_LADDER


def default_ladder(levels_dir: str | Path | None = None) -> Ladder:
    return load_ladder(resolve_ladder_path(levels_dir))
