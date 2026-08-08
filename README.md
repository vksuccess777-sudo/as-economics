# AS Economics 9708 — foundation

A private study and exam-practice tool for Cambridge International AS Level
Economics (9708). Built by Karthik Varadharajan.

Currently implemented: the syllabus spine, the attempt log, the assessment
model, the **MCQ engine** (generation, validation, weighted paper assembly,
marking), the **concept tutor**, the **essay engine** (generation, two-pass
marking, diagram declaration) and the **progress dashboard**. What remains is
calibration against real marked scripts — see the roadmap.

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
python scripts/check_pages.py    # confirms all four screens will appear

# fill the question bank (this is the only step that spends tokens)
python scripts/bank_questions.py --all --per-topic 3

streamlit run Home.py
```

`build_syllabus_spine.py` prints the parsed structure and warns if the per-unit
topic counts do not match the published shape of the AS syllabus (6 units, 29
topics: 6/5/3/6/4/5). Treat a warning as a parser bug, not a rounding error.

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

**A model never emits a mark, and never sees what it should not.** The essay
marker splits reading from judging so the judging pass cannot reward fluency,
and caps AO2 in code when a required diagram is missing. Both are covered by
tests that fail if the property is lost.

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
                 essay_generator.py  Section B/C essays, banked as two parts
                 validator.py deterministic quality gate before banking
                 mcq_generator.py  prompt, parse, validate, bank
                 paper_builder.py  weighted selection, balanced vs targeted
src/tutor/       retriever.py lexical search over the spine + scope guards
                 explainer.py grounded explanation, refuses out-of-scope
src/notes/       generator.py  knowledge-base notes, fixed sections, validated
src/coach/       diagnosis.py  gap classification from the attempt log
                 grades.py     AS grade bands, gap to target in exam marks
                 plan.py       revision plan built by code, narrated optionally
src/marking/     mcq_marker.py     zero-token marking, writes the attempt log
                 levels.py         level -> marks ladder, validated on load
                 diagram.py        diagram declaration checking + AO2 cap
                 essay_marker.py   two-pass marker (extract, then judge)
src/store/       schema.sql   attempt log + topic_performance view
                 db.py        thin SQLite layer, no ORM
src/llm/         provider.py  LLMProvider protocol + GroqProvider
                 exceptions.py  LLMRateLimitError with retry-time parsing
scripts/         build_syllabus_spine.py, check_setup.py, bank_questions.py,
                 bank_essays.py, build_notes.py, check_pages.py
tests/           214 tests, no network required
Home.py          Streamlit home: welcome page, module hub, syllabus reference
app_single.py    fallback entry point — every screen, no pages/ discovery
pages/1_MCQ_Practice.py   take a test, submit, review
pages/2_Concept_Tutor.py  ask about a concept, syllabus-grounded
pages/3_Essay_Practice.py write a Paper 2 essay, declare the diagram, get marked
pages/4_AI_Coach.py       progress, weaknesses, diagnosis, target grade, plan, reset
pages/5_Knowledge_Base.py revision notes per topic
data/levels/     paper2_levels.example.json  interim ladder (replace to calibrate)
data/grades/     as_thresholds.example.json  estimated grade thresholds
```

Run the suite with `python -m pytest tests -q`.

### After any upgrade, restart the server

Streamlit re-reads page scripts on every rerun but does **not** re-import
modules under `src/`, and `st.cache_resource` keeps handing out objects built
from the class it first imported. So after unzipping an update, pressing R is
not enough: stop the server with Ctrl+C and run it again. A command-line script
picks up the change immediately, which is what makes this confusing — the same
code works from `python scripts/...` and fails in the app.

Pages 5 and 6 check for this and say so plainly instead of raising
`AttributeError`. The check is written inline in each page rather than in a
shared helper, because a shared helper is itself an imported module and could
be the stale one.

### If the sidebar is empty

Streamlit builds its navigation by globbing `pages/*.py` **next to the entry
script**. Nothing fails loudly when that glob comes back empty: you get a
working app with no way to reach the MCQ test, which reads as though the
feature was never built. A zip extracted flat on Windows causes exactly this —
the page files land beside `Home.py` instead of inside `pages/`.

    python scripts/check_pages.py     # names the cause and the fix
    streamlit run app_single.py       # escape hatch: same screens, one file

`app_single.py` executes the same files `pages/` holds, so the two entry points
cannot drift. `tests/test_app_entrypoints.py` fails if a screen goes missing or
ends up at the repo root.

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

**Done**

1. ~~MCQ generator + timed Paper 1 mock~~
2. ~~Concept tutor, scoped to AS content~~
3. ~~Essay generator, two-pass essay marker, diagram handling~~
4. ~~Weakness dashboard~~
5. ~~Knowledge base — one revision note per topic, batch-written and stored~~
6. ~~AI Coach — progress dashboard + gap diagnosis, target-grade arithmetic,
   dated revision plan, and a one-click reset of attempt history~~

**Pending, in the order that matters**

7. **Calibrate the essay marker.** Build `data/levels/paper2_levels.json` from
   the specimen Paper 2 mark scheme. Until this lands, every essay mark is
   indicative and the app says so on every screen that shows one.
