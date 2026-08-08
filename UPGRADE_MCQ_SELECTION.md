# MCQ Practice — chapter and topic selection

Unzip over the repo. This one touches only `pages/`, so a Streamlit restart is
not strictly required — the page picks the change up on the next rerun.

```bash
python -m pytest tests -q          # expect: 286 passed
```

## What changed

**The filter was already chapter-level — it just called chapters "units".**
The syllabus calls them units, the Concept Tutor calls them chapters, and the
same six things carrying two names inside one app is my inconsistency, not
yours. Everything student-facing now says chapter, including the Knowledge Base
sidebar.

**What was genuinely missing was topic-level choice.** You could sit a paper on
all of Chapter 4 — 52 questions across six topics — or on the whole syllabus,
and nothing in between, unless the Concept Tutor handed a topic over. Now:

- **Chapters** — leave empty for the whole syllabus. Each shows how many
  questions are banked: *Chapter 4 · The Macroeconomy (52)*.
- **Topics** — narrowed to the chosen chapters, or every topic when no chapter
  is chosen, so a single topic can be picked without finding its chapter first.
  Each carries its own count: *4.1 National income statistics (8)*.

**The counts matter more than they look.** Your bank is uneven — 47, 40, 24,
52, 32, 39 across the six chapters — so a "balanced" paper is balanced against
the syllabus, not against what has been banked, and a thin chapter quietly
contributes less than it should. Seeing the numbers before starting is what
makes that visible; Chapter 3 is the one to top up.

**The panel now reports how many questions are actually available** — banked
*and* not yet answered — and caps the length slider to it. Previously the
slider ran to 30 regardless and a short paper came back with no explanation.
The step of 5 is gone as well: with a single topic selected, 5 is often more
than exists.

**The Concept Tutor handover no longer locks the controls.** "Practise it" on
topic 4.1 pre-selects Chapter 4 and topic 4.1 and leaves both editable —
arriving focused and then wanting to widen is a normal thing to do, and a
greyed-out control makes it look impossible.

## Tests

`tests/test_mcq_page.py` drives the panel headlessly. Selection had no test of
any kind before: `build_paper` is well covered, marking is well covered, and
the pickers that decide what reaches them were not. A filter that quietly
selects the wrong topics still produces a plausible-looking paper, which is the
kind of fault nobody notices.

One test exists for a real trap: deselecting a chapter while one of its topics
is still selected leaves session state holding a value that is no longer in the
widget's options, and Streamlit raises on that rather than ignoring it. The
stale topic is cleared before the widget is built.
