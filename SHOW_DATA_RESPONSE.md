# See the question you just banked

Unzip over your repo root, then:

    python scripts\show_data_response.py

It prints the extract, the table, and all six parts of the most recent
banked data response. No model call, no tokens.

    python scripts\show_data_response.py --list     all banked ones
    python scripts\show_data_response.py --marks    include the mark points

Leave `--marks` off if you plan to attempt the question yourself — it
prints the generated mark scheme.

## Why this needed a script

There is no screen that shows a data response outside a running mock, so
until now the only way to see what was generated was to sit the mock and
spend the marking tokens on it.

Two new files, nothing else changed:

    scripts/show_data_response.py
    tests/test_show_data_response.py

Suite 499 -> 506 passing, 9 skipped.

## What to look at

**Every figure in the prose should appear in the table.** That is the
guard the whole design leans on — the table is rendered from your CSV and
the model is only allowed to write around it, with any unsupported number
rejecting the item. It reported 0 rejections, so the guard did not fire;
reading the extract confirms it was right not to.

Also worth checking, in rough order of how likely they are to be wrong:

- **(a)(ii) is the calculate part.** Work the percentage change out
  yourself and see whether the answer is actually obtainable from the
  table.
- **CPIH vs CPI.** They are different measures (CPIH includes owner
  occupiers' housing costs) and a question that treats them as
  interchangeable is teaching something false.
- **(d) and (e) must be worth 6 each and open with a judgement command
  word** — Cambridge uses "Assess" or "Consider the extent to which".
- **Nothing above AS level.** The multiplier and detailed AD components
  are marked not required in your syllabus.

Paste the output back and I will check it against your 2023 specimen and
June 2024 mark schemes.
