"""Thin SQLite layer for the attempt log.

Deliberately not an ORM. The schema is small, the queries are few, and
keeping raw SQL visible makes the mark-computation path easy to audit.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Store:
    # Every table the app queries. Checking only one was not enough: a
    # partially-applied schema passed is_initialised() and then crashed on the
    # first query against a missing table.
    REQUIRED_TABLES = ("question", "attempt", "response", "calibration_case")

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
                for table in ("question", "attempt", "response", "calibration_case")
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
