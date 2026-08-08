# Fix: the gate rejected a rule the model was never told

Your run did exactly what it should have — and then failed, twice:

    rejected 4.6: (a)(i): names one period and asks for no comparison...

The gate was right. The prompt was the problem. When I added the three
gates I wrote a prompt instruction for the off-syllabus one and forgot the
other two, so the model was being marked against a rule it had never seen.
One bounded retry could not recover from that, because the retry feeds back
the rejection but the underlying instruction was still missing.

Unzip over your repo root, **restart Streamlit**, and re-run:

    python scripts\bank_data_response.py --dataset uk-inflation-cpih-cpi --topic 4.6 --shape june_2024 --count 1
    python scripts\show_data_response.py

Two files:

    src/questions/data_response.py
    tests/test_data_response_scope.py

Suite 520 -> 523 passing, 9 skipped.

## What changed

Every part kind now carries its requirement into the prompt, in the same
words the validator uses to reject:

    (a)(i)  1 mark(s), data_read
         -> (a)(i) must ask for a TREND, a COMPARISON between two periods,
            or whether a relationship is evident in the data. Never ask for
            the value in a single year.
    (a)(ii) 1 mark(s), calculate
         -> (a)(ii) must ask for a PERCENTAGE CHANGE between two periods of
            the table. Not a difference: subtracting two percentage rates
            gives percentage points, which is a different quantity.

Three new tests hold this together. One fails if any part kind used by
either shape has no instruction — so a future gate cannot ship without one.
The others assert the instruction names what the gate actually demands.

`python scripts\bank_data_response.py ... --dry-run` prints the whole
prompt if you want to read it. That costs nothing.

## If it still fails

Send me the rejection line. Two rejections in a row would mean the model is
struggling with the shape rather than with the instruction, and the answer
then is a better table — the two near-identical inflation series are a
genuinely awkward thing to write a question about.
