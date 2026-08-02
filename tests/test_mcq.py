import json

import pytest

from src.marking.mcq_marker import mark_paper
from src.questions.mcq_generator import (
    GenerationReport,
    MCQGenerator,
    build_prompt,
    parse_response,
    to_item,
)
from src.questions.models import MCQItem
from src.questions.paper_builder import build_paper, topic_weights
from src.questions.validator import ValidationError, is_valid, validate
from src.store.db import Store
from src.syllabus.parser import parse_text
from tests.fixtures import SYLLABUS_EXCERPT


# ------------------------------------------------------------- helpers


def good_item(**overrides) -> MCQItem:
    base = dict(
        stem="A government imposes a specific tax on petrol. What happens to the "
             "supply curve for petrol?",
        options={
            "A": "It shifts vertically upwards by the amount of the tax",
            "B": "It shifts vertically downwards by the tax amount",
            "C": "It becomes perfectly inelastic at the old quantity",
            "D": "It stays unchanged but demand shifts leftwards",
        },
        answer_key="A",
        topic_code="1.1",
        outcome_code="1.1.1",
        rationales={
            "A": "A specific tax raises unit cost, shifting supply up by the tax.",
            "B": "Confuses a tax with a subsidy.",
            "C": "Confuses a shift with a change in elasticity.",
            "D": "Confuses the incidence of a tax with a demand-side effect.",
        },
    )
    base.update(overrides)
    return MCQItem(**base)


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT, level="AS")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.sqlite3")
    s.initialise()
    return s


def bank(store, spine, topic_code, n, prefix="q"):
    ids = []
    for i in range(n):
        item = good_item(topic_code=topic_code, stem=f"{prefix}-{topic_code}-{i} " + "x" * 30)
        ids.append(
            store.add_question(
                paper_key="paper_1", section_key="mcq", topic_code=topic_code,
                max_marks=1, body=item.body_json(), answer_key=item.answer_key,
                origin="generated", syllabus_code="9708", syllabus_version="2026-2028",
            )
        )
    return ids


# ----------------------------------------------------------- validator


def test_a_well_formed_item_passes():
    validate(good_item())


@pytest.mark.parametrize("bad_option", [
    "All of the above",
    "none of the above",
    "Both A and B",
    "B and C only",
])
def test_banned_combination_options_are_rejected(bad_option):
    item = good_item(options={**good_item().options, "D": bad_option})
    with pytest.raises(ValidationError, match="banned combination"):
        validate(item)


def test_duplicate_options_are_rejected():
    opts = good_item().options
    item = good_item(options={**opts, "C": opts["A"] + " ."})
    with pytest.raises(ValidationError, match="duplicates"):
        validate(item)


def test_correct_answer_much_longer_than_distractors_is_rejected():
    """The classic generated-MCQ tell: answerable on length alone."""
    item = good_item(options={
        "A": "It shifts vertically upwards by exactly the amount of the specific "
             "tax, because the tax raises the unit cost of supplying every level "
             "of output for the producer in this market",
        "B": "It shifts down",
        "C": "It is unchanged",
        "D": "It becomes flat",
    })
    with pytest.raises(ValidationError, match="longer than every distractor"):
        validate(item)


def test_missing_rationale_is_rejected():
    item = good_item(rationales={"A": "right", "B": "", "C": "x", "D": "y"})
    with pytest.raises(ValidationError, match="missing rationale for B"):
        validate(item)


def test_wrong_number_of_options_is_rejected():
    item = good_item(options={"A": "one", "B": "two", "C": "three"})
    with pytest.raises(ValidationError, match="options must be exactly"):
        validate(item)


def test_answer_key_outside_abcd_is_rejected():
    with pytest.raises(ValidationError, match="answer_key"):
        validate(good_item(answer_key="E"))


def test_stem_about_the_syllabus_rather_than_economics_is_rejected():
    item = good_item(stem="According to the syllabus, what is opportunity cost "
                          "as defined in the specification document?")
    with pytest.raises(ValidationError, match="refers to the syllabus"):
        validate(item)


