"""Reading a worksheet correctly, with no model in the loop.

Every layout here came from writing out worksheets the way schools actually
print them, and two of them found real bugs on the first run:

- sibling parts were being discarded, so "1. Identify, in each case ... (a) ...
  (b) ... (c)" produced ONE item, (c), and lost the other two;
- an inline label chain, "(a) (i) Define the term", left (i) unopened, so it
  was absorbed as a stem when (ii) arrived and vanished the same way.

Both are silent failures — a plausible-looking set of solutions with questions
missing from it — which is why coverage is asserted, not just item counts.
"""

from __future__ import annotations

import zipfile
import io

import pytest

from src.worksheet.classify import (
    EVALUATIVE_WORDS,
    RECALL_WORDS,
    ANALYTIC_WORDS,
    classify_all,
    command_words,
    detect_command_word,
)
from src.worksheet.extract import extract, is_supported
from src.worksheet.models import ESSAY, MCQ, SHORT, STRUCTURED
from src.worksheet.segment import label_chain, segment, strip_marks

from tests.fixtures import SYLLABUS_EXCERPT
from src.config import settings
from src.syllabus.models import SyllabusSpine
from src.syllabus.parser import parse_text


@pytest.fixture(scope="module")
def spine():
    return parse_text(SYLLABUS_EXCERPT)


LISTED_PARTS = """Market Failure Worksheet
Name: .................

1. Identify, in each case, a government policy measure that could be used to
correct the following examples of market failure.
(a) Air pollution from a coal-fired power station. [2]
(b) Under-consumption of vaccinations in a rural district. [2]
(c) A monopoly water supplier charging a very high price. [2]

2. Define the term 'merit good'. [2]
"""

NESTED = """Question 1
(a) (i) Define the term minimum price. (2 marks)
    (ii) Using Extract A, calculate the difference between the two rises.
    (2 marks)
(b) With the help of a supply and demand diagram, explain the effect of a
minimum support price on the market for sugarcane. (6 marks)

Question 2
State two causes of a shift in the supply curve. (2 marks)
"""

MCQ_SHEET = """1. Which of the following shifts the supply curve of wheat to the right?
A An increase in the price of wheat
B A fall in the wage rate of farm workers
C An increase in the demand for bread
D A tax on wheat producers

2. An indirect tax is best described as
A a tax on income
B a tax on wealth
C a tax on expenditure
D a tax on profit
"""


# ------------------------------------------------------------- segmenting


def test_every_lettered_part_survives():
    """The bug that shipped nothing but 1(c) the first time."""
    sheet = segment(LISTED_PARTS)
    labels = [item.label for item in sheet.items]
    assert labels == ["1(a)", "1(b)", "1(c)", "2"]


def test_the_shared_instruction_reaches_each_part():
    """(b) alone is 'Under-consumption of vaccinations' — not a question."""
    sheet = segment(LISTED_PARTS)
    part_b = next(i for i in sheet.items if i.label == "1(b)")
    assert "Identify, in each case" in part_b.context
    assert "vaccinations" in part_b.text
    assert "Identify" not in part_b.text


def test_the_parent_stem_is_not_emitted_as_a_question_of_its_own():
    sheet = segment(LISTED_PARTS)
    assert not any(item.label == "1" for item in sheet.items)


def test_inline_label_chains_open_every_level():
    """'(a) (i) Define ...' must produce 1(a)(i), not swallow it."""
    sheet = segment(NESTED)
    labels = [item.label for item in sheet.items]
    assert "1(a)(i)" in labels
    assert "1(a)(ii)" in labels


def test_a_bare_question_header_still_numbers_its_parts():
    sheet = segment(NESTED)
    assert all(item.number in {"1", "2"} for item in sheet.items)
    assert "2" in [item.label for item in sheet.items]


def test_continuation_lines_stay_with_their_question():
    sheet = segment(NESTED)
    part_b = next(i for i in sheet.items if i.label == "1(b)")
    assert "sugarcane" in part_b.text


