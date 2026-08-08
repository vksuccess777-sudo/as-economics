# Tier 2 and Tier 3 sources — what shipped

Two things: a **source registry** that makes the link-out policy structural
rather than a promise, and **Paper 2 Section A**, the one AS component that had
no support at all.

Restart Streamlit after unzipping (Ctrl+C, then `streamlit run Home.py`) —
this touches `src/`, and a running server keeps the old modules in
`sys.modules`. Every new screen checks for that and says so rather than
throwing an AttributeError.

---

## 1. The registry: `data/reference/manifest.json`

Every external source now sits in one file with its licence, and one field
decides everything:

| `use` | means |
|---|---|
| `link_only` | the student may be sent there. No code path ever reads it. |
| `data` | a CSV may be stored under `data/reference/datasets/` and used as Section A stimulus |

That split is not a judgement about quality. ZNotes and tutor2u are good. It
is about what a licence permits and what this app actually needs.

**What the licence checks found**

- **Khan Academy** — CC BY-NC-SA 4.0. Linking and embedding are explicitly
  permitted with attribution plus a required line, which the app now prints
  automatically wherever a Khan link appears. *ShareAlike*, not
  NonCommercial, is what blocks ingestion: text pulled into a generated note
  would push BY-NC-SA onto the note.
- **CORE Econ** — CC BY-**ND** 4.0. The most open-looking teaching content in
  economics still forbids distributing modified material, so summarising it
  into a note is out. Undergraduate level anyway: good for depth, wrong for
  AS scope.
- **ZNotes** — per-reader watermarked PDFs, all rights reserved.
- **tutor2u / Save My Exams / Economics Help** — commercial, all rights
  reserved.
- **World Bank** CC BY 4.0 · **ONS** OGL v3 · **Our World in Data** CC BY 4.0
- **OECD** — CC BY 4.0 for content published from 1 July 2024. Older material
  is under the earlier OECD terms; record it as `OECD Terms`, not as CC.
- **IMF** — *not* Creative Commons. Its own terms permit copying, derivative
  works and redistribution with attribution, subject to an integrity
  condition and carve-outs for third-party material. The manifest records
  `IMF Terms of Use` and a test asserts the string `CC` never appears in it.

**Three guarantees, structural rather than behavioural**

1. `src/reference/` contains no HTTP client. A test reads the files and fails
   if `requests`, `httpx`, `urllib.request` or `urlopen` ever appears. The
   only fetching lives in `scripts/check_links.py --verify`, deliberately
   outside the package.
2. The key sets in `manifest.json` and `links.json` are **closed**. A
   `summary` or `excerpt` field is rejected at load, so someone else's writing
   cannot end up in either file.
3. A curated link's host must match its source's host, and a link's topic must
   exist in your parsed spine. A link claiming to be Khan but pointing
   elsewhere fails to load, because the attribution printed under it would be
   a lie.

`require_data_source()` is the single choke point. Try to attribute a dataset
to ZNotes and the script refuses:

```
REFUSED: ZNotes is registered as 'link_only': it may be linked to, never read.
```

### `links.json` ships empty on purpose

A deep link written from memory is plausible and wrong, and a dead link the
night before a mock is worse than no link. Nothing goes in there until it has
been opened. Meanwhile **every topic still offers live site-scoped search
links**, built in code from the syllabus wording — they cannot rot.

To add one, put the entry in and verify it:

```bash
python scripts/check_links.py            # what every topic offers, no network
python scripts/check_links.py --verify   # HEAD-checks every URL
```

The panel appears at the bottom of a **Knowledge Base** note and under a
**Concept Tutor** answer, anchored to the topic the answer came from. It opens
with a warning that those sites are not written to 9708 — Khan and CORE will
happily teach A Level and degree material, and the notes here decide what is
examinable.

---

## 2. Paper 2 Section A — data response

### The shapes are read off your own mark schemes, not remembered

| | parts |
|---|---|
| 2023 specimen 9708/02 | (a) 2 · (b)(i) 2 · (b)(ii) 2 · (c) 2 · (d) 6 · (e) 6 |
| June 2024 9708/21 | (a)(i) 1 · (a)(ii) 1 · (b) 2 · (c) 4 · (d) 6 · (e) 6 |

Different openings; identical where it counts. Twenty marks, low-mark
data-handling first (including a calculation in 2024), then two 6-mark
"Assess…" parts each split **up to 4 for analysis, up to 2 for evaluation**.
That split is now the marker's caps, taken from Cambridge's own wording. A
test asserts every shape totals 20 and ends 6+6.

