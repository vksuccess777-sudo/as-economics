# Concept Tutor v4 — three faults from your three transcripts

Unzip over the repo. **Stop the Streamlit server first (Ctrl+C)** — this
touches `src/`.

```bash
python -m pytest tests -q          # expect: 281 passed
python scripts/check_tutor.py      # expect: 21 answered, 6 refused, 0 tokens
streamlit run app.py
```

Contains everything from v2 and v3. Assessment of what you sent, worst first.

---

## 1. "for exam preparation … how marks are distribution between chapters"

**This one is a regression I introduced in v3, and it is the worst output the
tutor has produced.** Look at the line it printed:

> Reading "exam" as "example", "preparation" as "prepared", "know" as
> "knowledge", "mark" as "market".

Approximate matching was added in v3 to rescue misspelt *economics* terms. I
applied it to every word. Each of those four ordinary words happens to share a
root with a syllabus term, so the question was silently rewritten into a
different one — and then answered, fluently, about government intervention.
That is worse than a refusal: a refusal is visibly wrong, whereas a confident
answer to a question nobody asked is not.

Ordinary English is now checked first and never resolved. Approximate matching
applies only to words the corpus might plausibly own.

**The routing was also wrong.** A question containing "exam", "marks" and
"chapters" is obviously about exam technique, and it went to concept
retrieval because the trigger list had no word for chapter, topic,
distribution or preparation. It does now.

**And the exam route could not have answered it well anyway**, so I gave it
what it needs: every chapter with its topic count, its outcome count, whether
it is micro or macro, and which Paper 2 section its essays fall in. Plus an
explicit instruction that Cambridge publishes no per-chapter mark
distribution and that outcome counts must not be dressed up as one. An
invented mark table is the most damaging answer possible here — your child
would revise to it.

---

## 2. "how do i differentiate gdp and gnp"

Refused, and the refusal was technically correct: GNP is genuinely not in the
9708 AS syllabus. Your syllabus uses **GNI** — it appears in topic 4.1 and in
eight of your notes. GNP appears in none.

So the honest answer exists and is useful: *GNP is not on the AS course; the
measure the syllabus uses alongside GDP is GNI, and here is the difference.*
The tutor now gives it. When a question has one word the corpus does not know
**and** a subject it does, the answer is built from the syllabus content, and
the prompt instructs the model to open by saying the unknown term is not on
the AS course, not to define it, and to name the syllabus's own equivalent if
the retrieved content has one. The page prints *"'gnp' is not in the AS
syllabus — answering the rest of the question from what is."*

The interesting part is what stops this dissolving the guard. My first
attempt used a specificity score: answer around an unknown word if a *rare*
known word anchors the question. It worked on your 308-document corpus and
failed on the 40-document test fixture, because idf scales with corpus size —
exactly the kind of constant that works today and quietly means something
else after the next batch of notes.

The rule now reads sentence structure instead, and needs no tuned number:

- **"indifference curves"** — the unknown word sits directly against the known
  one. The subject is the compound, the compound is off-syllabus. Refused.
- **"gdp and gnp"** — a coordinator sits between them. Two subjects, one of
  which the syllabus covers. Answered around.

`explain indifference curves`, `what is deadweight loss`, `what is a
monopoly`, `explain marginal utility` and `who is the president of India` all
still refuse. `explain externalities and deadweight loss` and `explain
inflation and stagflation` now answer the half that exists.

---

## 3. "what is macro economics"

The answer was good, and correctly refused to draw the circular flow. Two
notes.

**"Where this comes from" looked empty in your paste because the panel was
collapsed.** Attribution hidden behind a click reads as no attribution at all,
which is worse than not offering it. There is now a visible one-line summary —
*From Chapter 4 · The Macroeconomy* — outside the panel, with the topic
breakdown inside it and expanded by default.

**On the answer itself:** it is accurate and pitched right, but notice it was
built almost entirely from the chapter document (unit title plus the list of
topic names), because no individual outcome line matched. That is why it reads
slightly more like an overview than your other answers. It is the correct
behaviour for a whole-course question — I mention it so you know why that one
looks different.

---

## What to watch next

The remaining weak spot is that a whole-chapter question retrieves chapter
text and little else, so orientation answers stay general. If your child asks
many of those, the fix is a short "what this chapter is about" paragraph per
unit in the knowledge base rather than anything in the tutor — say the word and
I will add it to `build_notes.py`.

281 tests. `tests/test_tutor_v4.py` covers all three faults, including a test
that the ordinary-word mangling cannot come back and one asserting the partial
rule behaves identically on the small fixture and the real corpus.
