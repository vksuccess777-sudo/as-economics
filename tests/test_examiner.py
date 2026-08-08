"""Reading an examiner report without copying it, and without importing A Level.

The two rules under test are the two ways this feature could go badly wrong:
storing Cambridge's words, and filing A Level observations into an AS
knowledge base.
"""

from __future__ import annotations

import json

import pytest

from src.llm.provider import LLMResponse
from src.notes.examiner import (
    MISCONCEPTION,
    TECHNIQUE,
    ExaminerError,
    ExaminerIngestor,
    Mistake,
    Observation,
    parse_mistakes,
    shares_long_shingle,
    split_observations,
    split_papers,
    strip_furniture,
    validate_line,
)
from src.store.db import Store
from src.syllabus.parser import parse_text
from tests.fixtures import SYLLABUS_EXCERPT

REPORT = """Cambridge International Advanced Subsidiary Level
9708 Economics June 2024
Principal Examiner Report for Teachers
ECONOMICS
Paper 9708/11
AS Level Multiple Choice
General comments
Most candidates answered between 14 and 23 questions correctly. Candidates
performed less well in the macroeconomic questions.
Comments on specific questions
Question 7 was answered correctly by 31 per cent of the candidates. The
question required candidates to calculate the supply of each firm at two
prices, and weaker candidates chose a firm whose supply rose with price.
Question 12 shows a continued misunderstanding of the nature of a good. A good
provided free of charge is not therefore a free good, and a good provided by
the government is not therefore a public good.
© 2024
Paper 9708/21
AS Level Data Response and Essays
Key messages
Candidates need to focus on the command word being used in a question.
Diagrams should be correctly drawn and clearly labelled, and a number of
scripts showed poor labelling or none at all.
General comments
It was obvious in some answers that candidates had not looked closely at the
command word being used in the question.
Comments on specific questions
Question 1
Many candidates described what happened in every month shown in the table
rather than identifying the overall trend across the whole period.
Question 2
Some candidates wrote about demerit goods although the question made no
reference to them.
Paper 9708/41
A level Data Response and Essays
Key messages
Candidates should be able to analyse the shape of the long run average cost
curve and explain economies of scale in a monopolistically competitive market.
Comments on specific questions
Question 1
Candidates confused the marginal revenue product of labour with the average
revenue product.
"""


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT, level="AS")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.sqlite3")
    s.initialise()
    return s


@pytest.fixture
def papers():
    return split_papers(strip_furniture(REPORT))


# ---- AS only ------------------------------------------------------------


def test_all_three_components_are_found(papers):
    assert [p.code for p in papers] == ["9708/11", "9708/21", "9708/41"]


def test_a_level_components_are_marked_and_excluded(papers):
    """The single most important line in this file. A June report covers
    9708/31-43 as well, and those are A Level."""
    assert [p.level for p in papers] == ["AS", "AS", "A"]
    assert [p.code for p in papers if p.is_as] == ["9708/11", "9708/21"]


def test_lowercase_a_level_in_a_header_is_still_a_level(papers):
    """Cambridge writes 'A level' in some headers and 'A Level' in others."""
    assert papers[2].title == "A level Data Response and Essays"
    assert papers[2].level == "A"


def test_a_header_that_contradicts_its_component_number_is_refused():
    text = REPORT.replace(
        "Paper 9708/41\nA level Data Response and Essays",
        "Paper 9708/41\nAS Level Data Response and Essays",
    )
    with pytest.raises(ExaminerError, match="refusing to guess"):
        split_papers(strip_furniture(text))


def test_running_headers_are_stripped():
    cleaned = strip_furniture(REPORT)
    assert "Principal Examiner Report" not in cleaned
    assert "© 2024" not in cleaned


# ---- segmentation -------------------------------------------------------


def test_key_messages_and_general_comments_become_technique(papers):
    observations = split_observations(papers[1])
    kinds = {o.ref: o.kind for o in observations}
    assert kinds["Key messages"] == TECHNIQUE
    assert kinds["General comments"] == TECHNIQUE


def test_numbered_questions_become_separate_misconceptions(papers):
    refs = [o.ref for o in split_observations(papers[1]) if o.kind == MISCONCEPTION]
    assert refs == ["Question 1", "Question 2"]


def test_mcq_running_prose_is_split_per_question(papers):
    """No headings on an MCQ paper — one blob covering four unrelated
    questions maps to no topic usefully."""
    refs = [o.ref for o in split_observations(papers[0]) if o.kind == MISCONCEPTION]
    assert refs == ["Question 7", "Question 12"]


def test_a_question_chunk_holds_only_its_own_text(papers):
    chunks = {o.ref: o.text for o in split_observations(papers[0])}
    assert "free good" in chunks["Question 12"]
    assert "free good" not in chunks["Question 7"]


# ---- the copyright guard ------------------------------------------------


SOURCE = (
    "Many candidates described what happened in every month shown in the table "
    "rather than identifying the overall trend across the whole period."
)


def test_a_lifted_clause_is_caught():
    lifted = "Do not describe what happened in every month shown in the table."
    assert shares_long_shingle(SOURCE, lifted)


