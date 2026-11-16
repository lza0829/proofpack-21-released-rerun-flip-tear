from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.db import connect
from app.repositories import checklist as check_repo
from app.repositories import packs as pack_repo
from app.repositories import releases as release_repo
from app.repositories import rules as rule_repo
from app.repositories import settings as settings_repo

POLICY_LATEST_ONLY = "latest_only"
POLICY_ANY_PASSED = "any_passed"
RELEASE_POLICIES = (POLICY_LATEST_ONLY, POLICY_ANY_PASSED)

POLICY_LABELS = {
    POLICY_LATEST_ONLY: "仅允许绑定该包最近一次且全过的运行",
    POLICY_ANY_PASSED: "允许绑定该包历史上任一次全过运行（晋升后旧运行作废）",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_release_policy(conn) -> str:
    value = settings_repo.get_setting(conn, "release_run_policy", POLICY_LATEST_ONLY)
    return value if value in RELEASE_POLICIES else POLICY_LATEST_ONLY


def _voided_reason(conn, run: dict[str, Any]) -> str | None:
    """运行之后若有规则版本晋升，则该历史运行作废，不可再用于放行。"""
    promoted = rule_repo.promotion_after(conn, int(run["rule_promotion_seq"] or 0))
    if not promoted:
        return None
    return (
        f"运行 {run['run_no']}（规则版本 {run['rule_version_code']}，晋升序号 "
        f"{run['rule_promotion_seq']}）之后，规则版本 {promoted['code']} 已于 "
        f"{promoted['promoted_at']} 晋升（晋升序号 {promoted['promotion_seq']}），"
        "该历史运行已作废，拒绝放行"
    )


def _load_run(
    conn,
    pack_id: int,
    run_id: int | None,
    run_no: str | None,
) -> dict[str, Any] | None:
    """按 run_id / run_no 载入运行；两者同时给出时必须指向同一运行。"""
    by_id = check_repo.get_run(conn, run_id) if run_id is not None else None
    by_no = check_repo.get_run_by_no(conn, str(run_no).strip()) if run_no and str(run_no).strip() else None

    if run_id is not None and by_id is None:
        raise HTTPException(status_code=404, detail="绑定的校验运行不存在，拒绝放行")
    if run_no and str(run_no).strip() and by_no is None:
        raise HTTPException(status_code=404, detail="绑定的校验运行不存在，拒绝放行")
    if by_id is not None and by_no is not None and int(by_id["id"]) != int(by_no["id"]):
        raise HTTPException(status_code=400, detail="run_id 与 run_no 指向不同运行，拒绝放行")

    run = by_id or by_no
    if run is not None and int(run["pack_id"]) != int(pack_id):
        raise HTTPException(
            status_code=400,
            detail=f"校验运行 {run['run_no']} 不属于该证据包，拒绝放行",
        )
    return run


def _resolve_run_for_pass(
    conn,
    pack_id: int,
    run_id: int | None,
    run_no: str | None,
) -> dict[str, Any]:
    """放行路径的运行绑定解析，全部为硬校验，任一不过即拒绝放行。

    不做任何“缺省取最近运行/空绑定也能过”的兜底：放行通过必须显式绑定一个
    真实存在、属于该包、全部通过、未被后续规则晋升作废的运行号。
    """
    has_no = bool(run_no and str(run_no).strip())
    if run_id is None and not has_no:
        raise HTTPException(
            status_code=400,
            detail="放行通过必须绑定一个校验运行号（run_id 或 run_no），未绑定运行号拒绝放行",
        )

    run = _load_run(conn, pack_id, run_id, run_no)
    if run is None:
        # 正常不会走到（_load_run 对显式入参缺失已 404），双保险。
        raise HTTPException(status_code=400, detail="未绑定有效校验运行号，拒绝放行")

    if int(run["all_passed"]) != 1:
        raise HTTPException(
            status_code=400,
            detail=f"校验运行 {run['run_no']} 未全部通过"
            f"（通过 {run['passed_count']}/{run['check_count']}），拒绝放行",
        )

    voided = _voided_reason(conn, run)
    if voided:
        raise HTTPException(status_code=400, detail=voided)

    return run


def _check_policy(conn, pack_id: int, run: dict[str, Any], policy: str) -> None:
    """按放行可用运行策略收口。"""
    if policy == POLICY_LATEST_ONLY:
        latest = check_repo.latest_run(conn, pack_id)
        if latest is None or int(latest["id"]) != int(run["id"]):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"当前策略为 latest_only：仅允许绑定该包最近一次且全过的运行，"
                    f"运行 {run['run_no']} 不是最近一次运行，拒绝放行"
                ),
            )
    # any_passed：历史上任一全过且未作废运行均可（作废已在前置校验拦截）。


