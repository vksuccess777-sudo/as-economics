"""Generate a Paper 2 Section A data response around a real dataset.

Section A is the one AS component this app had no support for, and it is the
only one that cannot be written out of the syllabus alone: it needs numbers.
That is what the Tier 2 open-data policy is actually for.

THE SHAPES ARE OBSERVED, NOT INVENTED. Both of these are read off mark
schemes in data/papers/ rather than recalled:

  2023 specimen 9708/02   1(a) 2, 1(b)(i) 2, 1(b)(ii) 2, 1(c) 2, 1(d) 6, 1(e) 6
  June 2024   9708/21     1(a)(i) 1, 1(a)(ii) 1, 1(b) 2, 1(c) 4, 1(d) 6, 1(e) 6

Different in the opening parts, identical where it counts: twenty marks in
total, low-mark data-handling first (including a calculation), and a tail of
two six-mark "Assess..." parts each split up to 4 for analysis and up to 2
for evaluation. A shape is chosen from that list; the generator never makes
one up, and `validate` fails if the returned parts do not match it exactly.

THE MODEL NEVER WRITES A NUMBER. The table is rendered by code from the CSV.
The extract is prose the model writes around it, and every figure appearing
in the extract or in a question part must already be in the table —
`unsupported_numbers` enforces that. An invented statistic in a stimulus is
the worst thing this whole project could produce: the student would reason
correctly from it and be wrong, and nothing on the page would look off.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..llm.provider import LLMProvider
from ..reference.dataset import Dataset, Table, normalise_number
from ..store.db import Store, new_id
from ..syllabus.models import SyllabusSpine, Topic

SECTION_MARKS = 20
BANDS = ("knowledge", "analysis", "evaluation")
BAND_TO_AO = {"knowledge": "AO1", "analysis": "AO2", "evaluation": "AO3"}

# Caps on the two six-mark parts, straight from the specimen mark scheme:
# "Up to 4 marks for explanation/analysis ... Up to 2 marks for evaluation."
ASSESS_CAPS = {"analysis": 4, "evaluation": 2}

EVALUATIVE_WORDS = {"assess", "discuss", "evaluate", "consider", "justify"}


@dataclass(frozen=True)
class PartSpec:
    label: str
    marks: int
    kind: str  # data_read | calculate | explain | assess
    caps: dict[str, int] | None = None

    @property
    def is_assess(self) -> bool:
        return self.kind == "assess"


@dataclass(frozen=True)
class Shape:
    name: str
    source: str
    parts: tuple[PartSpec, ...]

    def total(self) -> int:
        return sum(p.marks for p in self.parts)


SPECIMEN_2023 = Shape(
    name="specimen_2023",
    source="2023 specimen 9708/02 question 1",
    parts=(
        PartSpec("(a)", 2, "data_read"),
        PartSpec("(b)(i)", 2, "explain"),
        PartSpec("(b)(ii)", 2, "data_read"),
        PartSpec("(c)", 2, "explain"),
        PartSpec("(d)", 6, "assess", ASSESS_CAPS),
        PartSpec("(e)", 6, "assess", ASSESS_CAPS),
    ),
)

JUNE_2024 = Shape(
    name="june_2024",
    source="June 2024 9708/21 question 1",
    parts=(
        PartSpec("(a)(i)", 1, "data_read"),
        PartSpec("(a)(ii)", 1, "calculate"),
        PartSpec("(b)", 2, "explain"),
        PartSpec("(c)", 4, "explain"),
        PartSpec("(d)", 6, "assess", ASSESS_CAPS),
        PartSpec("(e)", 6, "assess", ASSESS_CAPS),
    ),
)

SHAPES = (SPECIMEN_2023, JUNE_2024)
SHAPES_BY_NAME = {s.name: s for s in SHAPES}

MIN_EXTRACT_WORDS = 90
MAX_EXTRACT_WORDS = 260

# Asking for "90-260 words" gets you 87. Models do not count words while
# writing, they estimate, and an estimate aimed at a boundary lands on both
# sides of it -- and a retry that only repeats the boundary misses again. So
# the prompt asks for a target comfortably inside the band while the validator
# keeps the band. The target also matches what a real Cambridge extract runs
# to, which the boundary numbers never did.
TARGET_EXTRACT_WORDS = 180


class DataResponseError(ValueError):
    """A generated data response was rejected, with a reason. Never repaired."""


SYSTEM_PROMPT = """You are an experienced Cambridge International AS Level \
Economics (9708) examiner writing the Section A data response for Paper 2.

