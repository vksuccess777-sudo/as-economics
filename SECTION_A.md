# Section A — four datasets registered

Unzip over your repo root (where `Home.py` lives). It adds:

    data/reference/datasets/uk-growth-unemployment/{data.csv,manifest.json}
    data/reference/datasets/uk-inflation-cpih-cpi/{data.csv,manifest.json}
    data/reference/datasets/uk-current-account-trade/{data.csv,manifest.json}
    data/reference/datasets/uk-exchange-rate-current-account/{data.csv,manifest.json}
    scripts/tidy_reference_csv.py     (replaced — see "Fix" below)
    tests/test_tidy_reference_csv.py  (replaced — 12 tests -> 16)
    .gitignore                        (replaced — one stanza added)

I built these from the files you put in `data/reference/`, using your own
`add_dataset.py`, so every manifest records the real source, page, licence
and date. Nothing was fabricated and nothing was fetched.

    python scripts/bank_data_response.py --list

should show all four.

## What each one is for

| Slug | Columns | Anchor topic |
|---|---|---|
| `uk-growth-unemployment` | GDP growth %, unemployment % | 4.4 / 4.5 |
| `uk-inflation-cpih-cpi` | CPIH %, CPI % | 4.6 |
| `uk-current-account-trade` | current account % of GDP, trade % of GDP | 6.3 / 6.1 |
| `uk-exchange-rate-current-account` | GBP per US$, current account % of GDP | 6.4 |

All 2015–2024, ten rows each — the range the specimen and June 2024 papers
both sit in.

Two deliberate choices worth knowing:

- **Every table has two data columns, not one.** Cambridge's `(b)` parts
  ask about the *relationship between* two series ("explain the
  relationship you would expect between the annual change in the balance
  of trade and the annual change in real GDP growth"). A single-column
  table gives that part nothing to work with.
- **The exchange rate is quoted GBP per US dollar**, which is how the
  World Bank publishes it, so a *rise* in that figure is a *depreciation*
  of sterling. That is recorded in the manifest `notes` and goes into the
  prompt, but it is exactly the kind of thing worth checking on the first
  generated question — and a good thing for a student to have to think
  about.

## Fix in the tidy script

`--round` used to take one value for every column. On your real data that
destroyed the exchange rate: 0.655 and 0.811 both became 0.7 sitting next
to a percentage. It now accepts a value per file:

    --round 3,1

One value still applies to all columns; `-1` leaves a column exactly as
downloaded. Four new tests cover it.

## Next: bank the questions (this spends tokens)

Start with one, and look at it before doing the rest:

    python scripts/bank_data_response.py --dataset uk-inflation-cpih-cpi --topic 4.6 --shape june_2024 --count 1

`--dry-run` first prints the exact prompt and spends nothing.

Use `--shape june_2024` when the table has something worth calculating a
percentage change on (inflation, the current account) and
`--shape specimen_2023` otherwise. Then:

    python scripts/bank_data_response.py --dataset uk-growth-unemployment --topic 4.4 --shape specimen_2023 --count 1
    python scripts/bank_data_response.py --dataset uk-current-account-trade --topic 6.3 --shape june_2024 --count 1
    python scripts/bank_data_response.py --dataset uk-exchange-rate-current-account --topic 6.4 --shape specimen_2023 --count 1

Four banked data responses is enough for Mock Test to stop skipping
Section A; it draws one compulsory question per mock and excludes ones
already answered, so bank a few more once you have seen the quality.

## What I could not check

The economics. Generation needs your key and I did not spend your quota
on it. When the first one is banked, paste the extract and the six parts
back to me and I will check them against the specimen and June 2024
schemes — particularly whether every figure in the prose really appears
in the table, which is the one guard the whole design leans on.
