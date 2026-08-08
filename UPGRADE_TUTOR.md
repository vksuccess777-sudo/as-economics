# Concept Tutor v2 — why the text box was closed, and what changed

Unzip over the repo, keeping the folder structure. Then, in this order:

```bash
# 1. STOP the Streamlit server first (Ctrl+C). This zip touches src/, and
#    Streamlit does not re-import src/ modules on a rerun — a server left
#    running will execute the new page against the old classes.
python -m pytest tests -q          # expect: 248 passed
python scripts/check_tutor.py      # expect: 15 answered, 5 refused, 0 tokens
streamlit run app.py
```

`check_tutor.py` spends nothing. It is the answer to "is the text box broken?"
without a single API call.

---

## The diagnosis

The starter buttons worked and the text box did not, because the buttons quote
the syllabus and a student does not. Every starter prompt is built from
`topic.title` and `outcome.text`, so its every word is by construction in the
syllabus vocabulary. Anything typed by hand is not.

Two guards stood between a typed question and an answer. Both were sound in
intent, and both were miscalibrated in a way only real phrasing exposes.

**1. The vocabulary gate counted words instead of weighing them.**
v1 required 60% of a question's content words to appear somewhere in the 131
syllabus outcome lines. Those lines are Cambridge drafting — terse noun phrases
— and they yield a vocabulary of just 341 distinct words. A student's sentence
is mostly ordinary English, so:

| typed question | v1 verdict | the word that sank it |
|---|---|---|
| how does a subsidy affect the market | refused | `affect` |
| what happens to price when supply increases | refused | `happens`, `increases` |
| what is meant by market failure | refused | `meant`, `failure` |
| why do governments impose maximum prices | refused | `impose` |
| explain externalities in simple terms | refused | `externality` |

The guard was written to catch one thing: the *distinctive* term being absent,
which is what separates "indifference curves" from AS content. It could not
tell `indifference` from `affect`, so it treated both as evidence.

Now only words that are in neither the corpus nor an explicit list of ordinary
English count, and one such word is enough to refuse. `src/tutor/general_words.py`
holds that list. It contains no economics, and it can only ever widen what the
tutor answers — it can never cause a refusal, which is why a plain list is safe
there. The syllabus authority is still your parsed spine, as before.

**2. The stemmer broke on -ies plurals.**
`subsidies` → `subsidie`, while a student's `subsidy` stayed `subsidy`. The two
never met, so subsidies — core unit 3 — read as off-syllabus. Same for
`externalities`, `monopolies`, `policies`. `-ies` now maps to `-y` on both
sides.

---

## What else changed

**The knowledge base is now part of retrieval.** 29 notes were sitting in the
`note` table doing nothing for the tutor. They say AS content in student
English, and they were already scope-validated when generated. Adding them
takes the corpus from 131 documents / 341 terms to 302 documents / 858 terms.
Syllabus outcomes still come first in the prompt and still fix the boundary of
what may be said; the notes supply the explanation.

If you have not run `build_notes.py --all` on a machine, the tutor still works
on the spine alone and the page says so.

**Follow-ups work.** "why?", "give me an example", "simpler please" carry no
content words, so v1 retrieved nothing and refused — the second message in
every conversation was a dead end. A follow-up now inherits the previous
question's retrieval anchor and the model sees the last two exchanges. A new
off-topic question does not inherit anything; there is a test for that, because
that path is the obvious way to smuggle an out-of-scope question in.

**Exam-technique questions have their own route.** "What does 'evaluate'
mean?", "how many marks is Section B?", "how do I structure a 12-mark answer?"
are not concept questions and were being forced through concept retrieval.
They are answered from Cambridge's own 17 command-word definitions in your
parsed spine plus the paper structure in `assessment.py` — so the marks,
timings and AO weightings in the answer come from code, never from the model.

**Refusals say what they could not place.** "I could not place *"deadweight"*
in the AS syllabus" instead of the same sentence every time, plus buttons for
the topics that did score. A refusal you cannot interrogate is
indistinguishable from a broken text box — which is exactly how this failure
hid.

**The browse panel no longer disappears** after the first question, and the
page now builds its provider through `build_provider()`, so a Groq rate limit
falls through to Gemini or Mistral instead of ending the conversation. The
other three pages still use Groq directly; worth changing next time you are in
them.

---

## Worth doing, one command

```bash
python scripts/build_syllabus_spine.py --level A --out data/syllabus_spine_a.json
```

Without it a refusal can only say "I could not place that". With it, the tutor
recognises A Level material and says *"that is A Level content, not worth
revision time yet"* — which is a different and much more useful message for
`monopoly`, `indifference curves`, `Lorenz curve`, `the multiplier`.

---

## Tests

248 passing. The new ones are the interesting part:

- `tests/test_tutor_v2.py` — every scope-gate test is phrased the way a
  fifteen-year-old types, not the way Cambridge writes. Plus a test asserting
  no economics term has leaked into the general-word list, since a leak there
  would silently disarm the guard for that word.
- `tests/test_tutor_page.py` — drives the actual screen headlessly and types
  into the actual chat box. The v1 failure was invisible to the whole suite:
  retrieval had unit tests, the page had a static existence check, and nothing
  in between ever typed a question and looked at what came back.

The fixture gained the real 3.2 outcome lines (taxes, subsidies, maximum and
minimum prices) rather than having its assertions weakened.
