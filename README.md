# AS Economics 9708 — foundation

A private study and exam-practice tool for Cambridge International AS Level
Economics (9708). Built by Karthik Varadharajan.

This repository currently contains **the foundation only** — the syllabus
spine, the attempt log, the assessment model, and the provider interface.
No question generation, marking or dashboard yet, by design.

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # add your GROQ_API_KEY

# Download the 9708 syllabus PDF for your exam year from
# cambridgeinternational.org and save it as data/9708-syllabus.pdf
python scripts/build_syllabus_spine.py
python scripts/check_setup.py

streamlit run app.py
```

`build_syllabus_spine.py` prints the parsed structure and warns if it does not
find 6 units and 27 topics — the published shape of the AS syllabus. Treat a
warning as a parser bug, not a rounding error.

---

## Design decisions worth knowing

**No Cambridge content is committed.** The syllabus PDF, the generated spine,
and anything derived from past papers are all git-ignored. The spine is
generated on your machine from your own copy. This is both a copyright
posture and better engineering: when the syllabus is revised, you regenerate
rather than hand-edit.

**The syllabus is the taxonomy.** Topic codes (`4.3`) and outcome codes
(`4.3.8`) come straight from Cambridge. No invented topic scheme. Every
question and every mark is tagged to a code, which is why the weakness
dashboard needs almost no code of its own — it reads the `topic_performance`
view.

**Marks are always computed, never generated.** `response.awarded` is written
by code: MCQs by answer-key comparison, essays by a level → marks lookup.
A model may emit a *level per AO* with justification; it never emits a mark.
This is the single most important invariant in the system.

**Economics has three assessment objectives**, not four — AO1 Knowledge and
understanding, AO2 Analysis, AO3 Evaluation. AO4 belongs to Business 9609.
Sections B and C of Paper 2 use a levels-based mark scheme, not points.

**`question.origin` is constrained by the database.** A row can only be
`generated`, `user_supplied` or `specimen_derived`. A generated question can
never be silently presented as an authentic past-paper question.

**Subject is a column, not a fork.** `subject` exists on every table from day
one so a second subject is a new row value rather than a schema migration.
The `SubjectPack` abstraction is deliberately *not* built — designing it from
a single example would shape it around Economics' quirks. Extract it when the
second subject actually arrives.

**Provider layer is a stub on purpose.** `GroqProvider` implements the same
`generate()` contract as the FRI provider chain, so the full
Groq → Gemini → Mistral → custom chain with response cache and cooldown can be
dropped in as a straight replacement when the first LLM feature lands.

---

## Layout

```
src/syllabus/    models.py    spine domain objects
                 parser.py    PDF -> spine (pure text->spine layer is testable)
                 assessment.py  paper structure, AO weights, micro/macro split
src/store/       schema.sql   attempt log + topic_performance view
                 db.py        thin SQLite layer, no ORM
src/llm/         provider.py  LLMProvider protocol + GroqProvider
                 exceptions.py  LLMRateLimitError with retry-time parsing
scripts/         build_syllabus_spine.py, check_setup.py
tests/           44 tests, no network required
app.py           Streamlit shell: spine browser, progress, exam structure
```

Run the suite with `python -m pytest tests -q`.

---

## What the tests do and do not prove

The parser is split into `extract_text()` (needs the PDF) and `parse_text()`
(pure). The tests exercise `parse_text()` against a real syllabus excerpt
chosen to contain every layout case that breaks a naive parser: page
furniture, `continued` repeat headers for both units and topics, bullet
lists, wrapped outcome lines, wrapped *bullet* lines, nested sub-bullets, and
the AS/A Level boundary.

They do **not** prove the PDF text layer extracts cleanly on your machine —
that is what `build_syllabus_spine.py`'s 6-unit / 27-topic sanity check is
for. Run it first and read the output.

---

## Roadmap

1. **MCQ generator + timed Paper 1 mock.** Marking costs zero LLM tokens.
   The LLM writes distractor rationales only, cached per question.
2. **Syllabus knowledge base Q&A**, scoped to AS content. Questions falling in
   topics 7.1–11.6 are declined rather than answered.
3. **Essay marker**, two-pass: pass 1 extracts the student's claims and
   evaluative judgements into a validated AO-tagged object; pass 2 sees only
   that object plus the level descriptors and assigns a level per AO.
4. **Weakness dashboard**, reading the attempt log.

### Known gaps, recorded not hidden

- **Diagram marking is not handled.** AS Economics answers lean on labelled
  AD/AS, PPC and supply-and-demand diagrams. A text-only marker is blind to
  them and will mis-mark. Decide the approach before the essay marker ships.
- **No past-paper material is ingested.** Question generation is
  syllabus-anchored.
- **Marker calibration is unproven** until real marked scripts are loaded into
  `calibration_case` and the marker is measured against them.