def test_topic_code_must_exist_in_the_spine(spine):
    codes = set(spine.topic_codes)
    validate(good_item(topic_code="1.1"), known_topic_codes=codes)
    with pytest.raises(ValidationError, match="not in the syllabus spine"):
        validate(good_item(topic_code="99.9"), known_topic_codes=codes)


def test_is_valid_returns_bool_instead_of_raising():
    assert is_valid(good_item())
    assert not is_valid(good_item(answer_key="Z"))


# ------------------------------------------------------------ shuffling


def test_shuffle_preserves_the_correct_answer_and_its_rationale():
    import random

    item = good_item()
    correct_text = item.correct_option
    correct_rationale = item.rationale_for(item.answer_key)

    for seed in range(20):
        shuffled = item.shuffled(random.Random(seed))
        assert shuffled.correct_option == correct_text
        assert shuffled.rationale_for(shuffled.answer_key) == correct_rationale
        assert set(shuffled.options.values()) == set(item.options.values())
        validate(shuffled)


def test_shuffle_actually_moves_the_key_around():
    """Guards against the model's positional bias becoming the student's strategy."""
    import random

    rng = random.Random(7)
    keys = {good_item().shuffled(rng).answer_key for _ in range(40)}
    assert len(keys) >= 3


# ------------------------------------------------------------- parsing


def test_parse_response_handles_markdown_fences():
    raw = '```json\n[{"stem": "s"}]\n```'
    assert parse_response(raw) == [{"stem": "s"}]


def test_parse_response_handles_preamble_prose():
    raw = 'Here are your questions:\n[{"stem": "s"}]\nHope that helps!'
    assert parse_response(raw) == [{"stem": "s"}]


def test_parse_response_unwraps_an_object_with_a_questions_key():
    raw = '{"questions": [{"stem": "s"}]}'
    assert parse_response(raw) == [{"stem": "s"}]


def test_parse_response_raises_when_there_is_no_array():
    with pytest.raises(ValidationError):
        parse_response("I'm sorry, I can't help with that.")


def test_to_item_accepts_options_as_a_list():
    """Models return a list despite being told to use an object."""
    item = to_item({"options": ["a", "b", "c", "d"], "answer_key": "b"}, "1.1")
    assert item.options == {"A": "a", "B": "b", "C": "c", "D": "d"}
    assert item.answer_key == "B"


def test_build_prompt_includes_outcome_codes(spine):
    prompt = build_prompt(spine.topic("1.1"), 5)
    assert "1.1.4" in prompt
    assert "Scarcity, choice and opportunity cost" in prompt


# ----------------------------------------------------------- generator


class FakeProvider:
    name = "fake"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def generate(self, prompt, **kwargs):
        from src.llm.provider import LLMResponse

        self.calls += 1
        return LLMResponse(text=self.payload, provider=self.name, model="fake")


def _raw(stem, key="A", topic_outcome="1.1.1"):
    return {
        "stem": stem,
        "options": {
            "A": "It shifts vertically upwards by the amount of the tax",
            "B": "It shifts vertically downwards by the tax amount",
            "C": "It becomes perfectly inelastic at the old quantity",
            "D": "It stays unchanged but demand shifts leftwards",
        },
        "answer_key": key,
        "outcome_code": topic_outcome,
        "rationales": {"A": "r1", "B": "r2", "C": "r3", "D": "r4"},
    }


def test_generator_banks_valid_items_and_rejects_bad_ones(store, spine):
    good = _raw("A government imposes a specific tax on petrol. What happens to supply?")
    bad = _raw("too short")
    provider = FakeProvider(json.dumps([good, bad]))

    report = MCQGenerator(provider, store, spine, seed=1).generate_for_topic("1.1", count=2)

    assert report.parsed == 2
    assert report.banked == 1
    assert len(report.rejected) == 1
    assert "too short" in report.rejected[0][1]
    assert store.counts()["question"] == 1


