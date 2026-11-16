from __future__ import annotations

import json
import sqlite3
from typing import Any


def create_batch(
    conn: sqlite3.Connection,
    *,
    batch_no: str,
    subject_id: int,
    seed: str,
    rate: float,
    source_count: int,
    sample_count: int,
    status: str,
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO sample_batches(
            batch_no, subject_id, seed, rate, source_count, sample_count, status, created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (batch_no, subject_id, seed, rate, source_count, sample_count, status, created_at),
    )
    return int(cur.lastrowid)


def insert_rows(
    conn: sqlite3.Connection,
    batch_id: int,
    rows: list[dict[str, Any]],
) -> None:
    for r in rows:
        conn.execute(
            """
            INSERT INTO sample_rows(batch_id, business_key, payload_json, event_ts, revision)
            VALUES (?,?,?,?,?)
            """,
            (
                batch_id,
                str(r.get("business_key", "")),
                json.dumps(r, ensure_ascii=False),
                r.get("event_ts"),
                r.get("revision"),
            ),
        )


def list_batches(conn: sqlite3.Connection, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, batch_no, subject_id, seed, rate, source_count, sample_count, status, created_at
        FROM sample_batches
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, batch_no, subject_id, seed, rate, source_count, sample_count, status, created_at
        FROM sample_batches WHERE id=?
        """,
        (batch_id,),
    ).fetchone()
    return dict(row) if row else None


def list_rows(conn: sqlite3.Connection, batch_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, batch_id, business_key, payload_json, event_ts, revision
        FROM sample_rows WHERE batch_id=? ORDER BY business_key
        """,
        (batch_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d.pop("payload_json"))
        except json.JSONDecodeError:
            d["payload"] = d.pop("payload_json")
        out.append(d)
    return out
