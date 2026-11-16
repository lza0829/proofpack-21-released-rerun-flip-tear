from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.db import connect
from app.repositories import rules as rule_repo

router = APIRouter(tags=["rules"])


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _decorate(rule: dict[str, Any]) -> dict[str, Any]:
    try:
        rule["payload"] = json.loads(rule["payload_json"]) if rule["payload_json"] else None
    except json.JSONDecodeError:
        rule["payload"] = rule["payload_json"]
    return rule


class RuleVersionBody(BaseModel):
    code: str
    title: str
    payload: dict[str, Any] | None = None


@router.get("/rules")
def list_rules():
    conn = connect()
    try:
        return [_decorate(r) for r in rule_repo.list_rule_versions(conn)]
    finally:
        conn.close()


@router.post("/rules")
def create_rule(body: RuleVersionBody) -> dict[str, Any]:
    code = (body.code or "").strip()
    if not code:
        raise HTTPException(status_code=400, detail="规则版本号不能为空")
    conn = connect()
    try:
        now = _now()
        rid = rule_repo.create_rule_version(
            conn,
            code=code,
            title=body.title,
            payload_json=json.dumps(body.payload or {}, ensure_ascii=False),
            created_at=now,
        )
        conn.commit()
        rule = rule_repo.get_rule_version(conn, rid)
        return _decorate(rule)
    finally:
        conn.close()


@router.post("/rules/{rule_version_id}/promote")
def promote_rule(rule_version_id: int) -> dict[str, Any]:
    conn = connect()
    try:
        rule = rule_repo.get_rule_version(conn, rule_version_id)
        if not rule:
            raise HTTPException(status_code=404, detail="规则版本不存在")
        if int(rule["active"]) == 1:
            # 重复晋升同一版本会平白令已有运行作废，拒绝。
            raise HTTPException(
                status_code=400,
                detail=f"规则版本 {rule['code']} 已生效，无需重复晋升",
            )
        now = _now()
        seq = rule_repo.promote_rule_version(conn, rule_version_id, now)
        conn.commit()
        rule = rule_repo.get_rule_version(conn, rule_version_id)
        rule["promoted_now"] = True
        rule["promotion_seq"] = seq
        return _decorate(rule)
    finally:
        conn.close()