def test_all_the_text_is_accounted_for():
    for source in (LISTED_PARTS, NESTED, MCQ_SHEET):
        sheet = segment(source)
        assert sheet.coverage == 1.0, f"lost lines in:\n{source}"
        assert not sheet.warnings


def test_marks_are_read_in_both_printed_forms():
    assert segment("1. Define demand. [3]\n").items[0].marks == 3
    assert segment("1. Define demand. (3 marks)\n").items[0].marks == 3
    assert segment("1. Define demand.\n").items[0].marks is None


def test_the_mark_allocation_is_stripped_out_of_the_question_text():
    item = segment("1. Define demand. [3]\n").items[0]
    assert "[3]" not in item.text
    assert item.text.startswith("Define demand")


def test_options_are_collected_as_options_not_as_questions():
    sheet = segment(MCQ_SHEET)
    assert len(sheet.items) == 2
    assert set(sheet.items[0].options) == {"A", "B", "C", "D"}
    assert "wage rate" in sheet.items[0].options["B"]


def test_two_lettered_lines_are_not_treated_as_a_choice():
    """An OCR pass that upper-cases '(a)' must not invent a two-option MCQ."""
    sheet = segment("1. Compare the two.\nA the first one\nB the second one\n")
    assert sheet.items[0].options == {}
    assert "the first one" in sheet.items[0].text
    assert sheet.coverage == 1.0


def test_a_diagram_is_flagged_only_when_one_is_asked_for():
    asked = segment("1. Using a demand and supply diagram, explain the effect.\n")
    assert asked.items[0].requires_diagram

    # "shifts the supply curve" is vocabulary, not an instruction to draw.
    not_asked = segment(MCQ_SHEET)
    assert not not_asked.items[0].requires_diagram


def test_page_furniture_does_not_become_a_question():
    sheet = segment("Page 2 of 3\n1. Define demand. [2]\n2 / 3\n")
    assert [i.label for i in sheet.items] == ["1"]


def test_an_unnumbered_page_says_so_rather_than_inventing_questions():
    sheet = segment("Discuss the causes of inflation and its effects on savers.")
    assert sheet.items == []
    assert any("No numbered questions" in w for w in sheet.warnings)


def test_a_gap_in_the_numbering_is_reported():
    sheet = segment("1. Define demand. [2]\n\n4. Define supply. [2]\n")
    assert any("Numbering jumps at: 2, 3" in w for w in sheet.warnings)


def test_label_chain_stops_before_an_option_letter():
    """'(a) A firm raises its price' — the A is prose, not option A."""
    chain, rest = label_chain("(a) A firm raises its price")
    assert chain == [("part", "a")]
    assert rest.strip().startswith("A firm")


def test_strip_marks_leaves_ordinary_brackets_alone():
    assert strip_marks("Define GDP (gross domestic product). [2]") == (
        "Define GDP (gross domestic product)."
    )


# ------------------------------------------------------------ classifying


def test_command_words_come_from_the_spine(spine):
    words = command_words(spine)
    assert "evaluate" in words and "define" in words
    assert words["define"], "definitions must come through, not just the names"


@pytest.mark.skipif(
    not settings.spine_path.exists(),
    reason="needs the real parsed spine — the excerpt fixture holds only part of "
           "the command word table",
)
def test_every_grouped_word_is_a_real_cambridge_command_word():
    """The grouping is a judgement; the words are not. Nothing invented here.

    Checked against the full spine rather than the fixture, because this is the
    assertion that stops the classifier acquiring a command word Cambridge does
    not publish — the exact failure mode of the hard-coded Gini regex.
    """
    real = SyllabusSpine.load(settings.spine_path)
    published = set(command_words(real))
    grouped = RECALL_WORDS | ANALYTIC_WORDS | EVALUATIVE_WORDS
    assert grouped <= published, f"not command words: {sorted(grouped - published)}"


