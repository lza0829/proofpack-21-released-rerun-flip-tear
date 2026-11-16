from __future__ import annotations

import sqlite3
from typing import Any


def create_decision(
    conn: sqlite3.Connection,
    *,
    pack_id: int,
    decision: str,
    reason: str | None,
    created_at: str,
    run_id: int | None = None,
    run_no: str | None = None,
    rule_version_id: int | None = None,
    rule_version_code: str | None = None,
    policy: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO release_decisions(
            pack_id, decision, reason, run_id, run_no, rule_version_id,
            rule_version_code, policy, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        """,
        (
            pack_id,
            decision,
            reason,
            run_id,
            run_no,
            rule_version_id,
            rule_version_code,
            policy,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def list_decisions(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, pack_id, decision, reason, run_id, run_no, rule_version_id,
               rule_version_code, policy, created_at
        FROM release_decisions
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def latest_for_pack(conn: sqlite3.Connection, pack_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, pack_id, decision, reason, run_id, run_no, rule_version_id,
               rule_version_code, policy, created_at
        FROM release_decisions
        WHERE pack_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (pack_id,),
    ).fetchone()
    return dict(row) if row else None
