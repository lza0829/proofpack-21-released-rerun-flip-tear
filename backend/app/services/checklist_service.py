from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.db import connect
from app.repositories import checklist as check_repo
from app.repositories import packs as pack_repo
from app.repositories import rules as rule_repo
from app.repositories import samples as sample_repo


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


REQUIRED_FIELDS = ("business_key", "amount", "qty", "event_ts", "revision", "title")


def _decorate_run(conn, run: dict[str, Any]) -> dict[str, Any]:
    """标注该运行之后是否已有规则版本晋升（若有，则该历史运行作废）。"""
    promoted = rule_repo.promotion_after(conn, int(run.get("rule_promotion_seq") or 0))
    run["voided"] = bool(promoted)
    run["voided_by"] = (
        {
            "code": promoted["code"],
            "promoted_at": promoted["promoted_at"],
            "promotion_seq": promoted["promotion_seq"],
        }
        if promoted
        else None
    )
    return run


def list_runs(pack_id: int | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return [_decorate_run(conn, r) for r in check_repo.list_runs(conn, pack_id=pack_id)]
    finally:
        conn.close()


def get_run(run_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        run = check_repo.get_run(conn, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="校验运行不存在")
        _decorate_run(conn, run)
        run["results"] = check_repo.list_results(conn, run_id=run_id)
        return run
    finally:
        conn.close()


def list_results(pack_id: int | None = None, run_id: int | None = None) -> list[dict[str, Any]]:
    conn = connect()
    try:
        return check_repo.list_results(conn, pack_id=pack_id, run_id=run_id)
    finally:
        conn.close()


def run_checklist(pack_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        pack = pack_repo.get_pack(conn, pack_id)
        if not pack:
            raise HTTPException(status_code=404, detail="证据包不存在")

        prior_status = pack["status"]
        # Re-runs are always allowed so operators can append a fresh audit trail
        # after release. Pack status is re-synced from the new run so the desk
        # shows the latest checklist conclusion rather than a stale terminal label.
        rule = rule_repo.get_active_rule_version(conn)
        if not rule:
            raise HTTPException(status_code=400, detail="当前无生效规则版本，无法执行校验清单")

        items = pack_repo.list_items(conn, pack_id)
        sample_rows = sample_repo.list_rows(conn, pack["batch_id"])
        now = _now()

        checks: list[dict[str, Any]] = []

        # 1. 条数一致
        count_ok = len(items) == len(sample_rows) and len(items) == pack["item_count"]
        checks.append(
            {
                "check_code": "count_match",
                "check_title": "条数一致",
                "passed": count_ok,
                "detail": f"包条目={len(items)}，样本行={len(sample_rows)}，包记录条数={pack['item_count']}",
            }
        )

        # 2. 键唯一
        keys = [it["business_key"] for it in items]
        unique_ok = len(keys) == len(set(keys))
        dup = sorted({k for k in keys if keys.count(k) > 1})
        checks.append(
            {
                "check_code": "key_unique",
                "check_title": "键唯一",
                "passed": unique_ok,
                "detail": "全部业务键唯一" if unique_ok else f"重复键: {', '.join(dup)}",
            }
        )

        # 3. 必填非空
        missing: list[str] = []
        for it in items:
            summary = it.get("summary") if isinstance(it.get("summary"), dict) else {}
            merged = {
                "business_key": it.get("business_key"),
                "title": summary.get("title"),
                "amount": summary.get("amount"),
                "qty": summary.get("qty"),
                "event_ts": summary.get("event_ts"),
                "revision": summary.get("revision"),
            }
            for field in REQUIRED_FIELDS:
                val = merged.get(field)
                if val is None or (isinstance(val, str) and val.strip() == ""):
                    missing.append(f"{it.get('business_key')}.{field}")
        required_ok = len(missing) == 0
        checks.append(
            {
                "check_code": "required_fields",
                "check_title": "必填非空",
                "passed": required_ok,
                "detail": "必填字段齐全" if required_ok else f"缺失: {', '.join(missing[:20])}",
            }
        )

        passed_count = sum(1 for c in checks if c["passed"])
        failed_count = len(checks) - passed_count
        all_ok = failed_count == 0

        run_id, run_no = check_repo.create_run_with_retry(
            conn,
            pack_id=pack_id,
            pack_no=pack["pack_no"],
            rule_version_id=rule["id"],
            rule_version_code=rule["code"],
            rule_promotion_seq=int(rule["promotion_seq"] or 0),
            check_count=len(checks),
            passed_count=passed_count,
            failed_count=failed_count,
            all_passed=all_ok,
            created_at=now,
        )
        for c in checks:
            check_repo.insert_result(
                conn,
                run_id=run_id,
                pack_id=pack_id,
                check_code=c["check_code"],
                check_title=c["check_title"],
                passed=c["passed"],
                detail=c["detail"],
                created_at=now,
            )

        next_status = "checked_ok" if all_ok else "checked_fail"
        # Always rewrite the pack row from the newest run, including packs that
        # were previously released or rejected — the run list is append-only and
        # the status column is treated as a mirror of the latest conclusion.
        pack_repo.update_status(conn, pack_id, next_status, respect_terminal=False)
        conn.commit()

        return {
            "run_id": run_id,
            "run_no": run_no,
            "pack_id": pack_id,
            "pack_no": pack["pack_no"],
            "rule_version_id": rule["id"],
            "rule_version_code": rule["code"],
            "item_count": len(items),
            "check_count": len(checks),
            "passed_count": passed_count,
            "failed_count": failed_count,
            "all_passed": all_ok,
            "created_at": now,
            "prior_status": prior_status,
            "pack_status": next_status,
            "results": check_repo.list_results(conn, run_id=run_id),
        }
    finally:
        conn.close()
