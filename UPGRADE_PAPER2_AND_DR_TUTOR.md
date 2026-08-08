# Upgrade — Paper 2 marked as a paper, and Section A taught in the Concept Tutor

Two changes, both asked for. Unzip over the repo root, then **restart
Streamlit** (this touches `src/`, and a running server keeps the old modules
cached in `sys.modules`).

```powershell
# from the repo root, PowerShell
Ctrl+C                       # stop the running server first
# ...unzip over the repo...
python -m pytest -q          # expect 592 passed, 9 skipped
python scripts\check_pages.py
streamlit run Home.py
```

If a page reports "this Streamlit server is running code from before the last
upgrade", the server was not restarted. To tell a stale server from a file
that did not land:

```powershell
python -c "from src.store.db import Store; print(hasattr(Store,'seen_group_ids'))"
```

`True` means the file is fine and the server was stale. `False` means the file
did not get replaced.

---

## 1 · Paper 2 is now marked as a paper

**What was wrong.** Paper 1 always reported as a paper — "24 / 30" — because
the MCQ marker returns a paper-shaped result. Paper 2 did not. Its three
sections were reported one at a time and nothing added them up, so a sitting
that scored 34 on Sections B and C with Section A skipped showed three tidy
metrics and **85%**. The paper is out of 60 and the student had answered 57%
of it.

**What changed.** `src/marking/mock_report.py` is a new pure-arithmetic module
(no Streamlit, no database, no model) that scores every component against the
marks Cambridge actually sets, read from `syllabus/assessment.py`.

Every component now carries two denominators, and the difference is stated
rather than buried:

| | meaning |
|---|---|
| `official_marks` | what Cambridge sets — Paper 1 is 30, each Paper 2 section 20 |
| `set_marks` | what this sitting actually put in front of the student |

The official total is the headline, because a paper is out of 60 whether or
not the bank was ready. Any shortfall is reported in marks.

On the Mock Test screen:

* **Setup** now states the marks of every component, so you can see before
  starting that an unbanked Section A costs 20 of the 60.
* **Paper 2** gets a `/60` total with a per-section strip underneath. A
  skipped section shows "not sat" and still counts against the paper.
* **Paper 1** reports `/30` even when the bank was short, with a caption
  naming the shortfall and giving the percentage against what was actually
  asked as well. Both numbers, each labelled.
* **A full mock totals `/90`**, which *is* the AS aggregate — 30 and 60 are
  already in the 33/67 ratio, so no weighting is applied. The screen says so.
* **An estimated grade** appears only off a complete sitting of both papers,
  using `data/grades/` with its provenance label. A grade is awarded on the AS
  aggregate; a letter off one paper would be labelling something the letter
  does not describe.

---

## 2 · The Concept Tutor teaches the data response

Section A was the one component that could be generated, served and marked but
never taught. A student who has never seen its shape meets it for the first
time under a clock.

A new panel, **"Learn the data response — Paper 2 Section A"**, with two tabs.

**How Section A works** — costs zero tokens. Both observed shapes rendered as
tables (from `SHAPES`, which were read off the mark schemes in `data/papers/`,
not recalled), time per part derived from 120 minutes ÷ 60 marks, and the cap
consequence stated plainly:

> Up to 4 marks for explanation and analysis and up to 2 for evaluation. An
> answer with no judgement in it stops at 4 out of 6 however well it is argued.

**Walk through a real one** — pick a banked data response, read the stimulus,
then work part by part. Each part shows Cambridge's own command-word meaning
from your parsed spine, what that kind of part demands, how many creditable
points the stored mark scheme actually holds, and an attempt box that checks
your answer against that mark scheme using the existing `PointsMarker`. A
model is called only for the part you actually attempt.

Typed questions ("how do I answer a data response?", "how are the marks split
in Section A?") now route to a Section A answer built from the same facts,
ahead of the general exam-technique route.

### The anti-drift piece

What a student is *taught* a part demands is the **same string** the validator
*rejects* on and the generator is *instructed* with — `KIND_GUIDANCE` in
`questions/data_response.py`. A test fails if they ever disagree. Otherwise
the tutor would be coaching answers to questions the app does not build.

### Coached practice is not an attempt

Nothing in the walkthrough writes to the attempt log. Being coached through a
question says nothing about what you can do unaided, and recording it would
tell the AI Coach the opposite.

The one thing recorded is that the question has been **seen**, in a new
`practice_seen` table (schema v4, self-upgrading on the `note` /
`observed_mistake` pattern — verified against a copy of your real database,
364 questions intact). The Mock Test screen prefers a data response the tutor
has not already taken apart, and warns rather than blocks if every banked one
has been.

---

## Two bugs of mine, both caught by running the screens

1. `store` was never bound at page level in the Concept Tutor — only inside
   `get_tutor()`. The walkthrough crashed on first render.
2. Worse: the walkthrough marked a question "seen" **on render**, so it wrote
   on every Streamlit rerun. Running the tutor page tests once burned all
   twelve banked data responses. It now sits behind an explicit "Open this
   walkthrough" button, and a regression test asserts that two page renders
   write nothing.

The Mock Test screen had **no test of any kind** before this — which is how a
Paper 2 could report three section metrics with nothing adding them up.
`tests/test_mock_page.py` now drives it headless, including the report.

Suite **529 → 592 passing**, 9 skipped.

---

## Files

New:

```
src/marking/mock_report.py
src/tutor/data_response_tutor.py
tests/test_mock_report.py
tests/test_mock_page.py
tests/test_data_response_learning.py
```

Changed:

```
src/marking/points_marker.py      PointsPart now carries kind + command_word
src/tutor/explainer.py            the Section A route
src/store/db.py                   practice_seen, schema v4
src/store/schema.sql              practice_seen
pages/2_Concept_Tutor.py          the learning panel
pages/7_Mock_Test.py              marks on setup, paper totals in the report
tests/test_tutor_page.py          panel + "rendering must not write"
```
