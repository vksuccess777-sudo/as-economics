"""The Coach makes claims about a student. Every one of them is checked here."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.coach.diagnosis import (
    APPLICATION,
    CONCEPT,
    EVALUATION,
    RECALL,
    UNTESTED,
    diagnose,
)
from src.coach.grades import (
    GradeError,
    default_grades,
    gap_to_target,
    load_grades,
    normalise_target,
)
from src.coach.plan import build_plan, build_narrative_prompt, narrate, sessions_available
from src.store.db import Store
from src.syllabus.parser import parse_text
from tests.fixtures import SYLLABUS_EXCERPT

NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT, level="AS")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.sqlite3")
    s.initialise()
    return s


def add_mcq(store, topic_code, *, key="A", rationales=None):
    body = {
        "stem": "stem",
        "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
        "rationales": rationales or {
            "A": "correct because supply shifts up by the tax",
            "B": "confuses a tax with a subsidy",
            "C": "confuses a shift with a change in elasticity",
            "D": "confuses incidence with a demand-side effect",
        },
    }
    return store.add_question(
        paper_key="paper_1", section_key="mcq", topic_code=topic_code,
        max_marks=1, body=json.dumps(body), answer_key=key, origin="generated",
        syllabus_code="9708", syllabus_version="2026-2028",
    )


def sit(store, pairs, *, mode="mcq_test"):
    """pairs: [(question_id, selected_option_or_None, awarded)]"""
    attempt = store.start_attempt(mode=mode, paper_key="paper_1")
    for ordinal, (qid, selected, awarded) in enumerate(pairs, start=1):
        store.record_response(
            attempt_id=attempt, question_id=qid, ordinal=ordinal, max_marks=1,
            answer_text=selected, awarded=awarded, marker_version="mcq-key-v1",
        )
    store.finish_attempt(attempt)
    return attempt


# ------------------------------------------------------------- diagnosis


def test_no_evidence_means_no_claims(store, spine):
    d = diagnose(store, spine, now=NOW)
    assert d.has_evidence is False
    assert all(w.gap == UNTESTED for w in d.weaknesses)


def test_untested_topics_are_surfaced_not_assumed_strong(store, spine):
    qid = add_mcq(store, "1.1")
    sit(store, [(qid, "A", 1)])
    d = diagnose(store, spine, now=NOW)
    untested = {w.topic_code for w in d.by_gap(UNTESTED)}
    assert "1.1" not in untested
    assert len(untested) == d.topics_total - 1


def test_wrong_answers_with_named_misconceptions_are_a_concept_gap(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(4)]
    sit(store, [(ids[0], "B", 0), (ids[1], "B", 0), (ids[2], "C", 0), (ids[3], "A", 1)])
    d = diagnose(store, spine, now=NOW)
    weakness = next(w for w in d.weaknesses if w.topic_code == "1.1")
    assert weakness.gap == CONCEPT
    assert any("confuses a tax with a subsidy" in e for e in weakness.evidence)


def test_misconceptions_come_from_the_option_actually_chosen(store, spine):
    qid = add_mcq(store, "1.1")
    sit(store, [(qid, "D", 0)])
    d = diagnose(store, spine, now=NOW)
    assert d.misconceptions[0]["misconception"].startswith("confuses incidence")


def test_skipped_questions_are_counted_but_carry_no_misconception(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(2)]
    sit(store, [(ids[0], None, 0), (ids[1], None, 0)])
    d = diagnose(store, spine, now=NOW)
    assert d.skipped == 2
    assert d.misconceptions == []


def test_a_strong_recent_topic_is_not_a_weakness(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(4)]
    sit(store, [(q, "A", 1) for q in ids])
    d = diagnose(store, spine, now=NOW)
    assert all(w.topic_code != "1.1" for w in d.weaknesses if w.gap != UNTESTED)


def test_a_strong_but_stale_topic_becomes_recall_not_concept(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(4)]
    sit(store, [(q, "A", 1) for q in ids])
    later = NOW + timedelta(days=40)
    d = diagnose(store, spine, now=later)
    weakness = next(w for w in d.weaknesses if w.topic_code == "1.1")
    assert weakness.gap == RECALL
    assert "days" in weakness.evidence[0]


def test_thin_evidence_is_flagged_and_damped(store, spine):
    qid = add_mcq(store, "1.1")
    sit(store, [(qid, "B", 0)])
    d = diagnose(store, spine, now=NOW)
    weakness = next(w for w in d.weaknesses if w.topic_code == "1.1")
    assert weakness.is_thin
    solid = next(w for w in d.weaknesses if w.gap == UNTESTED)
    # One wrong answer is a hint; it must not outrank everything on the list.
    assert weakness.priority < 2.0 and solid.priority > 0


def test_priority_is_deterministic(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(3)]
    sit(store, [(q, "B", 0) for q in ids])
    first = [(w.topic_code, w.priority) for w in diagnose(store, spine, now=NOW).ranked()]
    second = [(w.topic_code, w.priority) for w in diagnose(store, spine, now=NOW).ranked()]
    assert first == second


def test_every_weakness_carries_a_remedy(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(3)]
    sit(store, [(q, "B", 0) for q in ids])
    for w in diagnose(store, spine, now=NOW).weaknesses:
        assert w.remedy and w.label


# ---------------------------------------------------------------- grades


def test_as_level_has_no_a_star():
    """The correction this module exists for."""
    with pytest.raises(GradeError, match="no A\\*"):
        normalise_target("A*")


def test_grade_labels_are_accepted_loosely():
    assert normalise_target("Grade B") == "b"
    assert normalise_target(" a ") == "a"


def test_unknown_grade_is_rejected():
    with pytest.raises(GradeError, match="not an AS grade"):
        normalise_target("f")


def test_shipped_thresholds_are_flagged_as_estimates():
    model = default_grades()
    assert model.is_official is False
    assert model.grade_for(85) == "a"
    assert model.grade_for(10) is None


def test_thresholds_must_descend(tmp_path):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(
        {"thresholds": {"a": 60, "b": 70, "c": 50, "d": 40, "e": 30}}
    ))
    with pytest.raises(GradeError, match="descending order"):
        load_grades(path)


def test_a_star_in_a_thresholds_file_is_rejected(tmp_path):
    path = tmp_path / "g.json"
    path.write_text(json.dumps(
        {"thresholds": {"a*": 90, "a": 80, "b": 70, "c": 60, "d": 50, "e": 40}}
    ))
    with pytest.raises(GradeError, match="does not award"):
        load_grades(path)


def test_gap_is_expressed_in_exam_marks():
    model = default_grades()
    gap = gap_to_target(model, current_percent=65, target="a", evidence_marks=90)
    assert gap.gap_percentage_points == 15.0
    assert gap.marks_per_paper_1 == 5   # 15% of 30
    assert gap.marks_per_paper_2 == 9   # 15% of 60


def test_already_at_target_reports_no_gap():
    gap = gap_to_target(default_grades(), current_percent=88, target="a")
    assert gap.already_there
    assert gap.marks_per_paper_1 == 0


def test_thin_evidence_blocks_a_confident_projection():
    gap = gap_to_target(default_grades(), 90, "a", evidence_marks=8)
    assert "too few to project" in gap.confidence_note


# ------------------------------------------------------------------ plan


def test_capacity_comes_from_time_available():
    assert sessions_available(days=10, minutes_per_day=90) == 20
    assert sessions_available(days=10, minutes_per_day=30) == 10  # never below one
    assert sessions_available(days=0, minutes_per_day=90) == 0


def test_plan_follows_the_computed_priority_order(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(3)]
    sit(store, [(q, "B", 0) for q in ids])
    d = diagnose(store, spine, now=NOW)
    plan = build_plan(d, days=5, minutes_per_day=90)
    topic_sessions = [s for s in plan.sessions if s.topic_code]
    expected = [w.topic_code for w in d.ranked()][: len(topic_sessions)]
    assert [s.topic_code for s in topic_sessions] == expected


def test_blank_answers_promote_a_timing_drill_to_the_front(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(3)]
    sit(store, [(q, None, 0) for q in ids])
    plan = build_plan(diagnose(store, spine, now=NOW), days=3, minutes_per_day=45)
    assert plan.sessions[0].is_drill
    assert "Timing drill" in plan.sessions[0].title


def test_plan_respects_the_time_given(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(3)]
    sit(store, [(q, "B", 0) for q in ids])
    d = diagnose(store, spine, now=NOW)
    plan = build_plan(d, days=2, minutes_per_day=45)
    assert plan.total_sessions == 2
    assert plan.unplanned, "areas that did not fit must be reported, not dropped"


def test_each_session_has_a_check(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(3)]
    sit(store, [(q, "B", 0) for q in ids])
    plan = build_plan(diagnose(store, spine, now=NOW), days=4, minutes_per_day=90)
    assert all(s.check and s.what_to_do for s in plan.sessions)


def test_concept_and_application_sessions_prescribe_different_work(store, spine):
    from src.coach.plan import ACTIVITIES

    assert ACTIVITIES[CONCEPT][0] != ACTIVITIES[APPLICATION][0]
    assert "No reading" in ACTIVITIES[APPLICATION][0]
    assert "12-mark" in ACTIVITIES[EVALUATION][0]


def test_narrative_failure_leaves_the_plan_intact(store, spine):
    class Exploding:
        name = "boom"

        def generate(self, *a, **k):
            raise RuntimeError("provider down")

    ids = [add_mcq(store, "1.1") for _ in range(3)]
    sit(store, [(q, "B", 0) for q in ids])
    d = diagnose(store, spine, now=NOW)
    plan = build_plan(d, days=3, minutes_per_day=90)
    before = len(plan.sessions)
    plan = narrate(Exploding(), d, plan)
    assert len(plan.sessions) == before
    assert plan.narrative == ""


def test_narrative_prompt_states_the_plan_is_fixed(store, spine):
    ids = [add_mcq(store, "1.1") for _ in range(3)]
    sit(store, [(q, "B", 0) for q in ids])
    d = diagnose(store, spine, now=NOW)
    plan = build_plan(d, days=3, minutes_per_day=90)
    prompt = build_narrative_prompt(d, plan)
    assert "session" in prompt.lower()
    assert str(d.topics_total) in prompt