def test_the_groups_do_not_overlap():
    assert not RECALL_WORDS & ANALYTIC_WORDS
    assert not RECALL_WORDS & EVALUATIVE_WORDS
    assert not ANALYTIC_WORDS & EVALUATIVE_WORDS


def test_the_leading_command_word_wins(spine):
    text = "Explain why a subsidy lowers price, and assess its effect on farmers."
    assert detect_command_word(text, spine) == "explain"


def test_a_command_word_in_the_shared_stem_is_found(spine):
    """1(a) 'Air pollution from a power station' has no command word of its own."""
    sheet = segment(LISTED_PARTS)
    classify_all(sheet.items, spine)
    part_a = next(i for i in sheet.items if i.label == "1(a)")
    assert part_a.command_word == "identify"


def test_kinds_are_assigned_from_tariff_and_command_word(spine):
    sheet = segment(LISTED_PARTS + MCQ_SHEET.replace("1.", "9.").replace("2.", "10."))
    classify_all(sheet.items, spine)
    kinds = {item.label: item.kind for item in sheet.items}
    assert kinds["1(a)"] == SHORT
    assert kinds["2"] == SHORT
    assert kinds["9"] == MCQ


def test_a_twelve_mark_discuss_is_an_essay(spine):
    sheet = segment("1. Discuss whether a maximum price helps tenants. [12]\n")
    classify_all(sheet.items, spine)
    assert sheet.items[0].kind == ESSAY


def test_a_six_mark_explain_is_structured_not_an_essay(spine):
    sheet = segment("1. Explain how a subsidy affects the market for solar panels. [6]\n")
    classify_all(sheet.items, spine)
    assert sheet.items[0].kind == STRUCTURED


def test_an_evaluative_command_word_with_no_tariff_is_still_an_essay(spine):
    sheet = segment("1. Assess the case for a minimum wage.\n")
    classify_all(sheet.items, spine)
    assert sheet.items[0].kind == ESSAY


# -------------------------------------------------------------- extracting


def test_supported_formats():
    assert is_supported("worksheet.pdf")
    assert is_supported("Worksheet.DOCX")
    assert is_supported("photo.jpg")
    assert not is_supported("worksheet.doc")


def test_an_unreadable_format_names_the_fix():
    result = extract("worksheet.doc", b"\xd0\xcf\x11\xe0")
    assert not result.ok
    assert "docx" in " ".join(result.warnings).lower()


def test_plain_text_comes_through_unchanged():
    result = extract("sheet.txt", LISTED_PARTS.encode("utf-8"))
    assert result.ok and result.kind == "text"
    assert "merit good" in result.text


def test_a_photo_without_a_transcriber_explains_why_not():
    result = extract("page.jpg", b"\xff\xd8\xff", transcriber=None)
    assert not result.ok
    assert "GEMINI_API_KEY" in " ".join(result.warnings)


def test_a_photo_uses_the_transcriber_it_is_given():
    calls = []

    def fake(data, mime):
        calls.append(mime)
        return "1. Define demand. [2]"

    result = extract("page.jpg", b"\xff\xd8\xff", transcriber=fake)
    assert result.ok and "Define demand" in result.text
    assert calls == ["image/jpeg"]


def _docx_bytes(paragraphs: list[str]) -> bytes:
    ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>' for text in paragraphs
    )
    document = f'<?xml version="1.0"?><w:document xmlns:w="{ns}"><w:body>{body}</w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def test_docx_is_read_without_a_third_party_library():
    data = _docx_bytes(["1. Define demand. [2]", "2. Define supply. [2]"])
    result = extract("sheet.docx", data)
    assert result.ok and result.kind == "docx"
    sheet = segment(result.text)
    assert [i.label for i in sheet.items] == ["1", "2"]


def test_a_file_that_is_not_really_a_docx_says_so():
    result = extract("sheet.docx", b"not a zip at all")
    assert not result.ok
    assert "Save As .docx" in " ".join(result.warnings)