def test_generator_rejects_an_item_for_an_unknown_topic_code(store, spine):
    """A generated outcome_code cannot smuggle in content outside the spine."""
    provider = FakeProvider(json.dumps([_raw("x" * 40 + " what happens to supply?")]))
    gen = MCQGenerator(provider, store, spine, seed=1)
    with pytest.raises(ValueError, match="not in the spine"):
        gen.generate_for_topic("99.9", count=1)


def test_banked_question_is_stored_as_generated_with_one_mark(store, spine):
    provider = FakeProvider(json.dumps([_raw("A government imposes a tax. What happens to supply?")]))
    MCQGenerator(provider, store, spine, seed=3).generate_for_topic("1.1", count=1)
    with store.connect() as conn:
        row = conn.execute("SELECT * FROM question").fetchone()
    assert row["origin"] == "generated"
    assert row["max_marks"] == 1
    assert row["paper_key"] == "paper_1"
    assert json.loads(row["body"])["stem"].startswith("A government")


def test_generation_report_rejection_rate():
    report = GenerationReport(requested=4, parsed=4, banked=1,
                              rejected=[("a", "r"), ("b", "r"), ("c", "r")])
    assert report.rejection_rate == 0.75


# -------------------------------------------------------- paper builder


def test_balanced_weights_follow_outcome_counts(spine, store):
    weights = topic_weights(spine, store, mode="balanced")
    assert weights["1.1"] == 4      # 4 outcomes in the fixture
    assert weights["1.3"] == 1


def test_targeted_mode_favours_untested_topics_over_strong_ones(spine, store):
    bank(store, spine, "1.1", 4)
    attempt = store.start_attempt(mode="mcq_test")
    for i, qid in enumerate(store.candidate_questions()[:4], start=1):
        store.record_response(attempt_id=attempt, question_id=qid["id"],
                              ordinal=i, max_marks=1, awarded=1)

    weights = topic_weights(spine, store, mode="targeted")
    assert weights["1.2"] > weights["1.1"], "untested topic must outrank a mastered one"


def test_targeted_mode_rejects_an_unknown_mode(spine, store):
    with pytest.raises(ValueError, match="balanced"):
        topic_weights(spine, store, mode="random")


def test_build_paper_returns_requested_count_when_bank_is_deep(spine, store):
    for topic in spine.topic_codes:
        bank(store, spine, topic, 5)
    paper = build_paper(store, spine, count=10, seed=1)
    assert len(paper.questions) == 10
    assert paper.shortfall == 0
    assert len({q.question_id for q in paper.questions}) == 10


def test_build_paper_reports_shortfall_rather_than_silently_returning_fewer(spine, store):
    bank(store, spine, "1.1", 3)
    paper = build_paper(store, spine, count=10, seed=1)
    assert len(paper.questions) == 3
    assert paper.shortfall == 7


def test_build_paper_excludes_already_answered_questions(spine, store):
    ids = bank(store, spine, "1.1", 4)
    attempt = store.start_attempt(mode="mcq_test")
    store.record_response(attempt_id=attempt, question_id=ids[0], ordinal=1,
                          max_marks=1, awarded=1)

    paper = build_paper(store, spine, count=10, seed=1)
    assert ids[0] not in {q.question_id for q in paper.questions}
    assert len(paper.questions) == 3


def test_build_paper_can_be_restricted_to_topics(spine, store):
    bank(store, spine, "1.1", 5)
    bank(store, spine, "2.1", 5)
    paper = build_paper(store, spine, count=10, topic_codes=["2.1"], seed=1)
    assert {q.item.topic_code for q in paper.questions} == {"2.1"}


def test_build_paper_is_reproducible_for_a_given_seed(spine, store):
    for topic in spine.topic_codes:
        bank(store, spine, topic, 4)
    a = build_paper(store, spine, count=8, seed=42)
    b = build_paper(store, spine, count=8, seed=42)
    assert [q.question_id for q in a.questions] == [q.question_id for q in b.questions]


