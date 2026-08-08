# Fix: the viewer printed raw JSON

Replaces the two files from the previous zip.

    ((a)(i))  [1]
          {"prompt": "What was the CPIH annual inflation rate in 2022?"}

The question wording is stored as JSON inside the `body` column, not as
the column itself. I printed the column. Nothing is wrong with your data —
the Mock Test screen was reading it correctly all along, through
`PointsPart.from_row` in `src/marking/points_marker.py`.

The viewer now goes through that same decoder rather than unpacking the
row itself, so it cannot drift from what the mock shows. There is a
regression test asserting `{"prompt"` never reaches the output.

Re-run:

    python scripts\show_data_response.py

Suite 506 -> 507 passing, 9 skipped.