8. **Load calibration cases.** Real marked scripts into `calibration_case`,
   then measure the marker against them. This is what turns "indicative" into
   "trustworthy", and nothing else does.
9. **Publish real grade thresholds.** Replace
   `data/grades/as_thresholds.example.json` with the published thresholds for
   your session so the AI Coach's grade projection stops being an estimate.
10. **Paper 2 Section A — data response.** Built, then the screen was
    withdrawn: it needs a real dataset registered with
    `scripts/add_dataset.py` before it can show anything, and that was not
    wanted. The engine is intact and tested —
    `src/questions/data_response.py`, `src/marking/points_marker.py`,
    `scripts/bank_data_response.py`, and the Store accessors. Restoring the
    screen means putting `pages/7_Data_Response.py` back and re-registering it
    in `scripts/check_pages.py`, `Home.py`, `app_single.py` and
    `tests/test_app_entrypoints.py`. See `UPGRADE_TIER2.md` for how it works.
11. **Full Paper 2 simulator.** Section A + B + C, one clock, 2 hours. Only
    worth building after 10, since it needs Section A to exist.
12. **Second subject.** The `subject` column has been on every table since day
    one. Extract the `SubjectPack` abstraction when Accounting or Business
    actually arrives — not before, or it will be shaped around Economics'
    quirks.

**Examiner-observed mistakes.** `scripts/ingest_examiner_report.py` reads a
Cambridge Principal Examiner Report from your local `data/papers/` copy and
files paraphrased mistake lines against topics, shown in the Knowledge Base
beside the generated ones. AS components only — a report also covers the A
Level papers — and no Cambridge wording is ever stored. See
`UPGRADE_EXAMINER.md`.

**Source policy (three tiers)**

- **Tier 1 — Cambridge.** Your own copies in `data/papers/`, git-ignored, used
  locally for pattern and for the levels descriptors. Nothing committed.
- **Tier 2 — open-licence data**, in `data/reference/datasets/`. Nothing lands
  without a manifest line: source, exact URL, licence, date downloaded. This is
  what Section A stimulus is built from.
- **Tier 3 — ZNotes, tutor2u, Save My Exams, Khan, CORE.** Read them; never
  ingest them. The app links out only, with the licence and any required
  attribution printed alongside.

`data/reference/manifest.json` holds the whole policy, and `src/reference/`
contains no code capable of fetching anything — a test enforces it. Run
`python scripts/check_links.py` to see what every topic offers.

**Deliberately not on the roadmap**

- *Question prediction from past-paper frequency.* It needs a labelled
  multi-year past-paper corpus that cannot be legally accumulated here, and the
  student's own attempt log is stronger evidence about what to revise than
  which topics happened to come up.
- *Embeddings / vector database.* 131 learning outcomes. Lexical retrieval is
  reproducible, dependency-free and has not failed yet.
- *Ingesting third-party revision sites.* Licensing, and it would break the
  claim that everything traces to the official syllabus spine.
- *Teacher and parent dashboards.* One student.

---

## The knowledge base

```bash
python scripts/build_notes.py --all        # 29 notes, one per topic
python scripts/build_notes.py --missing    # only topics without one
python scripts/build_notes.py --topic 4.3  # replaces that topic's note
```

Notes are written in batch and stored, so opening a topic to revise spends
nothing. Each note has a fixed set of sections — definitions, core chains,
diagrams, evaluation lines, common mistakes, exam notes — rather than free
prose. A fixed shape is checkable, and the validator rejects a note that is
missing one or thin on it. Asked for free-form notes, a model quietly skips the
section that is hardest to write, which for AS Economics is always evaluation —
and AO3 is 25% of the AS mark.

The validator also rejects notes that teach A Level content (indifference
curves, the multiplier, market structures beyond AS). Teaching it is not
generosity; it is revision time spent on material the exam cannot ask about.

## The AI Coach

Progress and Coach are one page now: `pages/4_AI_Coach.py`. A student used to
have to visit a scoreboard and a separate diagnosis page and merge them
mentally; everything from both lives here in one read, ordered snapshot →
target → diagnosis → plan, with the denser tables (full topic scoreboard, AO
and command-word breakdowns, sitting history) folded into an expander rather
than removed.

Everything on the page except one optional paragraph is computed from the
attempt log. The diagnosis, the priority order, the session allocation and the
grade arithmetic are deterministic, so they can be checked and they do not
change between two page loads. The model is asked only to write a short
coaching note explaining a plan it did not choose — and if that call fails, the
plan is unaffected.

**Starting fresh.** `Store.reset_progress()` deletes every `attempt` row (and
the `response` rows that cascade with it) for a subject, leaving the question
bank, knowledge base and calibration set untouched — those took real tokens
or effort to build and are not the student's own history. The page exposes
this behind a checkbox-gated confirm at the top of the AI Coach screen, so
test data (or a genuine restart) never has to be lived with permanently.

**Weaknesses are classified, because the remedy differs.** A topic percentage
says where marks went, not why, and re-reading notes on a topic where the
economics is understood but the chain does not complete is wasted revision.

