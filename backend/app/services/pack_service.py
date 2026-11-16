from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.db import connect
from app.engines.checksum import item_fingerprint, pack_fingerprint
from app.repositories import checklist as check_repo
from app.repositories import packs as pack_repo
from app.repositories import samples as sample_repo
from app.repositories import subjects as subject_repo


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _attach_latest_run(conn, row: dict[str, Any]) -> dict[str, Any]:
    """包状态须与其最近一次运行互证。"""
    run = check_repo.latest_run(conn, row["id"])
    row["latest_run_id"] = run["id"] if run else None
    row["latest_run_no"] = run["run_no"] if run else None
    row["latest_run_all_passed"] = bool(run and int(run["all_passed"]) == 1) if run else None
    row["latest_run_rule_version_code"] = run["rule_version_code"] if run else None
    row["latest_run_at"] = run["created_at"] if run else None
    return row


def list_packs(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = pack_repo.list_packs(conn, limit=limit)
        subjects = {s["id"]: s for s in subject_repo.list_subjects(conn)}
        for r in rows:
            s = subjects.get(r["subject_id"])
            r["subject_code"] = s["code"] if s else None
            r["subject_title"] = s["title"] if s else None
            _attach_latest_run(conn, r)
        return rows
    finally:
        conn.close()


def get_pack(pack_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        p = pack_repo.get_pack(conn, pack_id)
        if not p:
            raise HTTPException(status_code=404, detail="证据包不存在")
        s = subject_repo.get_subject(conn, p["subject_id"])
        p["subject_code"] = s["code"] if s else None
        p["subject_title"] = s["title"] if s else None
        p["items"] = pack_repo.list_items(conn, pack_id)
        _attach_latest_run(conn, p)
        return p
    finally:
        conn.close()


def build_pack(batch_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        batch = sample_repo.get_batch(conn, batch_id)
        if not batch:
            raise HTTPException(status_code=404, detail="采样批次不存在")
        rows = sample_repo.list_rows(conn, batch_id)
        if not rows:
            raise HTTPException(status_code=400, detail="采样批次无样本行")

        items_src = []
        for r in rows:
            payload = r.get("payload") if isinstance(r.get("payload"), dict) else {}
            items_src.append(
                {
                    "business_key": r["business_key"],
                    "title": payload.get("title"),
                    "amount": payload.get("amount"),
                    "qty": payload.get("qty"),
                    "event_ts": payload.get("event_ts") or r.get("event_ts"),
                    "revision": payload.get("revision") if payload.get("revision") is not None else r.get("revision"),
                }
            )

        fp = pack_fingerprint(items_src)
        now = _now()
        seq = conn.execute("SELECT COUNT(*) c FROM evidence_packs").fetchone()["c"] + 1
        pack_no = f"EP-{now[:10].replace('-', '')}-{seq:04d}"

        pack_items = []
        for it in items_src:
            summary = {
                "title": it.get("title"),
                "amount": it.get("amount"),
                "qty": it.get("qty"),
                "event_ts": it.get("event_ts"),
                "revision": it.get("revision"),
            }
            pack_items.append(
                {
                    "business_key": it["business_key"],
                    "summary": summary,
                    "item_fingerprint": item_fingerprint(it),
                }
            )

        pack_id = pack_repo.create_pack(
            conn,
            pack_no=pack_no,
            batch_id=batch_id,
            subject_id=batch["subject_id"],
            item_count=len(pack_items),
            fingerprint=fp,
            status="built",
            created_at=now,
        )
        pack_repo.insert_items(conn, pack_id, pack_items)
        conn.commit()

        subject = subject_repo.get_subject(conn, batch["subject_id"])
        return {
            "id": pack_id,
            "pack_no": pack_no,
            "batch_id": batch_id,
            "subject_id": batch["subject_id"],
            "subject_code": subject["code"] if subject else None,
            "subject_title": subject["title"] if subject else None,
            "item_count": len(pack_items),
            "fingerprint": fp,
            "status": "built",
            "created_at": now,
            "latest_run_id": None,
            "latest_run_no": None,
            "latest_run_all_passed": None,
            "latest_run_rule_version_code": None,
            "latest_run_at": None,
            "items": pack_repo.list_items(conn, pack_id),
        }
    finally:
        conn.close()
