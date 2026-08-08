# Fix — `test_page_loads_without_spending_a_token` timed out

## What you saw

```
FAILED tests/test_tutor_page.py::test_page_loads_without_spending_a_token
RuntimeError: AppTest script run timed out after 30(s)
1 failed, 594 passed, 9 skipped in 155.29s
```

## Why

The shape of the failure is the diagnosis: **only the first** tutor-page test
failed and the other twelve passed. Nothing about the page changes between
them — what changes is that the first `AppTest` run in a pytest process pays
for everything cold:

* Streamlit's own start-up
* the module imports
* the syllabus spine parse
* loading 171 note sections into the corpus
* the tf-idf build over 308 documents

Every run after that hits `st.cache_resource` and `st.cache_data`, which are
process-global and therefore already warm.

Your suite took 155 seconds where mine takes 15, so that cold first run
crossed a 30-second ceiling I had set on a machine roughly ten times faster.
It is a timing assumption, not a defect in the page.

## The fix

`FIRST_RUN_TIMEOUT = 120` in both page test files, with the reasoning written
down next to it. A timeout is a ceiling, not a wait — a healthy run still
finishes in whatever it finishes in, so this does not slow anything down. It
only stops a slow machine being reported as a broken one.

Unzip over the repo root and run:

```powershell
python -m pytest -q
```

Expect **595 passed, 9 skipped**. No Streamlit restart — this touches tests
only.

## Files

```
tests/test_tutor_page.py
tests/test_mock_page.py
```