def list_releases(limit: int = 50) -> list[dict[str, Any]]:
    conn = connect()
    try:
        rows = release_repo.list_decisions(conn, limit=limit)
        packs = {p["id"]: p for p in pack_repo.list_packs(conn, limit=500)}
        for r in rows:
            p = packs.get(r["pack_id"])
            r["pack_no"] = p["pack_no"] if p else None
            r["pack_status"] = p["status"] if p else None
            run = check_repo.get_run(conn, r["run_id"]) if r.get("run_id") else None
            r["run_exists"] = bool(run)
            r["run_all_passed"] = bool(run and int(run["all_passed"]) == 1)
            if run:
                promoted = rule_repo.promotion_after(conn, int(run["rule_promotion_seq"] or 0))
                r["run_rule_version_code"] = run["rule_version_code"]
                r["run_created_at"] = run["created_at"]
                r["run_voided"] = bool(promoted)
                r["run_voided_by"] = (
                    {
                        "code": promoted["code"],
                        "promoted_at": promoted["promoted_at"],
                        "promotion_seq": promoted["promotion_seq"],
                    }
                    if promoted
                    else None
                )
                r["run_check_count"] = run["check_count"]
                r["run_passed_count"] = run["passed_count"]
                r["run_failed_count"] = run["failed_count"]
            else:
                r["run_rule_version_code"] = r.get("rule_version_code")
                r["run_created_at"] = None
                r["run_voided"] = False
                r["run_voided_by"] = None
                r["run_check_count"] = None
                r["run_passed_count"] = None
                r["run_failed_count"] = None
        return rows
    finally:
        conn.close()


def set_release_policy(policy: str) -> dict[str, Any]:
    value = (policy or "").strip()
    if value not in RELEASE_POLICIES:
        raise HTTPException(
            status_code=400,
            detail="放行可用运行策略须为 latest_only（仅最近一次）或 any_passed（历史任一次）",
        )
    conn = connect()
    try:
        settings_repo.set_setting(conn, "release_run_policy", value)
        conn.commit()
        return {
            "release_run_policy": value,
            "release_run_policy_label": POLICY_LABELS[value],
        }
    finally:
        conn.close()


def list_settings() -> dict[str, str]:
    conn = connect()
    try:
        data = settings_repo.list_settings(conn)
        data["release_run_policy_label"] = POLICY_LABELS[get_release_policy(conn)]
        return data
    finally:
        conn.close()


def decide(
    pack_id: int,
    decision: str,
    reason: str | None = None,
    run_id: int | None = None,
    run_no: str | None = None,
) -> dict[str, Any]:
    decision = (decision or "").strip().lower()
    if decision not in ("pass", "reject"):
        raise HTTPException(status_code=400, detail="决策须为 pass 或 reject")

    conn = connect()
    try:
        pack = pack_repo.get_pack(conn, pack_id)
        if not pack:
            raise HTTPException(status_code=404, detail="证据包不存在")

        policy = get_release_policy(conn)
        run: dict[str, Any] | None = None

        if decision == "pass":
            # 硬收口：必须显式绑定真实存在、属于本包、全过、未作废的运行号，
            # 再按策略校验；未绑定/未全过/已作废/非最近运行一律拒放行。
            run = _resolve_run_for_pass(conn, pack_id, run_id, run_no)
            _check_policy(conn, pack_id, run, policy)
            if not reason or not str(reason).strip():
                reason = (
                    f"清单全部通过，依据运行 {run['run_no']}"
                    f"（规则版本 {run['rule_version_code']}），予以放行"
                )
            status = "released"
        else:
            if not reason or not str(reason).strip():
                raise HTTPException(status_code=400, detail="驳回须填写原因")
            if run_id is not None or (run_no and str(run_no).strip()):
                # 驳回可选绑运行；给了就必须真实存在且属于该包。
                run = _load_run(conn, pack_id, run_id, run_no)
            status = "rejected"

        now = _now()
        rid = release_repo.create_decision(
            conn,
            pack_id=pack_id,
            decision=decision,
            reason=reason,
            created_at=now,
            run_id=run["id"] if run else None,
            run_no=run["run_no"] if run else None,
            rule_version_id=run["rule_version_id"] if run else None,
            rule_version_code=run["rule_version_code"] if run else None,
            policy=policy,
        )
        # 决策接口是包状态机权威：人工放行/驳回可从任何状态迁入（含 released
        # 之后再驳回）；与复跑路径的 released 保护互斥，避免留痕与包态分叉。
        pack_repo.update_status(conn, pack_id, status, allow_from_released=True)
        conn.commit()

        return {
            "id": rid,
            "pack_id": pack_id,
            "pack_no": pack["pack_no"],
            "decision": decision,
            "reason": reason,
            "run_id": run["id"] if run else None,
            "run_no": run["run_no"] if run else None,
            "rule_version_id": run["rule_version_id"] if run else None,
            "rule_version_code": run["rule_version_code"] if run else None,
            "policy": policy,
            "pack_status": status,
            "created_at": now,
            "checklist_all_passed": bool(run and int(run["all_passed"]) == 1),
        }
    finally:
        conn.close()
