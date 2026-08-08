# as-econ — Worksheet Helper

Unzip **over your existing `as-econ/` folder**, keeping the folder structure,
then **restart Streamlit** (this touches `src/`, so a running server will serve
the old code and throw `AttributeError`).

    python scripts/check_pages.py      # expect: all 6 screens, nothing else
    python -m pytest tests -q          # expect: 364 passed
    streamlit run Home.py

New screen: **📄 Worksheet Helper**. Upload a worksheet the school set — PDF,
Word, a photo of the page, or pasted text — and it is read, split into
questions, and worked through one at a time.

## Try it without spending anything first

    python scripts/check_worksheet.py                    # built-in sample
    python scripts/check_worksheet.py "path/to/sheet.pdf"
    python scripts/check_worksheet.py sheet.docx --prompt 3

Nothing is sent to a model. It prints what was extracted, how it split, the
marks and command word it read off each question, the topic each one matched,
and — with `--prompt` — the exact text a question would be sent. Run this the
first time a new worksheet layout appears.

**The number to watch is COVERAGE.** Below 100% means lines of the sheet were
not placed under any question, so the item list is incomplete.

## How it reads a worksheet

Splitting the sheet into questions is done **in code**, not by a model. Ask an
LLM to "list the questions" in a long document and it quietly returns the first
eight of fourteen, with nothing about the output looking wrong — and a student
would then work through a solution set missing the questions they most needed.
Numbering, `[4]`, `(a)` and option letters are typography; regexes get them
right every time and cost nothing. Only the economics goes to a model.

That check paid for itself immediately. On your own example — *"identify, in
each case, a government policy measure that could be used to correct the
following examples of market failure"* — the first version of the segmenter
returned **only 1(c)**: parts (a) and (b) were absorbed as a stem and dropped.
Coverage read 78% and made it visible. A second layout, `(a) (i) Define the
term ...`, lost (i) the same way. Both are fixed and both now have regression
tests.

What it handles:

| On the sheet | What happens |
|---|---|
| `1.` `2.` `Question 3` `Q4` | top-level questions, numbered or bare |
| `(a)` `(b)` and `(i)` `(ii)` | parts and sub-parts, stacked or inline |
| A stem above lettered cases | becomes shared context — every part gets it, and the stem is not answered on its own |
| `[4]` / `(6 marks)` | read as the tariff, stripped from the question text |
| `A B C D` lines | collected as options; fewer than three is treated as prose, not a choice |
| `Page 2 of 3` | dropped |
| Missing question numbers | reported ("numbering jumps at 2, 3"), never silently filled |

## How it answers

Each question is classified by tariff and command word, and answered in the
shape that question actually wants:

- **Multiple choice** — the letter, why it is right, and why each other option
  is wrong. If you picked a letter first, it says whether the two agree.
- **Short answer** — the answer, the justification, and how the printed marks
  would split.
- **Structured** — the chain of reasoning, plus the diagram to draw.
- **Essay / 12-mark discuss** — a **plan**, not an essay. See below.

Command words come from your parsed spine, with Cambridge's own definition
shown to the student, because the commonest way a worksheet answer loses marks
is answering a different command word from the printed one.

## Three deliberate frictions

**The answer box comes before the solution.** A button that prints worked
answers to a worksheet is a homework machine. Every question shows a place to
write an answer first, and the solution opens underneath. Nothing stops
clicking straight through — the point is that the default path is attempt, then
check, which is the only order that reveals anything about what she knows.

**Essays get a plan, not an essay.** For a 12-mark "discuss", a finished answer
is the least useful thing to hand over: it can be copied without thought, and
it is exactly the writing that needs practising. So those items return the
demand of the question, a paragraph plan, the evaluation lines available and
the diagram expected — then she writes it and pastes it into Essay Practice for
proper levels-based marking. If you would rather see full model answers, say
so and I will add it as a toggle.

**Nothing here touches the attempt log.** A school worksheet has no mark scheme
attached, so every answer on this page is derived by a model reading an
unvalidated question. Marks in your database are computed by code against
validated keys, and mixing the two would corrupt the diagnosis on the AI Coach
page. There is a test asserting the database row counts do not move when a
worksheet is solved.

## Reading the file

No new dependencies:

- **PDF** — pdfplumber, already required. A scanned PDF with no text layer is
  detected and says so, with the fix, instead of returning whitespace.
- **.docx** — read with the standard library (a .docx is XML in a zip).
  A `.doc` needs saving as `.docx` first; it says so.
- **Photo** — the Gemini transcriber your Essay Practice page already uses,
  with a worksheet-specific prompt that preserves numbering and mark
  allocations. Needs `GEMINI_API_KEY`; without it, the page says why.
- **Paste** — for one question at a time.

## Known limitation, worth knowing before she uses it

Topic matching is lexical, and an incidental word can pull a question sideways.
*"Discuss whether a maximum price is the best way to make housing affordable
for low income families"* currently matches **4.1 National income statistics**
on the word *income*, rather than 3.2. The right syllabus line is still in the
prompt (it retrieves several), so the answer is not built on the wrong topic —
but the "Open the note" button would take her to the wrong note.

So the screen labels it **"closest syllabus match"** and both buttons name the
topic they lead to, rather than presenting the match as settled. Fixing the
ranking properly means changing the shared retriever, which the Concept Tutor
also uses, so I left it alone rather than re-tune that at the same time as
shipping this. Worth doing as its own change if you see it mis-hit often.

## Files

    src/worksheet/__init__.py
    src/worksheet/models.py             what an item and a worksheet are
    src/worksheet/extract.py            pdf / docx / photo / text -> text
    src/worksheet/segment.py            text -> items, in code, with coverage
    src/worksheet/classify.py           kind + command word, from the spine
    src/worksheet/solve.py              prompts, validation, one bounded retry
    pages/6_Worksheet_Helper.py
    scripts/check_worksheet.py          token-free diagnostic
    tests/test_worksheet_segment.py     33 tests
    tests/test_worksheet_solve.py       25 tests
    tests/test_worksheet_page.py        11 tests, drives the screen headless

    changed:
    Home.py                             sixth card
    app_single.py                       sixth screen in the fallback router
    scripts/check_pages.py              expects the new screen
    tests/test_app_entrypoints.py       expects the new screen
    tests/fixtures.py                   the excerpt held four command words;
                                        extended with the real rows for Define,
                                        Describe, Discuss, Explain, Identify,
                                        State
    tests/test_parser.py                expected command-word set updated to
                                        match, and a wrapped-meaning assertion
                                        added for Explain

Suite 295 -> 364. All six screens plus `Home.py` and `app_single.py` verified
headless.

## What is not verified

The plumbing is tested with a fake provider; the **quality of the economics is
not**, because that needs your key and I will not spend your quota. Run
`scripts/check_worksheet.py --prompt <label>` to read a prompt before paying
for it, then try two or three real questions and tell me what comes back.