# -------------------------------------------------------------- marking


def _paper_of(store, spine, n=3):
    bank(store, spine, "1.1", n)
    return build_paper(store, spine, count=n, seed=1)


def test_marking_computes_the_score_without_an_llm(store, spine):
    paper = _paper_of(store, spine, 3)
    keys = {i: paper.questions[i - 1].item.answer_key for i in (1, 2)}
    wrong = next(k for k in "ABCD" if k != paper.questions[2].item.answer_key)
    keys[3] = wrong

    attempt = store.start_attempt(mode="mcq_test", paper_key="paper_1")
    result = mark_paper(store, paper, keys, attempt_id=attempt)

    assert result.score == 2
    assert result.total == 3
    assert result.percent == 66.7
    assert len(result.wrong_answers()) == 1


def test_skipped_questions_score_zero_but_are_still_recorded(store, spine):
    paper = _paper_of(store, spine, 3)
    attempt = store.start_attempt(mode="mcq_test")
    result = mark_paper(store, paper, {1: paper.questions[0].item.answer_key}, attempt_id=attempt)

    assert result.score == 1
    assert store.counts()["response"] == 3, "a skipped question is evidence, not missing data"
    assert result.answers[1].was_skipped


def test_marking_feeds_the_topic_performance_view(store, spine):
    paper = _paper_of(store, spine, 4)
    keys = {i: paper.questions[i - 1].item.answer_key for i in range(1, 5)}
    attempt = store.start_attempt(mode="mcq_test")
    mark_paper(store, paper, keys, attempt_id=attempt)

    perf = {row["topic_code"]: row for row in store.topic_performance()}
    assert perf["1.1"]["answered"] == 4
    assert perf["1.1"]["pct"] == 100.0


def test_marking_closes_the_attempt(store, spine):
    paper = _paper_of(store, spine, 2)
    attempt = store.start_attempt(mode="mcq_test")
    mark_paper(store, paper, {}, attempt_id=attempt)
    with store.connect() as conn:
        row = conn.execute("SELECT finished_at FROM attempt WHERE id = ?", (attempt,)).fetchone()
    assert row["finished_at"] is not None


def test_feedback_stored_with_each_response_is_readable_offline(store, spine):
    paper = _paper_of(store, spine, 1)
    attempt = store.start_attempt(mode="mcq_test")
    mark_paper(store, paper, {1: "A"}, attempt_id=attempt)
    with store.connect() as conn:
        row = conn.execute("SELECT feedback, marker_version FROM response").fetchone()
    assert json.loads(row["feedback"])["rationale"]
    assert row["marker_version"] == "mcq-key-v1"


def test_by_topic_breakdown(store, spine):
    bank(store, spine, "1.1", 2)
    bank(store, spine, "2.1", 2)
    paper = build_paper(store, spine, count=4, seed=1)
    keys = {i: paper.questions[i - 1].item.answer_key for i in range(1, 5)}
    attempt = store.start_attempt(mode="mcq_test")
    result = mark_paper(store, paper, keys, attempt_id=attempt)
    assert sum(answered for _, answered in result.by_topic().values()) == 4


@pytest.mark.parametrize("variant", [
    "It shifts vertically upwards by the amount of the tax.",
    "It shifts vertically upwards by the amount of the tax ",
    "It shifts vertically upwards by the amount of the tax ,",
    "it shifts  vertically upwards by the  amount of the tax",
    "IT SHIFTS VERTICALLY UPWARDS BY THE AMOUNT OF THE TAX",
])
def test_near_duplicate_options_are_caught_across_punctuation_and_case(variant):
    """Regression: trailing punctuation used to hide a duplicate option."""
    item = good_item(options={**good_item().options, "C": variant})
    with pytest.raises(ValidationError, match="duplicates"):
        validate(item)
