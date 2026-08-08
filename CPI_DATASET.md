# New dataset: uk-cpi-inflation

The gate is right and the table is wrong. `uk-inflation-cpih-cpi` puts
CPIH in the first data column, so it is the most obvious thing in the
stimulus to ask about — and it is the one thing the course does not name.
The generator kept reaching for it because it was there.

Unzip over your repo root. No code changes, so no Streamlit restart.

    data/reference/datasets/uk-cpi-inflation/{data.csv,manifest.json}

Then delete the old one, so it cannot be picked again:

    rmdir /s /q data\reference\datasets\uk-inflation-cpih-cpi

and bank:

    python scripts\bank_data_response.py --dataset uk-cpi-inflation --topic 4.6 --shape june_2024 --count 1
    python scripts\show_data_response.py

## What it is

ONS series D7G7, the CPI annual rate, 2015-2024. One data column. Your
syllabus names exactly this measure at 4.6.2 and nothing else, so there is
no off-syllabus term anywhere in the table for a part to latch onto.

Use `--shape june_2024` with it. The specimen shape has a "relationship
between two series" part that a single-column table cannot support.

A single-column table is not a compromise: the June 2024 Sri Lanka question
worked from one series of monthly trade-balance figures, and carried the
economics in the extract rather than in extra columns.

## If you want a richer inflation table later

Download one more file and the whole table becomes World Bank, so it can be
registered against a single source honestly:

  https://data.worldbank.org/indicator/FP.CPI.TOTL.ZG?locations=GB

Pair it with the unemployment zip you already have:

    python scripts\tidy_reference_csv.py --country "United Kingdom" ^
        --from 2015 --to 2024 --out uk-inflation-unemployment.csv ^
        --labels "Inflation (annual %),Unemployment (% of labour force)" ^
        "%USERPROFILE%\Downloads\API_FP.CPI.TOTL.ZG_DS2_en_csv_v2_XXXX.zip" ^
        "%USERPROFILE%\Downloads\API_SL.UEM.TOTL.ZS_DS2_en_csv_v2_33398.zip"

That gives a table where the two columns have a real economic relationship,
which is what the specimen's (b)(i) and (b)(ii) parts are built on. Not
required — the CPI-only table works now.
