from __future__ import annotations

import json
import sqlite3
from typing import Any


def create_pack(
    conn: sqlite3.Connection,
    *,
    pack_no: str,
    batch_id: int,
    subject_id: int,
    item_count: int,
    fingerprint: str,
    status: str,
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO evidence_packs(
            pack_no, batch_id, subject_id, item_count, fingerprint, status, created_at
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (pack_no, batch_id, subject_id, item_count, fingerprint, status, created_at),
    )
    return int(cur.lastrowid)


def insert_items(
    conn: sqlite3.Connection,
    pack_id: int,
    items: list[dict[str, Any]],
) -> None:
    for it in items:
        conn.execute(
            """
            INSERT INTO pack_items(pack_id, business_key, summary_json, item_fingerprint)
            VALUES (?,?,?,?)
            """,
            (
                pack_id,
                str(it["business_key"]),
                json.dumps(it["summary"], ensure_ascii=False),
                it["item_fingerprint"],
            ),
        )


def list_packs(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, pack_no, batch_id, subject_id, item_count, fingerprint, status, created_at
        FROM evidence_packs
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_pack(conn: sqlite3.Connection, pack_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, pack_no, batch_id, subject_id, item_count, fingerprint, status, created_at
        FROM evidence_packs WHERE id=?
        """,
        (pack_id,),
    ).fetchone()
    return dict(row) if row else None


def list_items(conn: sqlite3.Connection, pack_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, pack_id, business_key, summary_json, item_fingerprint
        FROM pack_items WHERE pack_id=? ORDER BY business_key
        """,
        (pack_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["summary"] = json.loads(d.pop("summary_json"))
        except json.JSONDecodeError:
            d["summary"] = d.pop("summary_json")
        out.append(d)
    return out


TERMINAL_STATUSES = ("released", "rejected")


def update_status(
    conn: sqlite3.Connection,
    pack_id: int,
    status: str,
    *,
    respect_terminal: bool = False,
) -> None:
    """Update pack status.

    Checklist re-runs prefer to rewrite the pack row so the desk always mirrors
    the latest run outcome. ``respect_terminal`` can keep released/rejected rows
    frozen, but callers that sync from a fresh run leave it off so the status
    column stays aligned with the newest checklist conclusion.
    """
    if respect_terminal:
        conn.execute(
            """
            UPDATE evidence_packs
            SET status=?
            WHERE id=? AND status NOT IN ('released', 'rejected')
            """,
            (status, pack_id),
        )
        return
    conn.execute("UPDATE evidence_packs SET status=? WHERE id=?", (status, pack_id))