Absolute rules:
- You are given a table of real published data. DO NOT invent, adjust, round \
or extrapolate any figure. Every number you write must already appear in that \
table. If you want to say something you have no figure for, say it without a \
number.
- The extract is background prose about the economy in the table. It must be \
consistent with the data and must not contradict it.
- Put exactly one short phrase of the extract in single quotation marks, and \
make one of the later question parts quote that same phrase back. This is how \
Cambridge links the stimulus to the questions.
- The early low-mark parts must be answerable FROM THE TABLE.
- The two six-mark parts ask for judgement and must be arguable both ways.
- For every part, list the indicative points a marker would credit, one mark \
each. Give at least as many points as the part has marks.
- British spelling, Cambridge terminology. Never mention the syllabus, topic \
numbers, units or assessment objectives. Never write model answers in prose.

Return ONLY a JSON object. No prose, no markdown fences."""

SCHEMA = """The object must have exactly these keys:
  "extract_title": string, a short headline for the stimulus
  "extract":       string, background prose of about {target_words} words \
(anything under {min_words} or over {max_words} is rejected outright, so \
aim for the target, not the limit). Write it as 3 short paragraphs of \
roughly 4-6 sentences each -- covering, in order, (1) the recent trend in \
the data, (2) one likely cause behind it, (3) one consequence or policy \
response. A response with only one paragraph is too short even if every \
sentence is long.
  "table_caption": string, e.g. "Table 1.1 ..." describing what the table shows
  "parts":         array, one object per part, in this exact order:
{part_lines}
       each part object is:
       {{"label": string (exactly as listed above),
         "prompt": string, the wording the candidate reads,
         "points": array of {{"text": string, "band": one of \
knowledge/analysis/evaluation}} }}"""


# What each kind of part must ASK, stated to the model in the same words the
# validator uses to reject. Gate 1 got a prompt instruction when it was added
# and gates 2 and 3 did not, so the model was rejected twice for a rule it had
# never been told. A gate without a matching instruction is a retry loop.
KIND_GUIDANCE = {
    "data_read": (
        "must ask for a TREND, a COMPARISON between two periods, or whether a "
        "relationship is evident in the data. Never ask for the value in a "
        "single year — that reads one cell and tests nothing"
    ),
    "calculate": (
        "must ask for a PERCENTAGE CHANGE between two periods of the table. "
        "Not a difference: subtracting two percentage rates gives percentage "
        "points, which is a different quantity"
    ),
    "explain": (
        "asks the candidate to give a reason or a meaning, building on the "
        "extract or the data"
    ),
    "assess": (
        "must open with a judgement command word (Assess, Consider, Discuss, "
        "Evaluate) and must be arguable both ways"
    ),
}


def assess_points_example(caps: dict[str, int]) -> str:
    """A worked points array for an assess part, band counts exactly right.

    The abstract instruction ("write AT LEAST 4 analysis points... not a 3/3
    split") already states the rule in words. It still isn't landing every
    time -- 2 of 5 items missed it in one batch, then 1 of 5 in the next,
    after the wording was tightened. Models follow a shown shape far more
    reliably than a counted rule, so this shows the shape directly: the
    exact number of items in each band, and the specific wrong split
    (one analysis point short, dumped into evaluation instead) that keeps
    recurring, named as wrong.
    """
    analysis, evaluation = caps["analysis"], caps["evaluation"]
    lines = [f'         {{"band": "analysis", "text": "..."}},' for _ in range(analysis)]
    lines += [f'         {{"band": "evaluation", "text": "..."}},' for _ in range(evaluation)]
    lines[-1] = lines[-1].rstrip(",")
    array = "\n".join(lines)
    wrong_analysis = analysis - 1
    wrong_evaluation = evaluation + 1
    return (
        "Worked example of a CORRECT points array for a 6-mark assess part "
        f"with these caps (analysis={analysis}, evaluation={evaluation}). "
        'Count the "band" values in your own output before you submit -- '
        "this exact count is what gets checked:\n"
        '  "points": [\n'
        f"{array}\n"
        "  ]\n"
        f'That array has exactly {analysis} items with "band": "analysis" '
        f'and exactly {evaluation} with "band": "evaluation" -- '
        f"{analysis + evaluation} points in total, matching the two caps "
        "separately, not just the total. A split of "
        f"{wrong_analysis} analysis / {wrong_evaluation} evaluation still "
        f"totals {analysis + evaluation} points and will still be REJECTED, "
        f"because it is {analysis - wrong_analysis} short on the analysis band."
    )


def schema_text(shape: Shape) -> str:
    lines = []
    example_caps: dict[str, int] | None = None
    for part in shape.parts:
        extra = ""
        if part.caps:
            if example_caps is None:
                example_caps = part.caps
            # "Up to N marks" is the marker's ceiling, not a target -- said to
            # the model that way, it reads as permission to write fewer.
            # 3 analysis + 3 evaluation totals the same 6 points as 4 + 2,
            # so a model balancing evenly clears the "full marks unreachable"
            # gate and still fails the per-band cap gate on the very next
            # line. State the floor the validator actually enforces.
            extra = (
                "  [write AT LEAST {analysis} separate analysis points and "
                "AT LEAST {evaluation} separate evaluation points -- not a "
                "3/3 or other even split. A marker can award up to that many "
                "marks in each band, and fewer points than that leaves marks "
                "no candidate could reach]".format(**part.caps)
            )
        lines.append(f"       {part.label}  {part.marks} mark(s), {part.kind}{extra}")
        guidance = KIND_GUIDANCE.get(part.kind)
        if guidance:
            lines.append(f"            -> {part.label} {guidance}.")
    text = SCHEMA.format(
        min_words=MIN_EXTRACT_WORDS,
        max_words=MAX_EXTRACT_WORDS,
        target_words=TARGET_EXTRACT_WORDS,
        part_lines="\n".join(lines),
    )
    if example_caps:
        text = f"{text}\n\n{assess_points_example(example_caps)}"
    return text


@dataclass
class Part:
    label: str
    marks: int
    kind: str
    prompt: str
    points: list[dict]
    caps: dict[str, int] | None = None

    @property
    def is_assess(self) -> bool:
        return self.kind == "assess"

    def points_in_band(self, band: str) -> int:
        return sum(1 for p in self.points if p.get("band") == band)

    def rubric(self, group_id: str, index: int, stimulus: dict | None) -> str:
        payload = {
            "group_id": group_id,
            "part": self.label,
            "part_index": index,
            "kind": self.kind,
            "points": self.points,
            "caps": self.caps,
            "provenance": "generated_indicative",
            "diagram": None,
        }
        if stimulus is not None:
            payload["stimulus"] = stimulus
        return json.dumps(payload, ensure_ascii=False)


@dataclass
class DataResponseItem:
    topic_code: str
    dataset_slug: str
    shape_name: str
    extract_title: str
    extract: str
    table_caption: str
    table: Table
    parts: list[Part]
    attribution: str
    outcome_code: str | None = None

    @property
    def shape(self) -> Shape:
        return SHAPES_BY_NAME[self.shape_name]

    def total_marks(self) -> int:
        return sum(p.marks for p in self.parts)

    def stimulus(self) -> dict:
        return {
            "title": self.extract_title,
            "extract": self.extract,
            "table_caption": self.table_caption,
            "table_headers": list(self.table.headers),
            "table_rows": [list(r) for r in self.table.rows],
            "attribution": self.attribution,
            "dataset": self.dataset_slug,
            "shape": self.shape_name,
        }


@dataclass
class DataResponseReport:
    requested: int = 0
    banked: int = 0
    attempts: int = 0
    rejected: list[tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        retried = f", attempts {self.attempts}" if self.attempts > self.requested else ""
        return (
            f"requested {self.requested}, banked {self.banked}, "
            f"rejected {len(self.rejected)}{retried}"
        )


# ---- number checking -------------------------------------------------

TABLE_REF = re.compile(r"\btable\s*\d+(\.\d+)?", re.IGNORECASE)
FIG_REF = re.compile(r"\bfig(?:ure)?\.?\s*\d+(\.\d+)?", re.IGNORECASE)
NUMBER_TOKEN = re.compile(r"-?\d[\d,]*(?:\.\d+)?%?")

# Small bare integers are counting words ("one supply-side reason", "two
# sectors"), not statistics. Anything with a decimal point, a thousands comma
# or a percent sign is a statistic and must come from the table, as is any
# integer big enough to be a year or a quantity.
SMALL_INT_LIMIT = 12


def unsupported_numbers(text: str, table: Table) -> list[str]:
    """Figures that appear in the text but not in the data.

    This is the guard the whole feature rests on. Models are fluent about
    statistics and will happily write "growth of 7.2%" next to a table that
    says 5.9.
    """
    cleaned = FIG_REF.sub(" ", TABLE_REF.sub(" ", text or ""))
    known = table.numbers()
    bad = []
    for token in NUMBER_TOKEN.findall(cleaned):
        is_statistic = "." in token or "," in token or token.endswith("%")
        value = normalise_number(token)
        if value is None:
            continue
        if not is_statistic and abs(float(value)) <= SMALL_INT_LIMIT:
            continue
        if value not in known:
            bad.append(token)
    return bad


def table_period_span(table: Table) -> str | None:
    """The exact range of periods actually IN the table, read off row labels.

    A dataset's title or notes can describe a longer span than the table the
    model is actually handed -- `--rows` slices to the most recent N rows, so
    a title like "...2015-2024" can sit above a table that starts at 2016.
    Telling the model to write about "the data" without saying what that
    covers invites it to reach for a year the title mentions and the table
    doesn't have, which `unsupported_numbers` then rejects. This is what
    turned into a one-error-at-a-time retry loop on uk-cpi-inflation/4.6:
    the title said 2015-2024, the table started at 2016, the model wrote
    "since 2015", and every retry saw the same title and reached for 2015
    again. Stating the true span explicitly removes the thing being reached
    for.
    """
    if not table.rows:
        return None
    first = str(table.rows[0][0]).strip()
    last = str(table.rows[-1][0]).strip()
    if not first:
        return None
    return first if first == last else f"{first}\u2013{last}"


def quoted_phrases(text: str) -> list[str]:
    return [
        m.strip()
        for m in re.findall(r"[‘'\"“]([^’'\"”]{6,80})[’'\"”]", text or "")
        if m.strip()
    ]


# ---- parsing and validation -------------------------------------------

SYLLABUS_LEAK = re.compile(
    r"\b(syllabus|assessment objective|AO[123]\b|topic \d+\.\d+|unit \d+)\b",
    re.IGNORECASE,
)


def parse_response(text: str) -> dict:
    """Parse the model's JSON reply.

    strict=False: the schema asks for the extract as short paragraphs, and
    models write paragraph breaks as literal newlines inside the JSON string
    rather than the escaped \\n strict JSON requires. That's not invented
    content and not a structural mistake -- it's a well-known gap between
    what models emit and what a strict JSON parser accepts, so it shouldn't
    cost a retry. Worse, the retry that DID cost surfaced a raw parser
    message ("Invalid control character at...") as the fed-back rejection
    reason, which tells the model nothing it can act on -- an unfixable
    rejection is the same failure mode as the loop this file was already
    rewritten once to stop.
    """
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.MULTILINE)
    try:
        payload = json.loads(cleaned, strict=False)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise DataResponseError("response contained no JSON object")
        try:
            payload = json.loads(match.group(0), strict=False)
        except json.JSONDecodeError as exc:
            raise DataResponseError(f"response was not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise DataResponseError("expected a JSON object")
    return payload


def to_item(
    raw: dict,
    *,
    topic_code: str,
    dataset: Dataset,
    table: Table,
    shape: Shape,
) -> DataResponseItem:
    raw_parts = raw.get("parts")
    if not isinstance(raw_parts, list):
        raise DataResponseError("parts must be a list")
    if len(raw_parts) != len(shape.parts):
        raise DataResponseError(
            f"expected {len(shape.parts)} parts for shape {shape.name}, got {len(raw_parts)}"
        )

    parts: list[Part] = []
    for spec, raw_part in zip(shape.parts, raw_parts):
        if not isinstance(raw_part, dict):
            raise DataResponseError("each part must be an object")
        label = str(raw_part.get("label", "")).strip()
        if label != spec.label:
            raise DataResponseError(
                f"part out of order: expected {spec.label!r}, got {label!r}"
            )
        points = raw_part.get("points") or []
        if not isinstance(points, list):
            raise DataResponseError(f"{spec.label}: points must be a list")
        clean_points = []
        for point in points:
            if not isinstance(point, dict):
                raise DataResponseError(f"{spec.label}: each point must be an object")
            band = str(point.get("band", "")).strip().lower()
            text = str(point.get("text", "")).strip()
            if band not in BANDS:
                raise DataResponseError(f"{spec.label}: unknown band {band!r}")
            if len(text) < 10:
                raise DataResponseError(f"{spec.label}: a mark point is too short to credit")
            clean_points.append({"text": text, "band": band})
        parts.append(
            Part(
                label=spec.label,
                marks=spec.marks,
                kind=spec.kind,
                prompt=str(raw_part.get("prompt", "")).strip(),
                points=clean_points,
                caps=dict(spec.caps) if spec.caps else None,
            )
        )

    return DataResponseItem(
        topic_code=topic_code,
        dataset_slug=dataset.slug,
        shape_name=shape.name,
        extract_title=str(raw.get("extract_title", "")).strip(),
        extract=str(raw.get("extract", "")).strip(),
        table_caption=str(raw.get("table_caption", "")).strip(),
        table=table,
        parts=parts,
        attribution=dataset.attribution(),
        outcome_code=(raw.get("outcome_code") or None),
    )


# A part may not be ABOUT a named measure the syllabus does not teach.
#
# The first real question generated for topic 4.6 put 8 of its 20 marks on
# CPIH -- the ONS index including owner occupiers' housing costs. It is a
# perfectly good statistic and it was sitting in the data, but 9708 names
# only "consumer price index (CPI)", so a candidate could answer those parts
# faultlessly and gain nothing.
#
# Three or more capitals is the signal, because a named measure that matters
# in economics has an acronym: CPIH, RPI, GNP, PPP, ILO. Two-letter forms are
# left alone -- UK, US and EU are countries, not measures. What counts as in
# scope is read off the parsed spine, never listed here, so a syllabus
# revision changes the answer with no code change.
ACRONYM = re.compile(r"\b[A-Z]{3,6}\b")

# Both real papers ask the same two things of the early parts, so these are
# observed like the shapes themselves, not invented:
#   June 2024 (a)(ii)  "Calculate the percentage change in Sri Lanka's balance
#                       of trade ... between January 2022 and January 2023."
#   Nov  2023 (a)      "calculate the percentage change in the average real
#                       global price of oil between 2014 and 2020."
# A subtraction of two figures is not what this part tests, and subtracting two
# percentage RATES gives percentage POINTS, a distinction a 1-mark prompt will
# not make.
CALCULATE_DEMAND = re.compile(r"percentage\s+change", re.IGNORECASE)

#   June 2024 (a)(i)   "Identify the overall trend in Sri Lanka's balance of
#                       trade ... between January 2022 and January 2023."
#   Specimen  (a)      "compare Vietnam's balance of trade ... between 2009 and
#                       2011 with that from 2015 to 2017."
#   Specimen  (b)(ii)  "Consider the extent to which this relationship is
#                       evident in the data in Table 1.1."
# The June 2024 examiner report records candidates losing the mark for
# describing every month instead of the trend, so the part is about reading a
# MOVEMENT, never about reporting one cell.
#
# This is stated as the failure rather than as an approved vocabulary, because
# the first version demanded a word like "trend" and rejected the specimen's
# own (b)(ii), which names no period at all. What actually goes wrong is a
# prompt pinned to a single row with nothing to compare it against.
COMPARATIVE = re.compile(
    r"\b(trend|compar\w+|pattern|relationship|evident|extent|between|"
    r"change[sd]?|rise|fall|fallen|risen|increase|decrease|over the period)\b",
    re.IGNORECASE,
)


def periods_named(prompt: str, table: Table) -> int:
    """How many of the table's own row labels the prompt names."""
    labels = {str(row[0]).strip() for row in table.rows if row}
    return sum(1 for label in labels if label and label in prompt)


def syllabus_acronyms(spine: "SyllabusSpine") -> set[str]:
    """Every 3+ letter acronym the AS syllabus itself names."""
    lines: list[str] = []
    for unit in spine.units:
        lines.append(unit.title)
        for topic in unit.topics:
            lines.append(topic.title)
            for outcome in topic.outcomes:
                lines.extend((outcome.text, *outcome.bullets))
    return set(ACRONYM.findall(" ".join(lines)))


def off_syllabus_acronyms(text: str, allowed: set[str]) -> list[str]:
    """Acronyms in `text` that the syllabus never names, in order, deduped."""
    seen: list[str] = []
    for found in ACRONYM.findall(text):
        if found not in allowed and found not in seen:
            seen.append(found)
    return seen


def validate(
    item: DataResponseItem,
    *,
    known_topic_codes: set[str] | None = None,
    allowed_acronyms: set[str] | None = None,
) -> None:
    """Check every gate and raise ONCE, listing every failure found.

    This used to raise on the first failed gate. That made every retry a
    single-issue patch: the model fixed the one thing it was told about,
    at a hotter temperature, with nothing stopping it from breaking a gate
    that was never mentioned because the run never got that far. With one
    bounded retry, that is a coin flip repeated forever — which is exactly
    the loop reported against uk-cpi-inflation/4.6. Collecting every issue
    before raising means the one retry this generator allows carries the
    whole rejection, and a single corrected attempt can actually pass.
    """
    issues: list[str] = []

    if known_topic_codes is not None and item.topic_code not in known_topic_codes:
        issues.append(f"topic {item.topic_code!r} is not in the spine")

    words = len(item.extract.split())
    if not (MIN_EXTRACT_WORDS <= words <= MAX_EXTRACT_WORDS):
        direction = (
            f"add about {TARGET_EXTRACT_WORDS - words} more words"
            if words < MIN_EXTRACT_WORDS
            else f"cut about {words - TARGET_EXTRACT_WORDS} words"
        )
        issues.append(
            f"extract is {words} words, which is outside "
            f"{MIN_EXTRACT_WORDS}-{MAX_EXTRACT_WORDS}. Keep everything else and "
            f"{direction} of background about the economy, aiming for "
            f"{TARGET_EXTRACT_WORDS}."
        )
    if item.total_marks() != SECTION_MARKS:
        issues.append(
            f"parts total {item.total_marks()} marks, Section A is {SECTION_MARKS}"
        )

    # Invented figures anywhere the student reads.
    checked = [("extract", item.extract)] + [
        (f"part {p.label}", p.prompt) for p in item.parts
    ]
    for where, text in checked:
        bad = unsupported_numbers(text, item.table)
        if bad:
            issues.append(
                f"{where} uses figures that are not in the data: {bad[:4]} — "
                "every number must come from the table"
            )

    # The Cambridge stimulus/question link: a quoted phrase reused in a part.
    phrases = quoted_phrases(item.extract)
    if not phrases:
        issues.append("extract quotes no phrase for a part to pick up")
    else:
        prompts = " ".join(p.prompt.lower() for p in item.parts)
        if not any(phrase.lower() in prompts for phrase in phrases):
            issues.append(
                "no part quotes the phrase the extract set up — the stimulus "
                "and the questions are not connected"
            )

    for part in item.parts:
        prompt_text = part.prompt.strip()
        if len(part.prompt) < 15:
            issues.append(f"{part.label}: prompt is too short to be a question")
        if SYLLABUS_LEAK.search(part.prompt):
            issues.append(f"{part.label}: prompt refers to the syllabus")
        if part.kind == "calculate" and not CALCULATE_DEMAND.search(part.prompt):
            issues.append(
                f"{part.label}: a calculate part asks for a percentage change in "
                "both real papers. A difference between two figures does not "
                "test the same skill, and a difference between two percentage "
                "rates is measured in percentage points."
            )
        if (
            part.kind == "data_read"
            and periods_named(part.prompt, item.table) <= 1
            and not COMPARATIVE.search(part.prompt)
        ):
            issues.append(
                f"{part.label}: names one period and asks for no comparison, so "
                "it reads a single cell. Both real papers ask for a trend, a "
                "comparison or a relationship here."
            )
        if allowed_acronyms is not None:
            stray = off_syllabus_acronyms(part.prompt, allowed_acronyms)
            if stray:
                issues.append(
                    f"{part.label}: asks about {', '.join(stray)}, which the AS "
                    "syllabus does not teach — a candidate could answer this "
                    "perfectly and gain nothing. Ask about what the syllabus "
                    "names instead."
                )
        if len(part.points) < part.marks:
            issues.append(
                f"{part.label}: {len(part.points)} mark points for {part.marks} marks — "
                "full marks would be unreachable"
            )
        if part.caps:
            for band, cap in part.caps.items():
                if part.points_in_band(band) < cap:
                    issues.append(
                        f"{part.label}: only {part.points_in_band(band)} {band} "
                        f"points but up to {cap} marks are available for {band}"
                    )
        if part.is_assess:
            # Guard, not just style: an empty prompt (already flagged above)
            # would otherwise crash split()[0] with an IndexError that the
            # generator's retry loop does not catch, losing the whole batch
            # instead of banking the rest and reporting one clean rejection.
            first = prompt_text.split()[0].lower().strip(",") if prompt_text else ""
            if first not in EVALUATIVE_WORDS:
                issues.append(
                    f"{part.label}: a six-mark part opening with {first!r} asks for "
                    "no judgement, so two of its marks are unreachable"
                )

    if not issues:
        return
    if len(issues) == 1:
        raise DataResponseError(issues[0])
    raise DataResponseError(
        f"{len(issues)} problems found, fix all of them:\n"
        + "\n".join(f"{n}. {msg}" for n, msg in enumerate(issues, 1))
    )


# ---- generation --------------------------------------------------------


def scope_instruction(allowed: set[str]) -> str:
    """What the prompt forbids, built from the set the validator allows.

    Both sides come from syllabus_acronyms(spine), which is what stops the
    prompt and the gate drifting apart. A prompt that forbids less than the
    gate rejects burns retries; one that forbids more quietly narrows the
    syllabus.
    """
    named = ", ".join(sorted(allowed))
    return (
        "- The data may contain measures this course does not teach. You may "
        "mention one in the extract if the table shows it, but NO QUESTION "
        "PART may be about one: a candidate would answer it perfectly and "
        "gain nothing. The only named measures on this course are: "
        f"{named}. Anything else — other indices, other national statistics — "
        "must not be the subject of a part."
    )


def build_prompt(
    topic: Topic,
    dataset: Dataset,
    table: Table,
    shape: Shape,
    *,
    rejection: str | None = None,
    allowed_acronyms: set[str] | None = None,
) -> str:
    outcomes = "\n".join(f"- {o.code}: {o.searchable_text()}" for o in topic.outcomes)
    context = " ".join(
        bit for bit in (dataset.region, dataset.units, dataset.notes) if bit
    )
    scope = ""
    if allowed_acronyms:
        scope = "\n" + scope_instruction(allowed_acronyms) + "\n"
    span = table_period_span(table)
    span_note = ""
    if span:
        span_note = (
            f"\nThe table above covers {span} ONLY. Its title or notes may "
            "describe a longer span than that -- if so, ignore the longer "
            "span. Every year or period you write, in the extract or in any "
            "part, must be a row actually shown above.\n"
        )
    retry = ""
    if rejection:
        retry = (
            "\nYour previous attempt was REJECTED. Fix EVERY issue listed "
            f"below and change nothing else:\n{rejection}\n"
        )
    return f"""Write one Paper 2 Section A data response.

Topic {topic.code}: {topic.title}

Learning outcomes to build on:
{outcomes}

The data you must use, and the only source of figures you may write:
{dataset.title}{(' — ' + context) if context else ''}

{table.as_text()}
{span_note}
Shape of the question ({shape.parts[0].label} first):
{schema_text(shape)}
{scope}{retry}"""


class DataResponseGenerator:
    def __init__(self, provider: LLMProvider, store: Store, spine: SyllabusSpine):
        self.provider = provider
        self.store = store
        self.spine = spine
        self._topic_codes = set(spine.topic_codes)
        self._acronyms = syllabus_acronyms(spine)

    def generate(
        self,
        topic_code: str,
        dataset: Dataset,
        *,
        shape: Shape = SPECIMEN_2023,
        columns: list[str] | None = None,
        max_rows: int = 9,
        count: int = 1,
    ) -> DataResponseReport:
        topic = self.spine.topic(topic_code)
        if topic is None:
            raise ValueError(f"topic {topic_code!r} is not in the spine")

        table = dataset.table(columns=columns, max_rows=max_rows)
        report = DataResponseReport(requested=count)

        for _ in range(count):
            item, reason = self._attempt(topic, dataset, table, shape, report)
            if item is None:
                report.rejected.append((topic.code, reason or "unknown"))
                continue
            self._bank(item)
            report.banked += 1
        return report

    def _attempt(self, topic, dataset, table, shape, report):
        """One generation with one bounded retry, the rejection fed back.

        Same posture as the notes generator: the retry runs hotter, because
        the same temperature reproduces the same rejected output.
        """
        rejection = None
        for attempt, temperature in enumerate((0.6, 0.85)):
            report.attempts += 1
            response = self.provider.generate(
                build_prompt(
                    topic, dataset, table, shape,
                    rejection=rejection,
                    allowed_acronyms=self._acronyms,
                ),
                system=SYSTEM_PROMPT,
                max_tokens=2600,
                temperature=temperature,
            )
            try:
                item = to_item(
                    parse_response(response.text),
                    topic_code=topic.code,
                    dataset=dataset,
                    table=table,
                    shape=shape,
                )
                validate(
                    item,
                    known_topic_codes=self._topic_codes,
                    allowed_acronyms=self._acronyms,
                )
                return item, None
            except (DataResponseError, ValueError, TypeError, AttributeError) as exc:
                rejection = str(exc)
        return None, rejection

    def _bank(self, item: DataResponseItem) -> str:
        group_id = new_id("dr")
        stimulus = item.stimulus()
        for index, part in enumerate(item.parts):
            self.store.add_question(
                paper_key="paper_2",
                section_key="A",
                topic_code=item.topic_code,
                outcome_code=item.outcome_code,
                command_word=part.prompt.split()[0].lower().strip(",") if part.prompt else None,
                max_marks=part.marks,
                origin="generated",
                syllabus_code=self.spine.syllabus_code,
                syllabus_version=self.spine.syllabus_version,
                body=json.dumps({"prompt": part.prompt}, ensure_ascii=False),
                # The stimulus is written once, onto the first part, rather
                # than copied onto all six.
                rubric=part.rubric(group_id, index, stimulus if index == 0 else None),
            )
        return group_id