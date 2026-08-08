"""Thin SQLite layer for the attempt log.

Deliberately not an ORM. The schema is small, the queries are few, and
keeping raw SQL visible makes the mark-computation path easy to audit.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta as _timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Store:
    # Every table the app queries. Checking only one was not enough: a
    # partially-applied schema passed is_initialised() and then crashed on the
    # first query against a missing table.
    # `note` arrived with the knowledge base. Listing it here is what makes an
    # existing database upgrade itself: is_initialised() returns False, the app
    # runs schema.sql again, and every statement in it is CREATE ... IF NOT
    # EXISTS, so the new table appears and nothing already there is touched.
    # `worksheet_topic_log` arrived with topic-coverage tracking, on the same
    # upgrade-in-place principle as `note`: listing it here makes an existing
    # database self-heal, since schema.sql only ever CREATEs IF NOT EXISTS.
    REQUIRED_TABLES = ("question", "attempt", "response", "calibration_case",
                       "note", "worksheet_topic_log", "observed_mistake",
                       "practice_seen")

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialise(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self.connect() as conn:
            conn.executescript(sql)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) "
                "VALUES (?, ?)",
                (SCHEMA_VERSION, _now()),
            )

    def is_initialised(self) -> bool:
        """True only when every required table exists."""
        if not self.db_path.exists():
            return False
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        present = {r["name"] for r in rows}
        return all(t in present for t in self.REQUIRED_TABLES)

    # ---- writes -----------------------------------------------------

    def add_question(
        self,
        *,
        paper_key: str,
        topic_code: str,
        max_marks: int,
        body: str,
        origin: str,
        syllabus_code: str,
        syllabus_version: str,
        subject: str = "economics",
        section_key: str | None = None,
        outcome_code: str | None = None,
        command_word: str | None = None,
        answer_key: str | None = None,
        rubric: str | None = None,
    ) -> str:
        qid = new_id("q")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO question (
                    id, subject, syllabus_code, syllabus_version, paper_key,
                    section_key, topic_code, outcome_code, command_word,
                    max_marks, origin, body, answer_key, rubric, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    qid, subject, syllabus_code, syllabus_version, paper_key,
                    section_key, topic_code, outcome_code, command_word,
                    max_marks, origin, body, answer_key, rubric, _now(),
                ),
            )
        return qid

    def start_attempt(
        self,
        *,
        mode: str,
        subject: str = "economics",
        paper_key: str | None = None,
        time_limit_secs: int | None = None,
    ) -> str:
        aid = new_id("a")
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO attempt (id, subject, mode, paper_key, started_at, "
                "time_limit_secs) VALUES (?,?,?,?,?,?)",
                (aid, subject, mode, paper_key, _now(), time_limit_secs),
            )
        return aid

    def finish_attempt(self, attempt_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE attempt SET finished_at = ? WHERE id = ?",
                (_now(), attempt_id),
            )

    def record_response(
        self,
        *,
        attempt_id: str,
        question_id: str,
        ordinal: int,
        max_marks: int,
        answer_text: str | None = None,
        awarded: float | None = None,
        ao_levels: dict[str, int] | None = None,
        marker_version: str | None = None,
        feedback: str | None = None,
        seconds_taken: int | None = None,
    ) -> None:
        levels = ao_levels or {}
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO response (
                    attempt_id, question_id, ordinal, answer_text, awarded,
                    max_marks, ao1_level, ao2_level, ao3_level, marker_version,
                    feedback, seconds_taken, marked_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    attempt_id, question_id, ordinal, answer_text, awarded,
                    max_marks, levels.get("AO1"), levels.get("AO2"),
                    levels.get("AO3"), marker_version, feedback, seconds_taken,
                    _now() if awarded is not None else None,
                ),
            )

    # ---- reset --------------------------------------------------------

    def reset_progress(self, subject: str = "economics") -> dict[str, int]:
        """Wipe a student's attempt history so they can start with a clean slate.

        Deletes every `attempt` row for the subject; `response` rows cascade
        with it (ON DELETE CASCADE — foreign keys are on for every connection).
        Deliberately does NOT touch `question` (the banked question pool cost
        real tokens to generate), `note` (the knowledge base), or
        `calibration_case` (the marker's regression set) — none of those are
        the student's own history, they are shared/reusable content.
        """
        with self.connect() as conn:
            attempts = conn.execute(
                "SELECT COUNT(*) FROM attempt WHERE subject = ?", (subject,)
            ).fetchone()[0]
            responses = conn.execute(
                "SELECT COUNT(*) FROM response r "
                "JOIN attempt a ON a.id = r.attempt_id WHERE a.subject = ?",
                (subject,),
            ).fetchone()[0]
            conn.execute("DELETE FROM attempt WHERE subject = ?", (subject,))
        return {"attempts_deleted": attempts, "responses_deleted": responses}

    # ---- reads ------------------------------------------------------

    def topic_performance(self, subject: str = "economics") -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM topic_performance WHERE subject = ? ORDER BY pct ASC",
                (subject,),
            ).fetchall()
        return [dict(r) for r in rows]

    def weakest_topics(
        self, limit: int = 5, min_answered: int = 3, subject: str = "economics"
    ) -> list[dict[str, Any]]:
        """Topics ranked worst-first, ignoring thin evidence.

        `min_answered` exists so a single unlucky wrong answer does not get
        reported as a weakness.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM topic_performance WHERE subject = ? "
                "AND answered >= ? ORDER BY pct ASC LIMIT ?",
                (subject, min_answered, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def untested_topics(
        self, all_topic_codes: list[str], subject: str = "economics"
    ) -> list[str]:
        """Syllabus topics with no marked answers yet — coverage gaps."""
        seen = {row["topic_code"] for row in self.topic_performance(subject)}
        return [code for code in all_topic_codes if code not in seen]

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("question", "attempt", "response",
                              "calibration_case", "note")
            }

    # ---- question bank ----------------------------------------------

    def bank_counts_by_topic(
        self, paper_key: str = "paper_1", subject: str = "economics"
    ) -> dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT topic_code, COUNT(*) AS n FROM question "
                "WHERE subject = ? AND paper_key = ? GROUP BY topic_code",
                (subject, paper_key),
            ).fetchall()
        return {r["topic_code"]: r["n"] for r in rows}

    def fetch_questions(self, question_ids: list[str]) -> list[dict[str, Any]]:
        if not question_ids:
            return []
        placeholders = ",".join("?" * len(question_ids))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM question WHERE id IN ({placeholders})", question_ids
            ).fetchall()
        by_id = {r["id"]: dict(r) for r in rows}
        return [by_id[qid] for qid in question_ids if qid in by_id]

    def candidate_questions(
        self,
        *,
        paper_key: str = "paper_1",
        subject: str = "economics",
        topic_codes: list[str] | None = None,
        exclude_answered: bool = True,
    ) -> list[dict[str, Any]]:
        """Questions available to put in a paper.

        `exclude_answered` keeps a test from re-serving something already sat,
        so a score reflects understanding rather than recall of a past attempt.
        """
        sql = [
            "SELECT q.* FROM question q WHERE q.subject = ? AND q.paper_key = ?"
        ]
        params: list[Any] = [subject, paper_key]

        if topic_codes:
            sql.append(f"AND q.topic_code IN ({','.join('?' * len(topic_codes))})")
            params.extend(topic_codes)

        if exclude_answered:
            sql.append(
                "AND q.id NOT IN (SELECT question_id FROM response "
                "WHERE awarded IS NOT NULL)"
            )

        sql.append("ORDER BY q.created_at")
        with self.connect() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
        return [dict(r) for r in rows]

    # ---- essays ------------------------------------------------------
    #
    # A Section B/C essay is two question rows sharing a `group_id` inside
    # rubric JSON. There is no group column: adding one would migrate the
    # schema for a relationship only the essay path cares about, and SQLite's
    # json_extract reads it perfectly well.

    def essay_groups(
        self,
        *,
        subject: str = "economics",
        topic_codes: list[str] | None = None,
        section_key: str | None = None,
        exclude_answered: bool = True,
    ) -> list[dict[str, Any]]:
        """One row per essay: group id, topic, section, and both part ids."""
        sql = [
            "SELECT json_extract(q.rubric, '$.group_id') AS group_id,",
            "       q.topic_code, q.section_key,",
            "       MIN(q.created_at) AS created_at, COUNT(*) AS parts",
            "FROM question q",
            "WHERE q.subject = ? AND q.paper_key = 'paper_2'",
            "AND json_extract(q.rubric, '$.group_id') IS NOT NULL",
        ]
        params: list[Any] = [subject]

        if topic_codes:
            sql.append(f"AND q.topic_code IN ({','.join('?' * len(topic_codes))})")
            params.extend(topic_codes)
        if section_key:
            sql.append("AND q.section_key = ?")
            params.append(section_key)
        if exclude_answered:
            sql.append(
                "AND q.id NOT IN (SELECT question_id FROM response "
                "WHERE awarded IS NOT NULL)"
            )

        sql.append("GROUP BY group_id, q.topic_code, q.section_key")
        sql.append("ORDER BY created_at")
        with self.connect() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
        # A group whose parts are split across answered/unanswered is not a
        # whole essay any more; only offer complete ones.
        return [dict(r) for r in rows if r["parts"] == 2]

    def essay_parts(self, group_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM question WHERE json_extract(rubric, '$.group_id') = ? "
                "ORDER BY json_extract(rubric, '$.part')",
                (group_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- examiner-observed mistakes ----------------------------------

    def add_observed_mistake(
        self,
        *,
        source: str,
        paper: str,
        kind: str,
        text: str,
        fingerprint: str,
        ref: str | None = None,
        topic_code: str | None = None,
        confidence: float = 0.0,
        subject: str = "economics",
    ) -> bool:
        """Returns False if this line is already stored.

        Re-running the ingest is a normal thing to do — a rejected line gets
        fixed and the script runs again — so duplicates are ignored rather
        than raising.
        """
        with self.connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO observed_mistake (
                    id, subject, source, paper, ref, kind, topic_code, text,
                    confidence, fingerprint, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_id("om"), subject, source, paper, ref, kind, topic_code,
                    text, confidence, fingerprint, _now(),
                ),
            )
            return cursor.rowcount > 0

    def observed_mistakes(
        self,
        topic_code: str | None = None,
        *,
        kind: str | None = None,
        subject: str = "economics",
    ) -> list[dict[str, Any]]:
        sql = ["SELECT * FROM observed_mistake WHERE subject = ?"]
        params: list[Any] = [subject]
        if topic_code is not None:
            sql.append("AND topic_code = ?")
            params.append(topic_code)
        if kind:
            sql.append("AND kind = ?")
            params.append(kind)
        sql.append("ORDER BY confidence DESC, created_at")
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(" ".join(sql), params).fetchall()]

    def observed_mistake_topics(self, subject: str = "economics") -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT topic_code FROM observed_mistake "
                "WHERE subject = ? AND topic_code IS NOT NULL ORDER BY topic_code",
                (subject,),
            ).fetchall()
        return [r["topic_code"] for r in rows]

    # ---- Paper 2 Section A -------------------------------------------

    def data_response_groups(
        self,
        *,
        subject: str = "economics",
        topic_codes: list[str] | None = None,
        exclude_answered: bool = True,
    ) -> list[dict[str, Any]]:
        """One row per banked data response.

        Section A groups have six parts where a Section B/C essay has two, so
        `essay_groups` (which returns only two-part groups) already ignores
        these and nothing needed changing there.
        """
        sql = [
            "SELECT json_extract(q.rubric, '$.group_id') AS group_id,",
            "       q.topic_code, MIN(q.created_at) AS created_at,",
            "       COUNT(*) AS parts, SUM(q.max_marks) AS marks",
            "FROM question q",
            "WHERE q.subject = ? AND q.paper_key = 'paper_2'",
            "AND q.section_key = 'A'",
            "AND json_extract(q.rubric, '$.group_id') IS NOT NULL",
        ]
        params: list[Any] = [subject]
        if topic_codes:
            sql.append(f"AND q.topic_code IN ({','.join('?' * len(topic_codes))})")
            params.extend(topic_codes)
        if exclude_answered:
            sql.append(
                "AND q.id NOT IN (SELECT question_id FROM response "
                "WHERE awarded IS NOT NULL)"
            )
        sql.append("GROUP BY group_id, q.topic_code")
        sql.append("ORDER BY created_at DESC")
        with self.connect() as conn:
            rows = conn.execute(" ".join(sql), params).fetchall()
        # A part-answered group is not a whole question any more; only offer
        # complete ones, same rule as essays.
        return [dict(r) for r in rows if r["marks"] == 20]

    def data_response_parts(self, group_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM question "
                "WHERE json_extract(rubric, '$.group_id') = ? "
                "ORDER BY CAST(json_extract(rubric, '$.part_index') AS INTEGER)",
                (group_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def data_response_stimulus(self, group_id: str) -> dict[str, Any] | None:
        """The extract and table, written onto the first part only."""
        with self.connect() as conn:
            row = conn.execute(
                "SELECT json_extract(rubric, '$.stimulus') AS stimulus "
                "FROM question WHERE json_extract(rubric, '$.group_id') = ? "
                "AND json_extract(rubric, '$.stimulus') IS NOT NULL LIMIT 1",
                (group_id,),
            ).fetchone()
        if not row or not row["stimulus"]:
            return None
        return json.loads(row["stimulus"])

    # ---- dashboard ---------------------------------------------------

    def ao_performance(self, subject: str = "economics") -> list[dict[str, Any]]:
        """Average level per assessment objective, essays only.

        MCQ responses carry no AO levels, so they are excluded by the NOT NULL
        checks rather than dragging the averages toward nothing.
        """
        out = []
        with self.connect() as conn:
            for ao, column in (("AO1", "ao1_level"), ("AO2", "ao2_level"),
                               ("AO3", "ao3_level")):
                row = conn.execute(
                    f"SELECT COUNT({column}) AS n, AVG({column}) AS avg_level "
                    "FROM response r JOIN question q ON q.id = r.question_id "
                    f"WHERE q.subject = ? AND {column} IS NOT NULL",
                    (subject,),
                ).fetchone()
                out.append(
                    {
                        "ao": ao,
                        "answered": row["n"],
                        "avg_level": round(row["avg_level"], 2) if row["n"] else None,
                    }
                )
        return out

    def command_word_performance(
        self, subject: str = "economics", min_answered: int = 1
    ) -> list[dict[str, Any]]:
        """Performance sliced by command word.

        Misreading the command word is one of the most common ways marks are
        lost, and it is invisible in a topic-only view: a student can know
        monetary policy and still score badly on every 'discuss'.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT q.command_word AS command_word, COUNT(r.id) AS answered, "
                "SUM(r.awarded) AS marks_awarded, SUM(r.max_marks) AS marks_available, "
                "ROUND(100.0 * SUM(r.awarded) / NULLIF(SUM(r.max_marks), 0), 1) AS pct "
                "FROM response r JOIN question q ON q.id = r.question_id "
                "WHERE q.subject = ? AND r.awarded IS NOT NULL "
                "AND q.command_word IS NOT NULL "
                "GROUP BY q.command_word HAVING answered >= ? ORDER BY pct ASC",
                (subject, min_answered),
            ).fetchall()
        return [dict(r) for r in rows]

    def attempt_history(
        self, subject: str = "economics", limit: int = 20
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT a.id, a.mode, a.paper_key, a.started_at, a.finished_at, "
                "COUNT(r.id) AS answered, SUM(r.awarded) AS marks_awarded, "
                "SUM(r.max_marks) AS marks_available, "
                "ROUND(100.0 * SUM(r.awarded) / NULLIF(SUM(r.max_marks), 0), 1) AS pct "
                "FROM attempt a LEFT JOIN response r ON r.attempt_id = a.id "
                "WHERE a.subject = ? GROUP BY a.id "
                "ORDER BY a.started_at DESC LIMIT ?",
                (subject, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- notes (knowledge base) --------------------------------------

    def upsert_note(
        self,
        *,
        topic_code: str,
        body: str,
        syllabus_code: str,
        syllabus_version: str,
        model: str | None = None,
        subject: str = "economics",
    ) -> str:
        """Write or replace the note for one topic.

        Replace rather than accumulate: a topic has one current set of notes.
        Keeping every draft would leave the page choosing between versions with
        no basis for the choice.
        """
        nid = new_id("n")
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO note (id, subject, syllabus_code, syllabus_version,
                                  topic_code, body, model, created_at)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT (subject, topic_code, syllabus_version)
                DO UPDATE SET body = excluded.body,
                              model = excluded.model,
                              created_at = excluded.created_at
                """,
                (nid, subject, syllabus_code, syllabus_version, topic_code,
                 body, model, _now()),
            )
        return nid

    def note(
        self, topic_code: str, *, subject: str = "economics",
        syllabus_version: str | None = None,
    ) -> dict[str, Any] | None:
        sql = "SELECT * FROM note WHERE subject = ? AND topic_code = ?"
        params: list[Any] = [subject, topic_code]
        if syllabus_version:
            sql += " AND syllabus_version = ?"
            params.append(syllabus_version)
        with self.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def note_topics(self, subject: str = "economics") -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT topic_code FROM note WHERE subject = ? ORDER BY topic_code",
                (subject,),
            ).fetchall()
        return [r["topic_code"] for r in rows]

    # ---- worksheet topic coverage -------------------------------------
    #
    # What the school is teaching right now, kept as a count per topic per
    # day — never the worksheet text itself. See schema.sql for why.

    def record_worksheet_topics(
        self,
        topic_counts: dict[str, int],
        *,
        subject: str = "economics",
        on: str | None = None,
    ) -> None:
        """Log one row per topic a worksheet touched. No text, no answers.

        Called once per uploaded worksheet (the caller is responsible for not
        calling this again on a Streamlit rerun of the same sheet). Rows
        accumulate rather than upsert — a fortnight with six sheets on 3.2
        should read as six rows, not one row silently overwritten five times,
        so `worksheet_topic_frequency` can tell "taught once" from "drilled
        all week" apart.
        """
        day = on or datetime.now(timezone.utc).date().isoformat()
        rows = [
            (new_id("wt"), subject, code, day, int(count), _now())
            for code, count in topic_counts.items()
            if code and count > 0
        ]
        if not rows:
            return
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO worksheet_topic_log "
                "(id, subject, topic_code, logged_on, item_count, created_at) "
                "VALUES (?,?,?,?,?,?)",
                rows,
            )

    def worksheet_topic_frequency(
        self, *, subject: str = "economics", days: int = 30
    ) -> dict[str, int]:
        """Item count per topic from worksheets logged in the last `days` days.

        A plain recency window, not a decay curve — the AI Coach only needs to
        know "this is live right now", and a window a student can reason about
        beats a smoothing constant nobody can see the effect of.
        """
        since = (datetime.now(timezone.utc).date() - _timedelta(days=days)).isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT topic_code, SUM(item_count) AS n FROM worksheet_topic_log "
                "WHERE subject = ? AND logged_on >= ? GROUP BY topic_code",
                (subject, since),
            ).fetchall()
        return {r["topic_code"]: r["n"] for r in rows}

    # ---- coached practice, which is not an attempt --------------------

    def mark_group_seen(
        self, group_id: str, *, surface: str = "concept_tutor",
        subject: str = "economics",
    ) -> None:
        """Record that a banked question has been walked through with the tutor.

        Deliberately not a `response` row. There is no mark here and there
        never will be: the student was coached through the question, so what
        they produced says nothing about what they can do in an exam hall, and
        writing it to the attempt log would tell the AI Coach the opposite.

        Idempotent — re-opening the same walkthrough is one row, not many.
        """
        if not group_id:
            return
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO practice_seen "
                "(id, subject, surface, group_id, seen_at) VALUES (?,?,?,?,?)",
                (new_id("ps"), subject, surface, group_id, _now()),
            )

    def seen_group_ids(
        self, *, surface: str | None = None, subject: str = "economics"
    ) -> set[str]:
        """Group ids already coached. Read by the Mock Test screen."""
        sql = "SELECT group_id FROM practice_seen WHERE subject = ?"
        params: list[Any] = [subject]
        if surface:
            sql += " AND surface = ?"
            params.append(surface)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return {r["group_id"] for r in rows}

    # ---- misconception evidence --------------------------------------

    def wrong_mcq_selections(
        self, subject: str = "economics", limit: int = 200
    ) -> list[dict[str, Any]]:
        """Every MCQ the student got wrong, with the option they chose.

        The rationale for the option they picked was written when the question
        was banked and names the specific misconception a student holds to
        choose it. That makes this the most direct evidence in the whole
        database about what is actually misunderstood — better than a topic
        percentage, which only says where marks were lost, not why.
        """
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT r.answer_text AS selected, q.topic_code, q.body, "
                "q.answer_key, r.marked_at "
                "FROM response r JOIN question q ON q.id = r.question_id "
                "WHERE q.subject = ? AND q.paper_key = 'paper_1' "
                "AND r.awarded = 0 AND r.answer_text IS NOT NULL "
                "ORDER BY r.marked_at DESC LIMIT ?",
                (subject, limit),
            ).fetchall()

        out = []
        for r in rows:
            try:
                body = json.loads(r["body"])
            except (TypeError, ValueError):
                continue
            rationale = (body.get("rationales") or {}).get(r["selected"], "")
            if not rationale:
                continue
            out.append(
                {
                    "topic_code": r["topic_code"],
                    "selected": r["selected"],
                    "misconception": rationale,
                    "marked_at": r["marked_at"],
                }
            )
        return out

    def skipped_count(self, subject: str = "economics") -> int:
        """Questions left blank. A time-management signal, not a knowledge one."""
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM response r JOIN question q "
                "ON q.id = r.question_id WHERE q.subject = ? "
                "AND r.answer_text IS NULL AND r.awarded IS NOT NULL",
                (subject,),
            ).fetchone()[0]

    def diagram_failures(self, subject: str = "economics") -> int:
        """Essay parts where a required diagram was missing or wrong."""
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM response r JOIN question q "
                "ON q.id = r.question_id WHERE q.subject = ? "
                "AND r.feedback IS NOT NULL "
                "AND json_extract(r.feedback, '$.cap_note') IS NOT NULL",
                (subject,),
            ).fetchone()[0]
