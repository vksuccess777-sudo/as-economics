# Examiner report → the knowledge base

Every `common_mistakes` line in your notes so far was written by a model from
the syllabus outcomes: a plausible guess at what loses marks. A Principal
Examiner Report is the real thing — what candidates across a whole cohort
actually got wrong, written by the people who marked it.

Restart Streamlit after unzipping (Ctrl+C, then `streamlit run Home.py`). This
touches `src/` and adds a table.

---

## Run it

```bash
python scripts/ingest_examiner_report.py --dry-run   # reads and segments only
python scripts/ingest_examiner_report.py             # the only step that spends tokens
python scripts/ingest_examiner_report.py --show      # what is stored
```

`--dry-run` writes nothing at all — not even the new table — and calls no
model. Run it first. On your June 2024 report it prints:

```
12 component(s) in june-2024-examiner-report.pdf:

  USE  9708/11  AS  AS Level Multiple Choice
         Question 7    misconception   666 chars
         ...
  skip 9708/31  A   A Level Multiple Choice
  skip 9708/41  A   A level Data Response and Essays
  ...
34 observation(s) from 6 AS paper(s).
```

Then look in the **Knowledge Base**, under *Common mistakes*.

---

## Three rules, all enforced rather than intended

**1. Nothing Cambridge wrote is stored.** The PDF is read from your local
`data/papers/` copy, held in memory for one script run, and never written
anywhere. What lands in the database is a paraphrase, and `shares_long_shingle`
rejects any output reusing a run of eight words from the source. Eight is short
enough to catch a lifted clause, long enough that shared technical phrasing
doesn't trip it. A test ingests the fixture report and asserts no stored line
shares a shingle with any source observation.

Also rejected: lines mentioning the examiner, the report, a session, a question
number, an option letter, or a percentage of candidates. Those make a line
about the exam rather than about the economics.

**2. AS papers only.** Your report covers twelve components, and **six of them
are A Level** — 9708/31-43. Ingesting those would push A Level content into an
AS knowledge base, which is exactly the failure that produced the Lorenz curve
episode. Level is resolved twice, from the component number *and* the printed
header, and the two must agree or the script refuses rather than guessing.
(Cambridge writes "A level" lowercase in two of those headers; the parser
handles it, and there's a test.)

**3. The spine still decides.** Every produced line goes through the same
out-of-scope check the notes generator uses, derived from your parsed syllabus.
A line teaching indifference curves is rejected by name.

---

## Design decisions worth knowing

**A separate table, not merged into the note.** `observed_mistake` sits beside
`note` rather than inside `note.body` for two reasons: regenerating a note with
`build_notes.py` would silently wipe merged lines, and an examiner's
observation must stay distinguishable from a model's guess. The Knowledge Base
shows them as two blocks with different captions, because they are not the same
kind of claim.

**`topic_code` is nullable.** The best lines in these reports — "candidates
ignored the command word", "diagrams were poorly labelled" — belong to no
single topic. Those are stored as `technique` with no topic and shown in an
expander that applies everywhere. Filing them under whichever topic happened to
share a word would be worse than filing them nowhere.

**Mapping is lexical, with a floor.** Misconceptions are mapped to a topic
using the same retriever the tutor uses, and only when the top hit clears a
confidence floor. Below it, the line is kept as general advice. Confidence is
stored on the row so a bad mapping is visible rather than invisible.

**MCQ papers are split per question.** They comment in running prose with no
headings, so left alone you get one 2,800-character blob covering four
unrelated questions, which matches everything weakly and nothing well. Splitting
on the inline "Question N" took 27 observations to 34 and made the topic
mapping meaningful.

**Re-running is safe.** Lines are fingerprinted; a second run reports duplicates
and writes nothing. Fix a rejection and run again.

---

## Files

New: `src/notes/examiner.py`, `scripts/ingest_examiner_report.py`,
`tests/test_examiner.py`.

Changed: `src/store/schema.sql` (the `observed_mistake` table),
`src/store/db.py` (three accessors; `observed_mistake` added to
`REQUIRED_TABLES`, so an existing database self-upgrades on next open — no
migration script), `pages/5_Knowledge_Base.py`.

Suite 446 → 469.

---

## What this does not do

It does not touch the AI Coach. Cross-referencing "you made this mistake **and**
examiners report it" is the obvious next move, but the Coach has no data to
cross-reference against yet — your attempt log is still empty. Sit a mock and
that becomes worth building.
