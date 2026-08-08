"""Section A marking: the model judges, the code counts.

Every test here is really the same test asked six ways — can a model's output
move a mark by any route other than the arithmetic in `award`? The answer has
to be no.
"""

from __future__ import annotations

import json

import pytest

from src.llm.provider import LLMResponse
from src.marking.points_marker import (
    MARKER_VERSION,
    PointsMarker,
    PointsMarkingError,
    PointsPart,
    award,
    parse_judgements,
    record_part,
)
from src.store.db import Store

ASSESS_CAPS = {"analysis": 4, "evaluation": 2}


def part(marks=6, caps=ASSESS_CAPS, points=None):
    points = points or (
        [{"text": f"analysis point {i}", "band": "analysis"} for i in range(5)]
        + [{"text": f"evaluation point {i}", "band": "evaluation"} for i in range(3)]
    )
    return PointsPart(
        question_id="q1",
        label="(d)",
        prompt="Assess the likely effects on employment.",
        max_marks=marks,
        points=tuple(points),
        caps=caps,
        topic_code="4.1",
    )


class FakeProvider:
    name = "fake"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return LLMResponse(text=text, provider=self.name, model="fake")


def judgements(met_indexes, total):
    return {
        "judgements": [
            {"index": i, "met": i in met_indexes, "why": "because"} for i in range(total)
        ],
        "advice": "Add a conclusion that weighs both sides.",
    }


# ---- the arithmetic -----------------------------------------------------


def test_marks_are_one_per_point_met():
    awarded, bands = award(part(marks=6, caps=None), [0, 1, 2])
    assert awarded == 3


def test_analysis_is_capped_at_four_however_many_points_are_met():
    """Straight from the mark scheme: up to 4 marks for explanation/analysis."""
    awarded, bands = award(part(), [0, 1, 2, 3, 4])  # five analysis points
    assert bands["analysis"] == 4
    assert awarded == 4


def test_evaluation_is_capped_at_two():
    awarded, bands = award(part(), [5, 6, 7])  # three evaluation points
    assert bands["evaluation"] == 2
    assert awarded == 2


def test_full_marks_need_both_bands():
    awarded, _ = award(part(), [0, 1, 2, 3, 5, 6])
    assert awarded == 6


def test_every_point_met_still_cannot_exceed_the_part_maximum():
    """The model is never told what the part is worth. Even if it were, and
    even if it claimed everything, the total is clamped here."""
    awarded, _ = award(part(), list(range(8)))
    assert awarded == 6


def test_out_of_range_indexes_are_ignored():
    awarded, _ = award(part(), [0, 99, -3])
    assert awarded == 1


def test_duplicate_indexes_count_once():
    awarded, _ = award(part(), [0, 0, 0])
    assert awarded == 1


# ---- parsing ------------------------------------------------------------


def test_a_point_the_marker_skipped_is_not_credited():
    """Silence is not credit. A marker that returns four judgements for eight
    points has not met the other four."""
    per_point, advice = parse_judgements(
        json.dumps({"judgements": [{"index": 0, "met": True, "why": "x"}], "advice": "a"}),
        part(),
    )
    assert len(per_point) == 8
    assert per_point[0]["met"] is True
    assert all(p["met"] is False for p in per_point[1:])
    assert per_point[1]["why"] == "not addressed"


def test_a_mark_written_by_the_model_is_ignored():
    payload = {
        "judgements": [{"index": 0, "met": True, "why": "x"}],
        "marks": 6,
        "score": "6/6",
        "advice": "a",
    }
    marked = PointsMarker(FakeProvider(payload)).mark(part(), "A real answer, written out.")
    assert marked.awarded == 1


def test_missing_judgements_raise():
    with pytest.raises(PointsMarkingError):
        parse_judgements(json.dumps({"advice": "nothing"}), part())


def test_markdown_fences_survive():
    per_point, _ = parse_judgements(
        "```json\n" + json.dumps(judgements([1], 8)) + "\n```", part()
    )
    assert per_point[1]["met"] is True


# ---- marking ------------------------------------------------------------


def test_blank_answer_scores_zero_without_calling_the_model():
    provider = FakeProvider(judgements([0, 1, 2], 8))
    marked = PointsMarker(provider).mark(part(), "   ")
    assert marked.awarded == 0
    assert provider.calls == 0, "an empty answer is zero by inspection — spend nothing"
    assert all(p["met"] is False for p in marked.per_point)


def test_marked_result_carries_the_band_split_and_the_marker_version():
    marked = PointsMarker(FakeProvider(judgements([0, 1, 2, 3, 4, 5], 8))).mark(
        part(), "A full answer with analysis and a judgement at the end."
    )
    assert marked.awarded == 5  # analysis capped at 4, one evaluation point
    assert marked.band_marks == {"analysis": 4, "evaluation": 1}
    assert marked.marker_version == MARKER_VERSION


def test_feedback_records_that_the_points_are_indicative():
    marked = PointsMarker(FakeProvider(judgements([0], 8))).mark(part(), "An answer.")
    payload = json.loads(marked.feedback_json())
    assert payload["indicative"] is True, (
        "the credited points were generated, not taken from a Cambridge mark "
        "scheme, and every stored result has to say so"
    )


# ---- the attempt log ----------------------------------------------------


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.sqlite3")
    s.initialise()
    return s


def test_recording_a_part_writes_marks_but_no_ao_levels(store):
    qid = store.add_question(
        paper_key="paper_2",
        section_key="A",
        topic_code="4.1",
        max_marks=6,
        body=json.dumps({"prompt": "Assess..."}),
        origin="generated",
        syllabus_code="9708",
        syllabus_version="2026-2028",
        rubric=json.dumps({"group_id": "g1", "part": "(d)", "part_index": 4}),
    )
    marked = PointsMarker(FakeProvider(judgements([0, 5], 8))).mark(
        part(), "An answer with one analysis point and one evaluation point."
    )
    object.__setattr__(marked, "question_id", qid)

    attempt_id = store.start_attempt(mode="practice", paper_key="paper_2")
    record_part(store, attempt_id=attempt_id, ordinal=1, marked=marked, answer_text="...")

    with store.connect() as conn:
        row = conn.execute("SELECT * FROM response WHERE question_id = ?", (qid,)).fetchone()
    assert row["awarded"] == 2
    # Section A is point-marked. Writing a level here would put fabricated
    # rows into the Coach's AO table.
    assert row["ao1_level"] is None
    assert row["ao2_level"] is None
    assert row["ao3_level"] is None
    assert row["marker_version"] == MARKER_VERSION


def test_part_reads_its_rubric_off_a_question_row(store):
    qid = store.add_question(
        paper_key="paper_2",
        section_key="A",
        topic_code="4.1",
        max_marks=2,
        body=json.dumps({"prompt": "Using Table 1.1, compare the two years."}),
        origin="generated",
        syllabus_code="9708",
        syllabus_version="2026-2028",
        rubric=json.dumps(
            {
                "group_id": "g1",
                "part": "(a)",
                "part_index": 0,
                "points": [{"text": "the comparison is made", "band": "knowledge"}],
                "caps": None,
            }
        ),
    )
    row = store.fetch_questions([qid])[0]
    loaded = PointsPart.from_row(row)
    assert loaded.label == "(a)"
    assert loaded.max_marks == 2
    assert loaded.caps is None
    assert loaded.points[0]["band"] == "knowledge"
