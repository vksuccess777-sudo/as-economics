# Concept Tutor v3 — "what is macroeconomics" should never have been refused

Unzip over the repo, keeping the folder structure. **Stop the Streamlit server
first (Ctrl+C)** — this touches `src/`, and Streamlit does not re-import
`src/` modules on a rerun.

```bash
python -m pytest tests -q          # expect: 266 passed
python scripts/check_tutor.py      # expect: 18 answered, 6 refused, 0 tokens
streamlit run app.py
```

Includes v2 if you have not applied it yet. This zip also touches
`pages/1_MCQ_Practice.py` and `pages/5_Knowledge_Base.py` — small additions
only, described at the bottom.

---

## What was actually wrong

Three separate faults met in one refusal.

**1. Unit titles were in no document.** The corpus was built from topic titles
and outcome lines. Chapter 4 is called *The Macroeconomy*, and the word
`macroeconomy` appeared in nothing searchable — so a question about half the AS
course had no home. `what is the macroeconomy` failed for the same reason.
Chapters are now documents in their own right, carrying the unit title and the
list of topics inside it.

**2. Vocabulary was an exact string match.** `macroeconomics`, `macro`,
`macroeconimics` and `macroeconomy` are one idea spelt four ways, and only one
spelling ever appears in Cambridge's prose. A student is not going to guess
which — and a student who cannot spell "macroeconomics" is exactly the student
who needs to ask what it means. Words are now *resolved* against the corpus:
exact, then prefix (`macro` → `macroeconomy`), then shared root of six or more
letters (`macroeconimic` → `macroeconomy`), then one typo in a medium word or
two in a long one (`inflasion` → `inflation`, `suply` → `supply`).

Every threshold is set where your real 861-term vocabulary shows no collisions,
and there is a test that fires if `indifference`, `deadweight`, `monopoly`,
`india` or `president` ever finds a home. The substitution is shown to the
student — *"Reading 'macroeconimics' as 'macroeconomy'."* — because a student
who used the wrong word deserves to know which one got answered.

**3. Another plural bug of the same family as the `-ies` one.** `taxes` stemmed
to `taxe` and `losses` to `losse`, so neither met `tax` or `loss`. Sibilant
plurals now strip properly.

---

## Sources — your actual question

Every answer now ends with **Where this comes from**, and each line is
chapter → topic → what inside it was used:

> **Chapter 4 · The Macroeconomy**
> 4.6 Price stability — *syllabus 4.6.4, 4.6.5, 4.6.1 · notes: exam notes, evaluation points*

Two decisions worth knowing about.

**The citations are computed in code from the retrieved documents, never asked
of the model.** A citation a model writes is a citation a model can invent, and
an invented chapter reference is worse than none — it sends a student to the
wrong page and looks authoritative doing it. The system prompt now explicitly
tells the model *not* to write references, because the interface prints real
ones.

**Each source is actionable.** Next to every topic sit two buttons: *Open the
note*, which jumps to that topic in the Knowledge Base, and *Practise it*,
which starts an MCQ set focused on that topic alone. That is the loop that was
missing — read an explanation, see where it lives, test whether it stuck,
without hunting through the sidebar.

When a question is about a whole area rather than a topic ("what is
macroeconomics"), the source reads *Chapter 4 · The Macroeconomy — whole
chapter*. A chapter line only appears when nothing inside it matched;
otherwise it would sit above the specific topics saying strictly less.

---

## One more thing the syllabus already knew

`build_notes.py` reads Cambridge's inline exclusions — "injections and leakages
*(multiplier not required)*" — and refuses to write notes teaching them. The
tutor was not using that. It is now, from the same two functions, so the note
builder and the tutor cannot come to disagree about the syllabus:

> The syllabus names *"multiplier"* but marks it **not required** at AS — it is
> A Level content. Paper 1 and Paper 2 cannot ask about it, so it is not worth
> your revision time yet.

Exclusion matches whole phrases, never single words. Splitting them was the
obvious implementation and the wrong one: `marginal revenue product` would have
retired the word "revenue" and `natural rate of unemployment` the word
"natural", both of which your child needs for content that *is* examinable.

Also: ordinary English still scores in retrieval, but at 0.3 weight. "explain
externalities **in simple terms**" was ranking *6.1 The reasons for
international trade* first, because the syllabus contains "terms of trade" and
the student's "terms" meant nothing at all. It now ranks *3.1 Reasons for
government intervention* first, which is right.

---

## What the diagnostic says on your machine

```
Corpus: 6 chapters + 131 syllabus lines + 171 note sections = 308 documents, 861 terms
  not required at AS: budget line; game theory; indifference curve; kinked demand;
  lorenz curve; marginal revenue product; marginal utility; monopolistic competition;
  multiplier; natural rate unemployment; oligopol; phillips curve

ANSWER  what is macroeconimics      reading macroeconimic->macroeconomy
                                    from Chapter 4 · The Macroeconomy · whole chapter
ANSWER  explain suply and demand    reading suply->supply
REFUSE  unknown_terms indifference  explain indifference curves
REFUSE  not_required multiplier     explain the multiplier
18 answered, 6 refused.
```

All six refusals are correct.

Still worth one command, and it improves three of those refusals:

```bash
python scripts/build_syllabus_spine.py --level A --out data/syllabus_spine_a.json
```

---

## Changes to the other two screens

`pages/5_Knowledge_Base.py` — the sidebar unit and topic pickers now open on a
topic handed over by the tutor. Resolved to an index rather than a widget key,
because a stale key holding a code that is not in the current unit's options
raises.

`pages/1_MCQ_Practice.py` — accepts a topic from the tutor, shows *"Focused on
4.6 Price stability, from the Concept Tutor"* with a one-click way back to the
whole syllabus.

266 tests. `tests/test_tutor_v3.py` covers the resolver — including the test
that off-syllabus words find no home — chapter documents, phrase-level
exclusion and source attribution; `tests/test_tutor_page.py` types the misspelt
question into the real chat box and checks both the answer and the substitution
notice.
