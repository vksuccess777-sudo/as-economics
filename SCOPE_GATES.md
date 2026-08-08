# Three gates for Section A, from reading the first real question

Unzip over your repo root. Then **restart Streamlit** (this touches
`src/`), and re-bank:

    python scripts\bank_data_response.py --dataset uk-inflation-cpih-cpi --topic 4.6 --shape june_2024 --count 1
    python scripts\show_data_response.py

Files:

    src/questions/data_response.py     the three gates + the prompt instruction
    scripts/bank_data_response.py      passes the allowed set into --dry-run
    tests/test_data_response_scope.py  new, 13 tests
    tests/fixtures.py                  extended with the real 4.6 syllabus lines

Suite 507 -> 520 passing, 9 skipped.

## Gate 1 — measures the syllabus does not name

Your question put 8 of its 20 marks on CPIH. It is a real ONS index and it
was sitting in the data, but 9708 names only "consumer price index (CPI)",
so those parts could be answered faultlessly for nothing.

Three or more capitals is the signal, because a measure that matters in
economics has an acronym: CPIH, RPI, GNP, PPP, ILO. Two-letter forms are
left alone, since UK, US and EU are countries. What counts as in scope is
read off your parsed spine — on your real syllabus that set is CAB, CPI,
GDP, GNI, LRAS, NNI, PED, PES, PPC, SRAS, XED, YED — so a syllabus
revision changes the answer with no code change. Fourth time the answer
has been "derive it from the spine".

The extract may still name CPIH if the table shows it. Refusing to would
make the stimulus dishonest about its own data. Only question parts are
gated.

The same set is written into the prompt, so the model is told what the
validator will reject. A test asserts the two agree.

## Gate 2 — the calculate part

Both real papers ask for a percentage change: June 2024 on Sri Lanka's
trade balance, November 2023 on the price of oil. Yours asked for a
difference. That is a different skill, and the difference between two
percentage rates is measured in percentage points, which a 1-mark prompt
will not say.

## Gate 3 — the data-read part

Yours asked "What was the CPIH rate in 2022?" — one cell. Both papers ask
for a trend or a comparison, and the June 2024 examiner report records
candidates losing that mark for describing every month instead of the
overall trend.

Worth knowing how this one landed: my first version demanded a word like
"trend", and your existing test suite immediately rejected the 2023
specimen's own (b)(ii) — "Consider the extent to which this relationship
is evident in the data" — which names no period at all. The rule now
states the failure rather than an approved vocabulary: a part is rejected
when it names one period of the table and asks for no comparison.

## What this does not fix

Two near-identical inflation series still invite a question about the
difference between the measures. The gate now blocks that, so the
generator has to find something else to ask — but pairing CPI with
something causal would be a better table. Worth doing if the re-banked
question still feels thin.
