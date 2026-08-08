# Stale-server guard

**Nothing is wrong with your install.** Both errors mean the Streamlit process
was started before you unzipped the last update.

## Do this first — no unzip needed

Ctrl+C in the terminal running Streamlit, then:

    streamlit run Home.py

Both pages should work immediately.

## Why it happened

Streamlit re-reads *page scripts* on every rerun, but modules under `src/` are
imported once and cached in `sys.modules` for the life of the process. On top
of that, `@st.cache_resource` keeps returning the `Store` object it built from
the class it first imported. So the app was calling `note_topics()` on a Store
class from before the upgrade.

`python scripts/build_notes.py` worked at the same moment because it is a fresh
process every time. That difference is the whole confusion: identical code,
working from the command line and failing in the app.

To confirm it is this and not a bad extraction, from the repo root:

    python -c "from src.store.db import Store; print(hasattr(Store,'note_topics'))"

`True` means the file is fine and the server was just stale. `False` means
`src/store/db.py` did not get replaced — re-extract the knowledge-base zip.

## What is in this zip

A guard so this reports itself instead of throwing a traceback. Pages 5 and 6
now check that `Store` has the methods they need, and if not say:

    This Streamlit server is running code from before the last upgrade
    (Store is missing: note, note_topics).
    Stop it with Ctrl+C in the terminal and run `streamlit run Home.py` again.
    Reloading the page is not enough — Streamlit re-reads page scripts but not
    imported modules.

The check is written inline in each page, not in a shared helper: a helper
would be an imported module, and an imported module can itself be the stale
thing.

Verified both ways — silent on a healthy install, and printing the message
above when the Store class is artificially rolled back.

README gained a short section on this, since it will come up on every future
upgrade.
