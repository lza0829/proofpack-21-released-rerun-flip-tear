from __future__ import annotations

import sqlite3
from typing import Any


def list_rule_versions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, code, title, payload_json, active, promotion_seq, promoted_at, created_at
        FROM rule_versions
        ORDER BY id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_rule_version(conn: sqlite3.Connection, rule_version_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, code, title, payload_json, active, promotion_seq, promoted_at, created_at
        FROM rule_versions WHERE id=?
        """,
        (rule_version_id,),
    ).fetchone()
    return dict(row) if row else None


def get_active_rule_version(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, code, title, payload_json, active, promotion_seq, promoted_at, created_at
        FROM rule_versions
        WHERE active=1
        ORDER BY id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def next_promotion_seq(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(promotion_seq), 0) m FROM rule_versions"
    ).fetchone()
    return int(row["m"]) + 1


def create_rule_version(
    conn: sqlite3.Connection,
    *,
    code: str,
    title: str,
    payload_json: str,
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO rule_versions(
            code, title, payload_json, active, promotion_seq, promoted_at, created_at
        ) VALUES (?,?,?,0,NULL,NULL,?)
        """,
        (code, title, payload_json, created_at),
    )
    return int(cur.lastrowid)


def promote_rule_version(conn: sqlite3.Connection, rule_version_id: int, promoted_at: str) -> int:
    """晋升一个规则版本：它成为唯一生效版本，并获得新的晋升序号。"""
    seq = next_promotion_seq(conn)
    conn.execute("UPDATE rule_versions SET active=0 WHERE id<>?", (rule_version_id,))
    conn.execute(
        "UPDATE rule_versions SET active=1, promotion_seq=?, promoted_at=? WHERE id=?",
        (seq, promoted_at, rule_version_id),
    )
    return seq


def promotion_after(conn: sqlite3.Connection, promotion_seq: int | None) -> dict[str, Any] | None:
    """返回在给定运行之后发生的晋升（若有，说明该历史运行已作废）。"""
    row = conn.execute(
        """
        SELECT id, code, title, promotion_seq, promoted_at
        FROM rule_versions
        WHERE promotion_seq IS NOT NULL AND promotion_seq > ?
        ORDER BY promotion_seq
        LIMIT 1
        """,
        (int(promotion_seq or 0),),
    ).fetchone()
    return dict(row) if row else None
