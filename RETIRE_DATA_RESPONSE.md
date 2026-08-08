# Data Response screen withdrawn

The Paper 2 Section A screen is gone from the sidebar. Everything else is
untouched.

## Do this after unzipping

```powershell
python scripts\check_pages.py --remove-retired
python scripts\check_pages.py
```

The first deletes `pages/7_Data_Response.py`. **A zip cannot delete files** —
it only replaces and adds — so unzipping alone would leave the old screen on
disk and still in your sidebar, which is exactly the problem that left
`4_Progress.py` and `6_Coach.py` hanging around after they were merged away.

The second should report **6 screens, and nothing else**.

Then restart Streamlit: Ctrl+C, then `streamlit run Home.py`.

If you run the tests before `--remove-retired`, two will fail by design, both
naming the leftover file and telling you to run it. That is the check working.

## What was removed, and what was not

Removed: the screen, its card on the home page, its entry in `app_single.py`,
and its registration in the page checks.

Kept: the engine behind it — `src/questions/data_response.py`,
`src/marking/points_marker.py`, `scripts/bank_data_response.py`,
`scripts/add_dataset.py`, the three Store accessors, and their tests (76 of
them, still running). None of it costs anything while unused, and the
`add_dataset.py` licence gate is part of the source policy regardless of
whether Section A exists.

`tests/test_data_response_page.py` now skips itself when the page file is
absent rather than failing, so restoring the screen restores its coverage with
no other change.

## Restoring it later

Put `pages/7_Data_Response.py` back, then add it to `EXPECTED` in
`scripts/check_pages.py` (removing it from `RETIRED`), to `modules` in
`Home.py`, to `SCREENS` in `app_single.py`, and to `EXPECTED_PAGES` in
`tests/test_app_entrypoints.py`. Ask me and I will ship it.
