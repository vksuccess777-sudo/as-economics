# Reshaping downloads for Section A

Two new files, packaged flat. Unzip over your repo root:

    scripts/tidy_reference_csv.py
    tests/test_tidy_reference_csv.py

Nothing else changes. Suite goes 460 -> 472 passing, 9 skipped unchanged (481 collected).

## Why it exists

Neither portal gives you a CSV `add_dataset.py` can read.

- **World Bank** hands you a zip whose CSV has four metadata lines above
  the header and years running across the top. The loader wants one
  header row and one row per year.
- **ONS** time series open with eight lines of Title/CDID/Unit preamble
  and then stack annual, quarterly (`2014 Q1`) and monthly (`2014 JAN`)
  periods in the same column. Reading a monthly row as if it were the
  year would put a wrong figure in an exam table and nothing downstream
  would notice.

This script reshapes both, joins several indicators on the year, and
writes a plain CSV you then hand to `add_dataset.py`. It has no network
access and writes nothing into `data/reference/` — the registration
script is still the only door in.

## Use

    python scripts/tidy_reference_csv.py --country "United Kingdom" ^
        --from 2015 --to 2024 --out uk-growth.csv ^
        --labels "GDP growth (annual %),Unemployment (% of labour force)" ^
        API_NY.GDP.MKTP.KD.ZG_DS2_en_csv_v2_1234.zip ^
        API_SL.UEM.TOTL.ZS_DS2_en_csv_v2_5678.zip

It prints the table it wrote. **Check those figures against the web page
before you register them** — a reshaper that silently picked the wrong
column would be invisible from here on.

Options: `--country` (default "United Kingdom", ignored for ONS files),
`--labels` (comma-separated headings, one per file — the portal's own
wording is far too long for an exam table), `--from` / `--to`,
`--round` (default 1 decimal place, `-1` to leave figures untouched).

## What it refuses

- a country that is not in the file — and it names the ones that are
- fewer than two usable years
- a `--labels` list whose length does not match the number of files
- a file from neither portal

A year present in one indicator but missing from another is dropped
rather than left blank, so every row in the table is comparable across
all its columns.

## One gotcha worth knowing

`add_dataset.py` checks the URL host against the registry. `world_bank`
is registered as `data.worldbank.org`, so a **DataBank** URL
(`databank.worldbank.org/...`) is refused. Download from the indicator
page instead and register that URL. If you would rather use DataBank,
say so and I will widen the host rule properly.
