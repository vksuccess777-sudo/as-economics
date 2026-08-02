# AS Economics 9708 — foundation

A private study and exam-practice tool for Cambridge International AS Level
Economics (9708). Built by Karthik Varadharajan.

Currently implemented: the syllabus spine, the attempt log, the assessment
model, and the **MCQ engine** — generation, validation, weighted paper
assembly, and marking. Essay marking and the full dashboard are next.

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

# fill the question bank (this is the only step that spends tokens)
python scripts/bank_questions.py --all --per-topic 3

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
src/questions/   models.py    MCQItem, option shuffling
                 validator.py deterministic quality gate before banking
                 mcq_generator.py  prompt, parse, validate, bank
                 paper_builder.py  weighted selection, balanced vs targeted
src/marking/     mcq_marker.py     zero-token marking, writes the attempt log
src/store/       schema.sql   attempt log + topic_performance view
                 db.py        thin SQLite layer, no ORM
src/llm/         provider.py  LLMProvider protocol + GroqProvider
                 exceptions.py  LLMRateLimitError with retry-time parsing
scripts/         build_syllabus_spine.py, check_setup.py, bank_questions.py
tests/           88 tests, no network required
app.py           Streamlit home: spine browser, progress, exam structure
pages/1_MCQ_Practice.py   take a test, submit, review
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

## The MCQ engine

**Generation is a batch job, never part of serving a test.**
`scripts/bank_questions.py` fills the bank; the app only reads from it. The
request path contains no LLM call at all, which is what makes a free tier with
a daily token ceiling workable.

```bash
python scripts/bank_questions.py --all --per-topic 3   # every topic
python scripts/bank_questions.py --topic 4.3 --count 5 # one topic
python scripts/bank_questions.py --thin 5              # top up thin topics
python scripts/bank_questions.py --all --dry-run       # spend nothing, see the plan
```

A rate limit stops the run cleanly and reports the wait; everything banked
before that point is kept.

**Nothing generated is trusted.** Every item passes `validator.py` before it is
banked, and a failure is reported with a reason rather than silently repaired —
a repaired question is an unreviewed question. The rules catch real failure
modes: "all of the above" forms Cambridge never uses, duplicate or near-duplicate
options, missing distractor rationales, stems that quiz the syllabus rather than
the economics, and the classic tell where the correct option is far longer than
every distractor and so is answerable on length alone.

**Options are reshuffled after validation.** Models place the correct answer at a
favourite position far more often than chance; left alone, the student learns the
position rather than the economics.

**Paper assembly has two modes.** `balanced` weights topics by outcome count, so
4.3 (12 outcomes) comes up more than 5.1 (1 outcome), as in the real paper.
`targeted` weights toward weak and untested topics — this is what makes the tool
worth more than a question bank. Selection is seeded and reproducible, and
questions already answered are excluded so a score reflects understanding
rather than recall.

**Marking costs nothing.** Answer-key comparison in code, with the rationales
written at banking time, so review works offline and never touches the budget.
A skipped question scores zero and is still recorded — it is evidence about a
topic, not missing data.

## Roadmap

1. ~~MCQ generator + timed Paper 1 mock~~ — done.
2. **Syllabus knowledge base Q&A**, scoped to AS content. Questions falling in
   topics 7.1–11.6 are declined rather than answered.
3. **Essay marker**, two-pass: pass 1 extracts the student's claims and
   evaluative judgements into a validated AO-tagged object; pass 2 sees only
   that object plus the level descriptors and assigns a level per AO. Needs the
   levels descriptors from the specimen Paper 2 mark scheme first.
4. **Weakness dashboard**, reading the attempt log.

### Known gaps, recorded not hidden

- **Diagram marking is not handled.** AS Economics answers lean on labelled
  AD/AS, PPC and supply-and-demand diagrams. A text-only marker is blind to
  them and will mis-mark. Decide the approach before the essay marker ships.
- **No past-paper material is ingested.** Question generation is
  syllabus-anchored.
- **Marker calibration is unproven** until real marked scripts are loaded into
  `calibration_case` and the marker is measured against them.
