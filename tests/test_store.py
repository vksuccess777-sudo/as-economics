import pytest

from src.store.db import Store


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.sqlite3")
    s.initialise()
    return s


def _question(store, topic_code, max_marks=1, **kw):
    return store.add_question(
        paper_key=kw.pop("paper_key", "paper_1"),
        topic_code=topic_code,
        max_marks=max_marks,
        body=kw.pop("body", "stem"),
        origin=kw.pop("origin", "generated"),
        syllabus_code="9708",
        syllabus_version="2026-2028",
        **kw,
    )


def test_initialise_is_idempotent(tmp_path):
    s = Store(tmp_path / "x.sqlite3")
    s.initialise()
    s.initialise()
    assert s.is_initialised()
    assert s.counts()["question"] == 0


def test_is_initialised_false_before_setup(tmp_path):
    assert not Store(tmp_path / "absent.sqlite3").is_initialised()


def test_origin_is_constrained(store):
    """A generated question must never be recordable as something else."""
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        _question(store, "1.1", origin="past_paper")


def test_topic_performance_aggregates_by_topic(store):
    q1 = _question(store, "4.3", max_marks=1)
    q2 = _question(store, "4.3", max_marks=1)
    q3 = _question(store, "2.2", max_marks=1)
    attempt = store.start_attempt(mode="mcq_test", paper_key="paper_1")

    store.record_response(attempt_id=attempt, question_id=q1, ordinal=1,
                          max_marks=1, awarded=1)
    store.record_response(attempt_id=attempt, question_id=q2, ordinal=2,
                          max_marks=1, awarded=0)
    store.record_response(attempt_id=attempt, question_id=q3, ordinal=3,
                          max_marks=1, awarded=1)
    store.finish_attempt(attempt)

    perf = {row["topic_code"]: row for row in store.topic_performance()}
    assert perf["4.3"]["pct"] == 50.0
    assert perf["4.3"]["answered"] == 2
    assert perf["2.2"]["pct"] == 100.0


def test_unmarked_responses_are_excluded_from_performance(store):
    q = _question(store, "5.2", max_marks=20, paper_key="paper_2", section_key="B")
    attempt = store.start_attempt(mode="single_question")
    store.record_response(attempt_id=attempt, question_id=q, ordinal=1,
                          max_marks=20, answer_text="draft", awarded=None)
    assert store.topic_performance() == []


def test_weakest_topics_ignores_thin_evidence(store):
    """One unlucky wrong answer is not a weakness."""
    attempt = store.start_attempt(mode="mcq_test")
    ordinal = 0
    for topic, results in (("1.1", [0]), ("6.4", [0, 0, 1])):
        for awarded in results:
            ordinal += 1
            q = _question(store, topic, max_marks=1)
            store.record_response(attempt_id=attempt, question_id=q,
                                  ordinal=ordinal, max_marks=1, awarded=awarded)

    weakest = store.weakest_topics(min_answered=3)
    assert [row["topic_code"] for row in weakest] == ["6.4"]


def test_untested_topics_reports_coverage_gaps(store):
    q = _question(store, "1.1", max_marks=1)
    attempt = store.start_attempt(mode="mcq_test")
    store.record_response(attempt_id=attempt, question_id=q, ordinal=1,
                          max_marks=1, awarded=1)

    gaps = store.untested_topics(["1.1", "1.2", "6.5"])
    assert gaps == ["1.2", "6.5"]


def test_ao_levels_are_stored_per_objective(store):
    q = _question(store, "5.3", max_marks=20, paper_key="paper_2", section_key="C")
    attempt = store.start_attempt(mode="single_question", paper_key="paper_2")
    store.record_response(
        attempt_id=attempt, question_id=q, ordinal=1, max_marks=20,
        answer_text="essay", awarded=13,
        ao_levels={"AO1": 3, "AO2": 3, "AO3": 2},
        marker_version="levels-v1",
    )
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM response WHERE attempt_id = ?",
                           (attempt,)).fetchone()
    assert (row["ao1_level"], row["ao2_level"], row["ao3_level"]) == (3, 3, 2)
    assert row["marker_version"] == "levels-v1"
    assert row["marked_at"] is not None


def test_duplicate_ordinal_within_an_attempt_is_rejected(store):
    import sqlite3

    q = _question(store, "1.1")
    attempt = store.start_attempt(mode="mcq_test")
    store.record_response(attempt_id=attempt, question_id=q, ordinal=1, max_marks=1)
    with pytest.raises(sqlite3.IntegrityError):
        store.record_response(attempt_id=attempt, question_id=q, ordinal=1, max_marks=1)


def test_responses_cascade_when_an_attempt_is_deleted(store):
    q = _question(store, "1.1")
    attempt = store.start_attempt(mode="mcq_test")
    store.record_response(attempt_id=attempt, question_id=q, ordinal=1,
                          max_marks=1, awarded=1)
    with store.connect() as conn:
        conn.execute("DELETE FROM attempt WHERE id = ?", (attempt,))
    assert store.counts()["response"] == 0


def test_partial_schema_is_not_reported_as_initialised(tmp_path):
    """Regression: a db holding some tables but not `question` passed the check
    and then crashed the app on its first query."""
    import sqlite3

    path = tmp_path / "partial.sqlite3"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE response (id INTEGER PRIMARY KEY)")
    conn.commit()
    conn.close()

    store = Store(path)
    assert not store.is_initialised()


def test_initialise_repairs_a_partial_schema_without_losing_rows(tmp_path):
    path = tmp_path / "repair.sqlite3"
    store = Store(path)
    store.initialise()
    qid = _question(store, "1.1")

    with store.connect() as conn:
        conn.execute("DROP TABLE calibration_case")
    assert not store.is_initialised()

    store.initialise()
    assert store.is_initialised()
    assert store.counts()["question"] == 1
    assert store.fetch_questions([qid])[0]["id"] == qid