| Gap | Evidence | Remedy |
|---|---|---|
| Concept not secure | wrong options whose rationales name a misconception, or low AO1 | note, tutor, then re-test |
| Analysis incomplete | low AO2, diagram caps | targeted MCQs and 8-mark parts — no reading |
| Judgement missing | low AO3 with sound AO2 | 12-mark part (b) only |
| Known but stale | good score, nothing for three weeks | one skim and a 10-question check |
| No evidence | never tested | test it cold before deciding anything |

**The strongest signal in the database is the distractor actually chosen.** Its
rationale was written at banking time and names the specific misconception a
student holds to pick it. The Coach reports those verbatim rather than guessing
at causes from a percentage.

**Priority is arithmetic**, not a model's opinion: how far below target, how
much syllabus the topic carries, damped by how much evidence there is. One
wrong answer is a hint, not a verdict.

**Grades.** Cambridge International AS Level is graded **a to e — there is no
A\*.** A* is awarded on the full A Level aggregate only, so the top AS target
is grade a, and the code rejects "A*" as a target with that explanation rather
than silently accepting it. The gap to a target is reported in exam marks
("about 5 more MCQs out of 30, 9 more marks out of 60"), rounded up — a gap
rounded down tells a student they need less than they do. Thresholds are
estimates until you replace them: Cambridge sets the real ones per session,
after the exam.

## The essay engine

```bash
python scripts/bank_essays.py --thin 1     # one essay per topic
python scripts/bank_essays.py --topic 4.3 --count 2
python scripts/bank_essays.py --all --dry-run
streamlit run Home.py                      # -> Essay Practice
```

**An essay is two question rows.** Section B/C essays are part (a) 8 marks and
part (b) 12 marks. Each part banks as its own row, linked by a `group_id` in
the rubric JSON. Marking a part is the natural unit of work, per-topic and
per-command-word performance stay meaningful, and the schema needed no
migration — SQLite reads the group id out of the JSON.

**Marking is two passes, and the second one cannot see the writing.**

- Pass 1 *extract* reads the answer and reports what the candidate actually
  said: terms defined, chains of reasoning attempted and whether each one
  completes, judgements offered and whether each is supported, plus errors.
- Pass 2 *judge* sees that structured account, the level descriptors and the
  diagram verdict — and not one word of the prose. It returns a level per
  assessment objective.

A single-pass marker rewards fluency. A confident, well-written answer with two
broken chains reads better than a plain answer with four complete ones, and the
model marks what it reads. Splitting the passes makes a missing link visible as
an absence instead of hidden by good writing. Pass 2's blindness is enforced by
the function signature and by a test that plants a marker string in the prose
and asserts it never reaches the judging prompt.

**Levels in, marks out.** `data/levels/paper2_levels.example.json` holds a
level → marks table per part size. The ladder is validated at load: the AO
maxima must sum to the part total, the top level must award the maximum, and
level 0 must exist. A mis-edited ladder fails loudly rather than quietly marking
a 12-mark part out of 11.

**The shipped ladder is interim and says so everywhere.** Its descriptors are
written from the published AO definitions, not copied from Cambridge, and its
AO mark split is a modelling assumption. `provenance` is `interim`, the marking
page carries a warning above the score, and every stored result records
`calibrated: false`. To calibrate: build `data/levels/paper2_levels.json` from
the specimen Paper 2 mark scheme (git-ignored; it is Cambridge's text). The
loader prefers your file automatically.

## Diagrams: declared, not drawn

This closes the gap the previous README recorded as unresolved. Three options
were considered: ignore diagrams (the marker then over-rewards prose and
under-rewards the student who did the right thing on paper), photograph and
read them with a vision model (hand-drawn axes and shifted curves are exactly
what vision models read unreliably, and a confident misreading of a correct
diagram is worse than no reading), or ask for a structured declaration.

The third is implemented. The student draws on paper as normal, then declares
the diagram: which one, which curve moves, which way, and what happens to each
axis variable. `src/marking/diagram.py` checks it against the question's spec
by exact comparison — no model, no tokens, no ambiguity. The declaration is
itself the discipline the mark scheme rewards.

The consequence is enforced in code, not by the model: **a required diagram
that is missing or wrong caps AO2.** A fluent answer will talk a model out of
strictness; it cannot talk a comparison operator out of it. The cap is a
ceiling only — a student already below it is never lifted to it.

Because the check is exact, a generated diagram spec written in invented
vocabulary would mark every correct declaration wrong. `essay_generator.py`
therefore validates every spec against the known diagram types, curve names,
directions and effects, and rejects the essay if any term is unrecognised.

### Known gaps, recorded not hidden

- **The marker is uncalibrated.** Until real marked scripts sit in
  `calibration_case` and the marker is measured against them, a mark tells you
  whether an answer is improving, not what grade it would get.
- **Section A (data response) is not built.** It needs a source-material
  generator, which is a different job from writing an essay question.
- **No past-paper material is ingested.** Question generation is
  syllabus-anchored.
- **A declared diagram is not a drawn diagram.** A student can declare
  correctly and draw badly. The tool never claims otherwise.
