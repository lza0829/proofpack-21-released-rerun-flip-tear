from __future__ import annotations

import sqlite3
from typing import Any


def list_subjects(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, code, title, domain, fixture, sample_rate_default, enabled, created_at
        FROM subjects
        ORDER BY id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_subject(conn: sqlite3.Connection, subject_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, code, title, domain, fixture, sample_rate_default, enabled, created_at
        FROM subjects WHERE id=?
        """,
        (subject_id,),
    ).fetchone()
    return dict(row) if row else None


def get_by_code(conn: sqlite3.Connection, code: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, code, title, domain, fixture, sample_rate_default, enabled, created_at
        FROM subjects WHERE code=?
        """,
        (code,),
    ).fetchone()
    return dict(row) if row else None
