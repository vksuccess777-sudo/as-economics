"""The ladder is the only thing standing between a model's opinion and a mark."""

from __future__ import annotations

import json

import pytest

from src.marking.levels import (
    LadderError,
    default_ladder,
    load_ladder,
    resolve_ladder_path,
)


def write(tmp_path, payload) -> str:
    path = tmp_path / "ladder.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


BASIC = {
    "provenance": "interim",
    "parts": {
        "8": {
            "AO1": {"max": 4, "levels": {"0": 0, "1": 1, "2": 3, "3": 4}},
            "AO2": {"max": 4, "levels": {"0": 0, "1": 1, "2": 3, "3": 4}},
            "AO3": {"max": 0, "levels": {"0": 0}},
        }
    },
}


def test_marks_come_from_the_table_not_the_model(tmp_path):
    ladder = load_ladder(write(tmp_path, BASIC))
    part = ladder.part(8)
    assert part.marks_for_levels({"AO1": 2, "AO2": 3}) == 3 + 4


def test_ao_maxima_must_sum_to_the_part_total(tmp_path):
    """A ladder that marks a 8-mark part out of 7 must fail at load, loudly."""
    broken = json.loads(json.dumps(BASIC))
    broken["parts"]["8"]["AO2"]["max"] = 3
    broken["parts"]["8"]["AO2"]["levels"] = {"0": 0, "1": 1, "2": 2, "3": 3}
    with pytest.raises(LadderError, match="sum to 7"):
        load_ladder(write(tmp_path, broken))


def test_top_level_must_award_the_maximum(tmp_path):
    broken = json.loads(json.dumps(BASIC))
    broken["parts"]["8"]["AO1"]["levels"]["3"] = 5
    with pytest.raises(LadderError, match="top level"):
        load_ladder(write(tmp_path, broken))


def test_level_zero_is_mandatory(tmp_path):
    """An answer that earns nothing for an objective must be expressible."""
    broken = json.loads(json.dumps(BASIC))
    del broken["parts"]["8"]["AO1"]["levels"]["0"]
    broken["parts"]["8"]["AO1"]["levels"] = {"1": 0, "2": 3, "3": 4}
    with pytest.raises(LadderError, match="no level 0"):
        load_ladder(write(tmp_path, broken))


def test_zero_weighted_ao_is_not_assessed(tmp_path):
    """An 8-mark explain part carries no evaluation credit."""
    ladder = load_ladder(write(tmp_path, BASIC))
    assert ladder.part(8).assessed_aos() == ["AO1", "AO2"]


def test_level_off_the_ladder_is_rejected(tmp_path):
    ladder = load_ladder(write(tmp_path, BASIC))
    with pytest.raises(LadderError, match="level 4 is not on the ladder"):
        ladder.part(8).band("AO1").marks_for(4)


def test_unknown_part_size_is_rejected(tmp_path):
    ladder = load_ladder(write(tmp_path, BASIC))
    with pytest.raises(LadderError, match="no ladder for a 20-mark part"):
        ladder.part(20)


def test_shipped_ladder_is_valid_and_totals_twenty():
    """The interim ladder must itself satisfy every rule above."""
    ladder = default_ladder()
    assert ladder.part_sizes() == [8, 12]
    assert sum(ladder.part(n).part_marks for n in ladder.part_sizes()) == 20
    for n in ladder.part_sizes():
        part = ladder.part(n)
        assert sum(part.band(ao).max_marks for ao in part.bands) == n


def test_shipped_ladder_is_flagged_calibrated():
    """data/levels/paper2_levels.json is built from the 2023 Specimen Paper 2
    mark scheme (see its 'source' field), so the loader should prefer it over
    the interim example and the result should read as calibrated."""
    ladder = default_ladder()
    assert ladder.is_calibrated is True
    assert ladder.provenance == "cambridge_mark_scheme"
    assert resolve_ladder_path().name == "paper2_levels.json"


def test_eight_mark_part_awards_evaluation_but_twelve_mark_part_does_not_split_ao1_ao2():
    """Cambridge point-marks the 8-mark part (a) questions AO1 3 / AO2 3 / AO3
    2, so AO3 IS assessed there. The 12-mark part (b) questions use Cambridge's
    Table A, which marks AO1 and AO2 TOGETHER (stored under AO1); Table B
    (AO3) is separate. So AO2 is the one not assessed at 12 marks."""
    ladder = default_ladder()
    assert "AO3" in ladder.part(8).assessed_aos()
    assert "AO2" not in ladder.part(12).assessed_aos()
    assert "AO3" in ladder.part(12).assessed_aos()
