from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from app.db import connect

# 举证对象种子
SUBJECT_SEEDS = [
    {
        "code": "store_dayend",
        "title": "门店日结抽检",
        "domain": "store",
        "fixture": "store_dayend.json",
        "sample_rate_default": 0.3,
        "enabled": 1,
    },
    {
        "code": "channel_settle",
        "title": "渠道结算抽检",
        "domain": "channel",
        "fixture": "channel_settle.json",
        "sample_rate_default": 0.3,
        "enabled": 1,
    },
    {
        "code": "price_change",
        "title": "价目变更核证",
        "domain": "price",
        "fixture": "price_change.json",
        "sample_rate_default": 0.3,
        "enabled": 1,
    },
]

DEFAULT_RULE_VERSION_CODE = "RULES-V1"
DEFAULT_RULE_VERSION_TITLE = "基础校验规则 v1"
DEFAULT_RULE_VERSION_PAYLOAD = {
    "label": "基础校验",
    "checks": ["count_match", "key_unique", "required_fields"],
    "description": "条数一致、键唯一、必填非空",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, decl: str) -> None:
    """Idempotently add a column to an existing (older) database."""
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def _migrate(conn: sqlite3.Connection) -> None:
    """旧库升级：旧 model 只有包级覆盖式清单结果，必须补齐运行号字段。"""
    _ensure_column(conn, "rule_versions", "promotion_seq", "INTEGER")
    _ensure_column(conn, "rule_versions", "promoted_at", "TEXT")
    _ensure_column(conn, "checklist_results", "run_id", "INTEGER")
    _ensure_column(conn, "checklist_runs", "rule_promotion_seq", "INTEGER")
    _ensure_column(conn, "release_decisions", "run_id", "INTEGER")
    _ensure_column(conn, "release_decisions", "run_no", "TEXT")
    _ensure_column(conn, "release_decisions", "rule_version_id", "INTEGER")
    _ensure_column(conn, "release_decisions", "rule_version_code", "TEXT")
    _ensure_column(conn, "release_decisions", "policy", "TEXT")

    conn.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_checklist_runs_pack
            ON checklist_runs(pack_id, id);
        CREATE INDEX IF NOT EXISTS idx_checklist_results_run
            ON checklist_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_checklist_results_pack
            ON checklist_results(pack_id, id);
        CREATE INDEX IF NOT EXISTS idx_release_decisions_pack
            ON release_decisions(pack_id, id);
        """
    )


def _seed_rule_version(conn: sqlite3.Connection, now: str) -> None:
    count = conn.execute("SELECT COUNT(*) c FROM rule_versions").fetchone()["c"]
    if count == 0:
        conn.execute(
            """
            INSERT INTO rule_versions(
                code, title, payload_json, active, promotion_seq, promoted_at, created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                DEFAULT_RULE_VERSION_CODE,
                DEFAULT_RULE_VERSION_TITLE,
                json.dumps(DEFAULT_RULE_VERSION_PAYLOAD, ensure_ascii=False),
                1,
                1,
                now,
                now,
            ),
        )
        return

    # 旧库里没有晋升序号：按 id 顺序补一个单调序号。
    rows = conn.execute(
        "SELECT id FROM rule_versions WHERE promotion_seq IS NULL ORDER BY id"
    ).fetchall()
    if rows:
        base = conn.execute(
            "SELECT COALESCE(MAX(promotion_seq), 0) m FROM rule_versions"
        ).fetchone()["m"]
        for offset, row in enumerate(rows, start=1):
            conn.execute(
                "UPDATE rule_versions SET promotion_seq=?, promoted_at=COALESCE(promoted_at, ?) WHERE id=?",
                (int(base) + offset, now, row["id"]),
            )

    active = conn.execute(
        "SELECT id FROM rule_versions WHERE active=1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if active is None:
        # 保证始终有一个生效规则版本，否则清单无法落运行记录。
        latest = conn.execute(
            "SELECT id FROM rule_versions ORDER BY promotion_seq DESC, id DESC LIMIT 1"
        ).fetchone()
        conn.execute("UPDATE rule_versions SET active=0 WHERE id<>?", (latest["id"],))
        conn.execute("UPDATE rule_versions SET active=1 WHERE id=?", (latest["id"],))


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(
            """
            -- 举证对象
            CREATE TABLE IF NOT EXISTS subjects(
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                domain TEXT NOT NULL,
                fixture TEXT NOT NULL,
                sample_rate_default REAL NOT NULL DEFAULT 0.3,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            -- 采样批次
            CREATE TABLE IF NOT EXISTS sample_batches(
                id INTEGER PRIMARY KEY,
                batch_no TEXT NOT NULL UNIQUE,
                subject_id INTEGER NOT NULL,
                seed TEXT NOT NULL,
                rate REAL NOT NULL,
                source_count INTEGER NOT NULL,
                sample_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(subject_id) REFERENCES subjects(id)
            );
            -- 样本行
            CREATE TABLE IF NOT EXISTS sample_rows(
                id INTEGER PRIMARY KEY,
                batch_id INTEGER NOT NULL,
                business_key TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                event_ts TEXT,
                revision INTEGER,
                FOREIGN KEY(batch_id) REFERENCES sample_batches(id)
            );
            -- 证据包
            CREATE TABLE IF NOT EXISTS evidence_packs(
                id INTEGER PRIMARY KEY,
                pack_no TEXT NOT NULL UNIQUE,
                batch_id INTEGER NOT NULL,
                subject_id INTEGER NOT NULL,
                item_count INTEGER NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(batch_id) REFERENCES sample_batches(id),
                FOREIGN KEY(subject_id) REFERENCES subjects(id)
            );
            -- 证据包条目
            CREATE TABLE IF NOT EXISTS pack_items(
                id INTEGER PRIMARY KEY,
                pack_id INTEGER NOT NULL,
                business_key TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                item_fingerprint TEXT NOT NULL,
                FOREIGN KEY(pack_id) REFERENCES evidence_packs(id)
            );
            -- 规则版本：晋升序号单调递增，用于判定历史运行是否作废
            CREATE TABLE IF NOT EXISTS rule_versions(
                id INTEGER PRIMARY KEY,
                code TEXT NOT NULL,
                title TEXT,
                payload_json TEXT,
                active INTEGER NOT NULL DEFAULT 0,
                promotion_seq INTEGER,
                promoted_at TEXT,
                created_at TEXT NOT NULL
            );
            -- 校验清单运行记录：每次跑清单一条独立记录，永不覆盖
            CREATE TABLE IF NOT EXISTS checklist_runs(
                id INTEGER PRIMARY KEY,
                run_no TEXT NOT NULL UNIQUE,
                pack_id INTEGER NOT NULL,
                pack_no TEXT NOT NULL,
                rule_version_id INTEGER NOT NULL,
                rule_version_code TEXT NOT NULL,
                rule_promotion_seq INTEGER NOT NULL DEFAULT 0,
                check_count INTEGER NOT NULL,
                passed_count INTEGER NOT NULL,
                failed_count INTEGER NOT NULL,
                all_passed INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(pack_id) REFERENCES evidence_packs(id),
                FOREIGN KEY(rule_version_id) REFERENCES rule_versions(id)
            );
            -- 校验清单结果：run_id 指向具体一次运行，历史结果不再被清除
            CREATE TABLE IF NOT EXISTS checklist_results(
                id INTEGER PRIMARY KEY,
                run_id INTEGER,
                pack_id INTEGER NOT NULL,
                check_code TEXT NOT NULL,
                check_title TEXT NOT NULL,
                passed INTEGER NOT NULL,
                detail TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES checklist_runs(id),
                FOREIGN KEY(pack_id) REFERENCES evidence_packs(id)
            );
            -- 放行决策：放行必须绑定 run_id/run_no，驳回留原因
            CREATE TABLE IF NOT EXISTS release_decisions(
                id INTEGER PRIMARY KEY,
                pack_id INTEGER NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT,
                run_id INTEGER,
                run_no TEXT,
                rule_version_id INTEGER,
                rule_version_code TEXT,
                policy TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(pack_id) REFERENCES evidence_packs(id),
                FOREIGN KEY(run_id) REFERENCES checklist_runs(id)
            );
            -- 设置
            CREATE TABLE IF NOT EXISTS settings(
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            -- 影子试跑（空挂，后题用）
            CREATE TABLE IF NOT EXISTS shadow_runs(
                id INTEGER PRIMARY KEY,
                pack_id INTEGER,
                rule_version_id INTEGER,
                status TEXT,
                note TEXT,
                created_at TEXT
            );
            """
        )
        _migrate(conn)

        if conn.execute("SELECT COUNT(*) c FROM subjects").fetchone()["c"] == 0:
            now = _now()
            for s in SUBJECT_SEEDS:
                conn.execute(
                    """
                    INSERT INTO subjects(
                        code, title, domain, fixture, sample_rate_default, enabled, created_at
                    ) VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        s["code"],
                        s["title"],
                        s["domain"],
                        s["fixture"],
                        s["sample_rate_default"],
                        s["enabled"],
                        now,
                    ),
                )

        now = _now()
        _seed_rule_version(conn, now)

        for key, value in (
            ("default_sample_rate", "0.3"),
            ("require_checklist_pass", "1"),
            ("sample_mode", "seeded"),
            ("release_run_policy", "latest_only"),
        ):
            conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                (key, value),
            )
        # 「放行须清单全过」在新模型下是不变量：放行必须绑定一次全过的运行，
        # 该开关不再可关闭，恒为 1。
        conn.execute(
            "UPDATE settings SET value='1' WHERE key='require_checklist_pass'"
        )
        conn.commit()
    finally:
        conn.close()