def test_a_real_paraphrase_passes():
    paraphrase = "State the overall direction of a trend instead of listing each period in turn."
    assert not shares_long_shingle(SOURCE, paraphrase)


def test_validate_rejects_a_lifted_line():
    observation = Observation(paper="9708/21", ref="Question 1", kind=MISCONCEPTION, text=SOURCE)
    with pytest.raises(ExaminerError, match="paraphrased, not quoted"):
        validate_line(
            "Avoid describing what happened in every month shown in the table when asked.",
            observation,
            forbidden=[],
        )


def test_validate_rejects_a_line_that_names_the_report():
    observation = Observation(paper="9708/21", ref="Question 1", kind=MISCONCEPTION, text=SOURCE)
    for bad in (
        "The examiner noted that trends were often listed period by period.",
        "In Question 1 the overall direction was often missed by weaker students.",
        "Only 31 per cent of students gave the overall direction of the change.",
    ):
        with pytest.raises(ExaminerError, match="refers to the report"):
            validate_line(bad, observation, forbidden=[])


def test_validate_rejects_a_line_teaching_a_level_content():
    observation = Observation(paper="9708/21", ref="Question 1", kind=MISCONCEPTION, text=SOURCE)
    with pytest.raises(ExaminerError, match="teaches A Level content"):
        validate_line(
            "Remember to use an indifference curve when comparing two goods here.",
            observation,
            forbidden=["indifference curve"],
        )


def test_validate_rejects_a_line_too_long_to_be_advice():
    observation = Observation(paper="9708/21", ref="Q1", kind=MISCONCEPTION, text=SOURCE)
    with pytest.raises(ExaminerError, match="characters"):
        validate_line("word " * 80, observation, forbidden=[])


def test_parse_mistakes_accepts_an_empty_list():
    """An observation describing only what candidates did well must be allowed
    to produce nothing. An invented mistake is worse than none."""
    assert parse_mistakes(json.dumps({"mistakes": []})) == []


def test_parse_mistakes_requires_the_key():
    with pytest.raises(ExaminerError, match="no 'mistakes' list"):
        parse_mistakes(json.dumps({"lines": ["x"]}))


# ---- ingestion ----------------------------------------------------------


class FakeProvider:
    name = "fake"

    def __init__(self, lines):
        self.lines = lines
        self.calls = 0

    def generate(self, prompt, **kwargs):
        self.calls += 1
        return LLMResponse(
            text=json.dumps({"mistakes": self.lines}), provider="fake", model="fake"
        )


GOOD_LINES = [
    "State the overall direction of a change instead of listing each period in turn.",
    "A good supplied at no charge is not automatically a free good in economic terms.",
]


def test_ingest_writes_lines_and_maps_a_topic(spine, store, papers):
    observations = split_observations(papers[1])
    ingestor = ExaminerIngestor(FakeProvider(GOOD_LINES), store, spine)
    report = ingestor.ingest(observations, source="test report")

    assert report.written > 0
    rows = store.observed_mistakes()
    assert rows
    assert all(row["source"] == "test report" for row in rows)


def test_technique_lines_are_never_filed_under_a_topic(spine, store, papers):
    observations = [o for o in split_observations(papers[1]) if o.kind == TECHNIQUE]
    ExaminerIngestor(FakeProvider(GOOD_LINES), store, spine).ingest(
        observations, source="test report"
    )
    for row in store.observed_mistakes(kind="technique"):
        assert row["topic_code"] is None


def test_rerunning_the_ingest_does_not_duplicate(spine, store, papers):
    observations = split_observations(papers[1])
    ingestor = ExaminerIngestor(FakeProvider(GOOD_LINES), store, spine)
    first = ingestor.ingest(observations, source="test report")
    second = ingestor.ingest(observations, source="test report")

    # Every attempt on the second run is a duplicate. (The fake returns the
    # same two lines for every observation, so some of the FIRST run's
    # attempts are duplicates too — same paper, same topic, same text is the
    # same line however many places it was observed.)
    assert second.written == 0
    assert second.duplicates == first.written + first.duplicates


def test_a_rejected_line_is_reported_and_not_stored(spine, store, papers):
    lifted = ["Many candidates described what happened in every month shown in the table."]
    observations = [o for o in split_observations(papers[1]) if o.ref == "Question 1"]
    report = ExaminerIngestor(FakeProvider(lifted), store, spine).ingest(
        observations, source="test report"
    )
    assert report.written == 0
    assert report.rejected
    assert store.observed_mistakes() == []


def test_the_source_text_is_never_stored(spine, store, papers):
    """Nothing Cambridge wrote may end up in the database."""
    observations = split_observations(papers[1])
    ExaminerIngestor(FakeProvider(GOOD_LINES), store, spine).ingest(
        observations, source="test report"
    )
    stored = " ".join(row["text"] for row in store.observed_mistakes())
    for observation in observations:
        assert not shares_long_shingle(observation.text, stored)


def test_fingerprints_differ_by_line(spine):
    a = Mistake(text="one thing", kind=TECHNIQUE, paper="9708/21", ref="x")
    b = Mistake(text="another thing", kind=TECHNIQUE, paper="9708/21", ref="x")
    assert a.fingerprint("s") != b.fingerprint("s")
