-- Attempt log. This is the foundation of the weakness dashboard: every mark
-- awarded anywhere in the system lands in `response` tagged to a syllabus
-- outcome code, so progress can be sliced by topic without any extra plumbing.
--
-- `subject` is present from day one so a second subject is a new row value,
-- not a schema migration. The abstraction is deliberately NOT built yet.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);

-- A generated (or ingested) question. Cambridge question text is never
-- stored here; `origin` records where a question came from so generated
-- items can never be presented as authentic past-paper questions.
CREATE TABLE IF NOT EXISTS question (
    id              TEXT PRIMARY KEY,
    subject         TEXT NOT NULL DEFAULT 'economics',
    syllabus_code   TEXT NOT NULL,
    syllabus_version TEXT NOT NULL,
    paper_key       TEXT NOT NULL,          -- paper_1 | paper_2
    section_key     TEXT,                   -- NULL for MCQ, else A | B | C
    topic_code      TEXT NOT NULL,          -- e.g. '4.3'
    outcome_code    TEXT,                   -- e.g. '4.3.8', when known
    command_word    TEXT,
    max_marks       INTEGER NOT NULL,
    origin          TEXT NOT NULL
        CHECK (origin IN ('generated', 'user_supplied', 'specimen_derived')),
    body            TEXT NOT NULL,          -- question stem (JSON for MCQ)
    answer_key      TEXT,                   -- MCQ: correct option; else NULL
    rubric          TEXT,                   -- JSON: AO-tagged rubric skeleton
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_question_topic ON question (subject, topic_code);

-- One sitting: a timed mock, a single practice question, whatever.
CREATE TABLE IF NOT EXISTS attempt (
    id              TEXT PRIMARY KEY,
    subject         TEXT NOT NULL DEFAULT 'economics',
    mode            TEXT NOT NULL
        CHECK (mode IN ('mcq_test', 'single_question', 'full_paper', 'practice')),
    paper_key       TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    time_limit_secs INTEGER,
    notes           TEXT
);

-- One answer within an attempt. `awarded` is always computed by code:
-- MCQ by key comparison, essays by level -> marks lookup. A model never
-- writes this column directly.
CREATE TABLE IF NOT EXISTS response (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id      TEXT NOT NULL REFERENCES attempt (id) ON DELETE CASCADE,
    question_id     TEXT NOT NULL REFERENCES question (id),
    ordinal         INTEGER NOT NULL,
    answer_text     TEXT,
    awarded         REAL,
    max_marks       INTEGER NOT NULL,
    ao1_level       INTEGER,
    ao2_level       INTEGER,
    ao3_level       INTEGER,
    marker_version  TEXT,                   -- which marker/prompt produced this
    feedback        TEXT,                   -- JSON: per-AO feedback
    seconds_taken   INTEGER,
    marked_at       TEXT,
    UNIQUE (attempt_id, ordinal)
);

CREATE INDEX IF NOT EXISTS idx_response_attempt ON response (attempt_id);

-- Calibration set: real marked scripts with a known teacher/examiner mark.
-- These are the regression cases the marker is measured against.
CREATE TABLE IF NOT EXISTS calibration_case (
    id              TEXT PRIMARY KEY,
    subject         TEXT NOT NULL DEFAULT 'economics',
    topic_code      TEXT NOT NULL,
    command_word    TEXT,
    max_marks       INTEGER NOT NULL,
    known_mark      REAL NOT NULL,
    source          TEXT NOT NULL,          -- e.g. 'school_marked_script'
    answer_text     TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

-- Per-topic performance. The whole weakness dashboard reads from here.
CREATE VIEW IF NOT EXISTS topic_performance AS
SELECT
    q.subject                                   AS subject,
    q.topic_code                                AS topic_code,
    COUNT(r.id)                                 AS answered,
    SUM(r.awarded)                              AS marks_awarded,
    SUM(r.max_marks)                            AS marks_available,
    ROUND(100.0 * SUM(r.awarded) / NULLIF(SUM(r.max_marks), 0), 1) AS pct,
    MAX(r.marked_at)                            AS last_answered
FROM response r
JOIN question q ON q.id = r.question_id
WHERE r.awarded IS NOT NULL
GROUP BY q.subject, q.topic_code;
