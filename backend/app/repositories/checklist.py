from __future__ import annotations

import sqlite3
from typing import Any


def next_run_no(
    conn: sqlite3.Connection,
    pack_id: int,
    pack_no: str,
) -> str:
    """每跑一次清单生成一个新运行号：CR-<包号>-<该包第几次运行>。"""
    seq = count_runs(conn, pack_id=pack_id) + 1
    return f"CR-{pack_no}-{seq:03d}"


def create_run(
    conn: sqlite3.Connection,
    *,
    run_no: str,
    pack_id: int,
    pack_no: str,
    rule_version_id: int,
    rule_version_code: str,
    rule_promotion_seq: int,
    check_count: int,
    passed_count: int,
    failed_count: int,
    all_passed: bool,
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO checklist_runs(
            run_no, pack_id, pack_no, rule_version_id, rule_version_code,
            rule_promotion_seq, check_count, passed_count, failed_count, all_passed, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_no,
            pack_id,
            pack_no,
            rule_version_id,
            rule_version_code,
            rule_promotion_seq,
            check_count,
            passed_count,
            failed_count,
            1 if all_passed else 0,
            created_at,
        ),
    )
    return int(cur.lastrowid)


def create_run_with_retry(
    conn: sqlite3.Connection,
    *,
    pack_id: int,
    pack_no: str,
    rule_version_id: int,
    rule_version_code: str,
    rule_promotion_seq: int,
    check_count: int,
    passed_count: int,
    failed_count: int,
    all_passed: bool,
    created_at: str,
) -> tuple[int, str]:
    """分配运行号并插入；并发下若运行号撞车则重试，保证每次运行号唯一。"""
    last_error: Exception | None = None
    for _ in range(20):
        run_no = next_run_no(conn, pack_id, pack_no)
        try:
            run_id = create_run(
                conn,
                run_no=run_no,
                pack_id=pack_id,
                pack_no=pack_no,
                rule_version_id=rule_version_id,
                rule_version_code=rule_version_code,
                rule_promotion_seq=rule_promotion_seq,
                check_count=check_count,
                passed_count=passed_count,
                failed_count=failed_count,
                all_passed=all_passed,
                created_at=created_at,
            )
            return run_id, run_no
        except sqlite3.IntegrityError as exc:  # run_no UNIQUE
            last_error = exc
            continue
    raise RuntimeError(f"无法分配唯一运行号: {last_error}")


def insert_result(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    pack_id: int,
    check_code: str,
    check_title: str,
    passed: bool,
    detail: str,
    created_at: str,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO checklist_results(
            run_id, pack_id, check_code, check_title, passed, detail, created_at
        ) VALUES (?,?,?,?,?,?,?)
        """,
        (run_id, pack_id, check_code, check_title, 1 if passed else 0, detail, created_at),
    )
    return int(cur.lastrowid)


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, run_no, pack_id, pack_no, rule_version_id, rule_version_code,
               rule_promotion_seq, check_count, passed_count, failed_count, all_passed, created_at
        FROM checklist_runs WHERE id=?
        """,
        (run_id,),
    ).fetchone()
    return dict(row) if row else None


def get_run_by_no(conn: sqlite3.Connection, run_no: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, run_no, pack_id, pack_no, rule_version_id, rule_version_code,
               rule_promotion_seq, check_count, passed_count, failed_count, all_passed, created_at
        FROM checklist_runs WHERE run_no=?
        """,
        (run_no,),
    ).fetchone()
    return dict(row) if row else None


def latest_run(conn: sqlite3.Connection, pack_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, run_no, pack_id, pack_no, rule_version_id, rule_version_code,
               rule_promotion_seq, check_count, passed_count, failed_count, all_passed, created_at
        FROM checklist_runs
        WHERE pack_id=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (pack_id,),
    ).fetchone()
    return dict(row) if row else None


def list_runs(
    conn: sqlite3.Connection,
    pack_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if pack_id is not None:
        rows = conn.execute(
            """
            SELECT id, run_no, pack_id, pack_no, rule_version_id, rule_version_code,
                   rule_promotion_seq, check_count, passed_count, failed_count, all_passed, created_at
            FROM checklist_runs
            WHERE pack_id=?
            ORDER BY id DESC
            """,
            (pack_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, run_no, pack_id, pack_no, rule_version_id, rule_version_code,
                   rule_promotion_seq, check_count, passed_count, failed_count, all_passed, created_at
            FROM checklist_runs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_results(
    conn: sqlite3.Connection,
    pack_id: int | None = None,
    run_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    base = """
        SELECT r.id, r.run_id, r.pack_id, r.check_code, r.check_title,
               r.passed, r.detail, r.created_at,
               cr.run_no, cr.rule_version_code, cr.rule_promotion_seq, cr.all_passed,
               cr.passed_count, cr.failed_count
        FROM checklist_results r
        JOIN checklist_runs cr ON cr.id = r.run_id
    """
    params: list[Any] = []
    where: list[str] = []
    if run_id is not None:
        where.append("r.run_id=?")
        params.append(run_id)
    if pack_id is not None:
        where.append("r.pack_id=?")
        params.append(pack_id)
    sql = base
    if where:
        sql += " WHERE " + " AND ".join(where)
    if run_id is not None or pack_id is not None:
        sql += " ORDER BY r.run_id DESC, r.id"
    else:
        sql += " ORDER BY r.id DESC LIMIT ?"
        params.append(limit)
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def count_runs(conn: sqlite3.Connection, pack_id: int | None = None) -> int:
    if pack_id is None:
        return int(conn.execute("SELECT COUNT(*) c FROM checklist_runs").fetchone()["c"])
    return int(
        conn.execute(
            "SELECT COUNT(*) c FROM checklist_runs WHERE pack_id=?", (pack_id,)
        ).fetchone()["c"]
    )


def pack_status_from_latest(conn: sqlite3.Connection, pack_id: int) -> str | None:
    run = latest_run(conn, pack_id)
    if not run:
        return None
    return "checked_ok" if int(run["all_passed"]) == 1 else "checked_fail"
