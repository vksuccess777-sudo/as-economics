# Fix — `python -m pytest` aborted before any test ran

## What you saw

```
ERROR collecting pages/7_Mock_Test.py
AttributeError: st.session_state has no attribute "mock_flow"
Interrupted: 1 error during collection
```

## Why

pytest collects files matching `test_*.py` and `*_test.py` by default.
**Windows matches those case-insensitively; Linux does not.** So on your
machine `7_Mock_Test.py` matched `*_test.py`, and pytest imported a Streamlit
**page** as a test module. The page ran outside `streamlit run`, found no
session state at `flow = st.session_state.mock_flow`, and errored during
collection — which aborts the entire run before a single test executes.

Nothing is wrong with the page or with the Mock Test screen. It is a naming
coincidence: a screen called `7_Mock_Exam.py` would never have shown it.

This is pre-existing — it arrived with the Mock Test screen, not with the last
upgrade — but you only met it because I asked you to run the suite. My own
verification runs on Linux, where the pattern does not match, so it could
never have caught this. I now check Windows-specific behaviour explicitly.

## The fix

`pytest.ini` at the repo root confines collection to `tests/`, which fixes it
for every page, present and future, on every operating system.

Unzip over the repo root and run:

```powershell
python -m pytest -q
```

Expect **595 passed, 9 skipped**. No Streamlit restart needed — this touches
no application code.

## Guard

`tests/test_app_entrypoints.py` gains two tests. The first fails if `pytest.ini`
is missing or no longer confines collection, and names the pages that would be
imported. The second is a non-vacuity check: it asserts the collision is real,
and skips with a message if you ever rename the page away from it.

## Files

```
pytest.ini                      new
tests/test_app_entrypoints.py   two tests added
```
