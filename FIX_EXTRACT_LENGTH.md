# Fix: 87 words against a 90 minimum

Both scope gates passed this time. The only rejection left was length, and
it is the same failure twice — the retry repeated the boundary and the
model missed it again.

Unzip over your repo root, **restart Streamlit**, then:

    python scripts\bank_data_response.py --dataset uk-cpi-inflation --topic 4.6 --shape june_2024 --count 1
    python scripts\show_data_response.py

Two files. Suite 523 -> 527 passing, 9 skipped.

## What changed

The prompt asked for "90-260 words". Models do not count words while
writing, they estimate — and an estimate aimed at a boundary lands on both
sides of it. It now asks for **about 180 words**, with the limits stated as
limits:

    "extract": string, background prose of about 180 words (anything under
    90 or over 260 is rejected outright, so aim for the target, not the
    limit)

180 is also closer to what a real Cambridge extract runs to; the boundary
numbers never described anything.

The rejection message now says which way to move and by how much — "add
about 93 more words, aiming for 180" — instead of restating the band the
model had already failed to hit. That is what the retry sees.

Four tests: the target must sit at least 40 words inside each limit, the
schema must ask for it, and a too-short and a too-long extract must each be
told the right direction.

## Note on the gates

Nothing was loosened. The band is still 90-260 and both scope gates are
unchanged — 90 words is a reasonable floor for a stimulus and lowering it
to fit the model would have been the wrong move. Only the instruction
changed.
