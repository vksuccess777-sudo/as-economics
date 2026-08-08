# Diagrams — drawn in code, for every relevant chapter

Fifteen AS diagrams now render on screen. Unzip over the repo root and
**restart Streamlit** (this touches `src/`).

```powershell
Ctrl+C
# ...unzip over the repo...
python -m pytest -q          # expect 679 passed, 9 skipped
streamlit run Home.py
```

## Where they appear

**Knowledge Base** — a topic that has a diagram now draws it above the
existing "what to label / what shifts" note. Where a diagram has a direction,
radio buttons let you shift AD left or right, or shift demand instead of
supply, and it redraws.

**Concept Tutor** — up to two diagrams appear under an answer, chosen from the
topics the retriever actually grounded that answer in. Not from the answer
text: a diagram only appears when the answer came from a topic that has one.

## The catalogue

| Diagram | Chapter |
|---|---|
| Production possibility curve | 1.5 |
| Demand and supply (shift either curve, either way) | 2.1, 2.4 |
| Elasticity along a straight-line demand curve | 2.2 |
| Perfectly elastic and perfectly inelastic curves | 2.2, 2.3 |
| Consumer and producer surplus | 2.5 |
| Indirect tax and its incidence | 3.2 |
| Subsidy | 3.2 |
| Maximum price | 3.2 |
| Minimum price | 3.2 |
| Buffer stock scheme | 3.2 |
| Circular flow of income | 4.2 |
| AD/AS (shift AD or SRAS, either way) | 4.3–4.6, 5.2, 5.3 |
| Supply-side policy shifting LRAS | 5.4 |
| Trading possibility curve | 6.1 |
| Exchange rate determination | 6.4 |

## Why code draws them, not a model

A model asked to emit SVG produces something that *looks* like a diagram and
is wrong in ways a student cannot detect — axes labelled one way and lines
drawn the other, a curve captioned "shifts right" that goes left, dashed
guides that miss the intersection they claim to mark. A wrong diagram is worse
than none, because it gets copied into an exam answer.

So every coordinate is computed in `src/diagrams/canvas.py`. The caption and
the intersection come from the *same* computed point, which is why they cannot
disagree. There is a test for each direction, including the two students most
often reverse: supply shifting right lowers price and raises quantity, and
SRAS shifting left raises the price level while cutting output.

**No new dependency.** An SVG is a string. Nothing to install, nothing that
behaves differently on Windows.

## The externality fix

The old `DIAGRAM_TYPES` was hand-written from memory and offered
`external_cost` and `external_benefit` as AS content. Externalities are **A
Level** (topic 7.4) in the 2026-2028 syllabus — the word appears nowhere in
your AS spine, and Unit 3 at AS is public goods, merit and demerit goods and
price control. The essay generator passed that whole list into its prompt, so
a generated AS essay could have *required* an A-Level diagram and the marker
would then have capped AO2 for not drawing it. None of your 58 banked essays
did, so nothing is broken — the risk was on the next banking run.

`DIAGRAM_TYPES` is now derived from the rendering catalogue, and
`src/diagrams/scope.py` filters that catalogue against your parsed spine using
the same mechanism the notes validator uses. Nothing asserts what is
examinable. When Cambridge revises the syllabus, regenerating the spine
changes what is offered with no code change.

That gate has already caught me once: I wrote `requires=("maximum price",)`
and it dropped the diagram, because Cambridge's own wording is "maximum **and**
minimum prices". The requirement now matches the syllabus, not my memory.

Old rubric keys (`price_ceiling`, `price_floor`) still validate through
`canonical_type()`, so banked essays are unaffected.

## Files

New: `src/diagrams/` (`canvas.py`, `catalogue.py`, `scope.py`),
`tests/test_diagrams.py`, `tests/test_diagram_pages.py`

Changed: `src/marking/diagram.py`, `pages/2_Concept_Tutor.py`,
`pages/5_Knowledge_Base.py`


## What to ask in the Concept Tutor

A diagram appears when the retriever grounds your answer in a topic that has
one, and the most relevant of them is shown first. Verified against the real
retriever:

| Ask this | You get |
|---|---|
| what happens to price if demand rises | Demand and supply |
| why does the demand curve slope downwards | Demand and supply |
| how does an indirect tax affect the market | Indirect tax |
| how does a subsidy work | Subsidy |
| what is a maximum price | Maximum price |
| how does a minimum price work | Minimum price |
| what is consumer surplus | Consumer and producer surplus |
| explain price elasticity of demand | Elasticity along a demand curve |
| explain the production possibility curve | PPC |
| explain the circular flow of income | Circular flow |
| explain aggregate demand | AD/AS |
| what happens if government spending increases | AD/AS, circular flow |
| what is inflation | AD/AS |
| how do supply side policies work | Supply-side LRAS shift |
| what makes an exchange rate depreciate | Exchange rate |
| explain comparative advantage | Trading possibility curve |

Exam-technique and data-response questions do **not** draw a diagram — those
routes answer from the paper structure and have no topic sources.

One known gap: "explain buffer stock schemes" retrieves topics that carry no
diagram, so nothing appears. Asking about maximum or minimum prices reaches it.


## Size

The diagrams were too small to read, so two things changed.

The canvas itself is bigger — 720x520 instead of 560x400 — with larger type
(17px curve labels, 15-16px everything else), heavier curves and bigger
equilibrium dots. That is legibility at the source, before any scaling.

On top of that the Knowledge Base has a **Diagram size** control: Fit (620px),
Large (900px, the default) or Full width. It applies to every diagram on the
topic.

Rendering moved from `st.image` to inline HTML to make that possible.
`st.image` draws an SVG at its intrinsic size, and the two obvious fixes are
version-traps: `use_container_width` is deprecated in your Streamlit, and
`width="stretch"` needs a newer version than `requirements.txt` guarantees.
Inline HTML has neither problem — Streamlit passes an `<svg>` through
untouched and the SVG's own `width="100%"` fills whatever box it is given.

There is no click-to-zoom. Streamlit's fullscreen button only applies to
raster images, and a JavaScript zoom would be stripped by its HTML sanitiser.
"Full width" plus the browser's own zoom (Ctrl and +) is the reliable route.