### The model never writes a number

The table renders from your CSV. The model writes only prose around it, and
every figure in the extract or a part prompt must already exist in the table
or the whole item is rejected and retried with the reason fed back.
`"Growth reached 7.2%"` beside a table saying `7.6` does not survive.

This is the guard the feature rests on. An invented statistic in a stimulus is
the most damaging thing this project could produce: the student would reason
correctly from it and still be wrong, and nothing on the page would look off.

Also enforced: the extract must set up a quoted phrase that a later part picks
up (a real Cambridge pattern), a 6-mark part must open with a judgement
command word, and each part needs at least as many indicative points as it has
marks — otherwise full marks are unreachable however well the student writes.

### Marking

Section A is point-marked, not levels-marked, so `src/marking/points_marker.py`
is a different shape from the essay marker. The model is asked one thing per
indicative point — *was this point made?* — and is never told what anything is
worth. `award()` counts, applies the caps and clamps to the part maximum. A
model that returns "met" on every point still cannot exceed the part total, and
any number it writes is ignored.

A blank part scores zero with **no model call**. Skipped is evidence, not
missing data.

**Provenance.** The credited points were written by the generator, not by
Cambridge — Section A schemes are bespoke per question, so there is nothing
generic to calibrate against the way the levels ladder was. Every stored
result records `indicative: true` and the screen says so above the score. Use
it to see which parts are weak, not as a predicted grade.

AO levels are stored as NULL for these responses: inventing a level would put
fabricated rows into the AI Coach's AO table.

---

## Getting a first data response on screen

A data response needs real data, and I will not ship a fabricated CSV.

1. **Download something.** Two or three columns and six to ten rows is the
   right size — a year column plus one or two indicators. Good starting
   points: World Bank Open Data (CC BY 4.0), ONS (OGL v3), Our World in Data.
   For local context, RBI or MoSPI.

2. **Register it.** This is the only door in; it records the source, exact
   URL, licence and today's date, then prints the table back.

   ```bash
   python scripts/add_dataset.py ~/Downloads/gdp.csv \
       --slug india-growth-inflation \
       --title "Real GDP growth and inflation, India" \
       --source world_bank \
       --url https://data.worldbank.org/indicator/... \
       --region India
   ```

3. **Bank a question** (this is the only step that spends tokens):

   ```bash
   python scripts/bank_data_response.py --list
   python scripts/bank_data_response.py --dataset india-growth-inflation \
       --topic 4.1 --columns "Year,GDP growth (%),Inflation (%)" --rows 8
   python scripts/bank_data_response.py --dataset ... --topic 4.1 --dry-run
   ```

   `--dry-run` prints the exact prompt and spends nothing.

4. **Sit it** — *Data Response* in the sidebar, about 40 minutes for 20 marks.

---

## Files

New: `src/reference/{registry,links,dataset,panel}.py`,
`src/questions/data_response.py`, `src/marking/points_marker.py`,
`pages/7_Data_Response.py`, `scripts/{add_dataset,bank_data_response,check_links}.py`,
`data/reference/{manifest,links}.json`, four test files.

Changed: `src/store/db.py` (three Section A accessors), `Home.py`,
`app_single.py`, `scripts/check_pages.py`, `pages/2_Concept_Tutor.py`,
`pages/5_Knowledge_Base.py`, `tests/test_app_entrypoints.py`.

Suite 364 → 446. All seven screens verified headless, including a full
submit → mark → attempt-log run against a temporary database.

---

## Deliberately not done

- **No ingestion of ZNotes, tutor2u, Save My Exams, CORE or Khan.** Beyond
  licensing: every scope gate in this project derives from *your parsed
  spine* — the A-Level leak check, `out_of_scope_terms`, the tutor's refusals,
  the `(… not required)` bracket logic. Third-party notes written to a
  different syllabus version put content in the corpus that those gates cannot
  adjudicate, and the tutor starts confidently teaching Lorenz curves again.
- **No crawler**, for any tier.
- **No curated links written from memory.** See above.

## Still open

- The examiner report is on your disk and `common_mistakes` in your notes has
  never seen it — those are currently the model's guess at what loses marks,
  not examiners' observations. Not a duplicate.
- `calibration_case` is still empty, so the essay marker remains unmeasured.
- Your attempt log is empty again. The Coach has nothing to diagnose until a
  mock is sat.
