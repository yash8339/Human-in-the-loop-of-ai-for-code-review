from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .decisions import HumanDecision

DEFAULT_DB_PATH = Path(__file__).with_name("human_review.sqlite3")


def initialize_database(db_path: str | Path = DEFAULT_DB_PATH) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
                upload_id INTEGER NOT NULL,
                issue_id TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('accept', 'reject', 'modify')),
                reviewer_note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (upload_id, issue_id)
            )
            """
        )


def save_decision(upload_id: int, decision: HumanDecision, db_path: str | Path = DEFAULT_DB_PATH) -> None:
    initialize_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO decisions (upload_id, issue_id, status, reviewer_note)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(upload_id, issue_id) DO UPDATE SET
                status = excluded.status,
                reviewer_note = excluded.reviewer_note,
                created_at = CURRENT_TIMESTAMP
            """,
            (upload_id, decision.issue_id, decision.status, decision.reviewer_note),
        )


def load_decisions(upload_id: int, db_path: str | Path = DEFAULT_DB_PATH) -> list[HumanDecision]:
    initialize_database(db_path)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT issue_id, status, reviewer_note FROM decisions WHERE upload_id = ? ORDER BY issue_id",
            (upload_id,),
        ).fetchall()
    return [HumanDecision(issue_id, status, reviewer_note) for issue_id, status, reviewer_note in rows]


def save_decisions_for_upload(upload_id: int, decisions: Iterable[HumanDecision], db_path: str | Path = DEFAULT_DB_PATH) -> None:
    for decision in decisions:
        save_decision(upload_id, decision, db_path)
