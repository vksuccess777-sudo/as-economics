# Fix: build_provider() missing 'settings'

My bug, and an old one. `build_provider` takes a `settings` argument, but
two scripts I wrote called it with none:

    scripts/bank_data_response.py    line 102
    scripts/ingest_examiner_report.py line 129

Every other caller — the four pages, `bank_essays.py`, `bank_questions.py`,
`build_notes.py` — passes it correctly, which is why nothing else broke.

Unzip over your repo root. Three files:

    scripts/bank_data_response.py       (fixed)
    scripts/ingest_examiner_report.py   (same bug, fixed before you hit it)
    tests/test_script_signatures.py     (new)

Then re-run the command that failed:

    python scripts\bank_data_response.py --dataset uk-inflation-cpih-cpi --topic 4.6 --shape june_2024 --count 1

Nothing under `src/` changed, so no Streamlit restart is needed.

## Why the test suite did not catch it

Scripts and pages are the only code in the project that no test runs.
The unit tests import `DataResponseGenerator` and hand it a fake provider
directly, so the line that builds the real one was never executed. The
error could only appear when a human typed the command — and it appeared
*after* the data table had already printed, which made it look like a
problem with the dataset rather than with the script.

`tests/test_script_signatures.py` closes that gap without running
anything: it parses every file in `scripts/` and `pages/`, finds each call
to a function imported from `src/`, and checks the call against the real
signature. I verified it by reintroducing the bug — it fails with the file,
the line number and the expected signature — and there is a further test
guarding the check itself, so it cannot quietly stop detecting anything.

Suite 476 -> 499 passing, 9 skipped.
