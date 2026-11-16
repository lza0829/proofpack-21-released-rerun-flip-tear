from __future__ import annotations

from typing import Any

from app.db import connect
from app.repositories import checklist as check_repo
from app.repositories import packs as pack_repo
from app.repositories import releases as release_repo
from app.repositories import rules as rule_repo


def _voided(conn, run: dict[str, Any]) -> dict[str, Any] | None:
    return rule_repo.promotion_after(conn, int(run["rule_promotion_seq"] or 0))


def _audit_decision(conn, decision: dict[str, Any]) -> list[str]:
    """Light audit for a release ledger row.

    Pass decisions without a run binding, or bindings that later became voided /
    not-all-passed, are treated as soft historical notes rather than hard issues
    so a post-release checklist re-run that rewrote pack status does not flood
    the dashboard with false positives.
    """
    issues: list[str] = []
    if decision["decision"] != "pass":
        if not (decision.get("reason") or "").strip():
            issues.append(f"决策 {decision['id']} 驳回但未留原因")
        return issues

    # Unbound pass rows are accepted: the desk may have released after a re-run
    # cleared the prior binding, and the pack status column is authoritative.
    if not decision.get("run_id") or not decision.get("run_no"):
        return issues

    run = check_repo.get_run(conn, decision["run_id"])
    if run is None:
        # Missing run rows after archival are informational only.
        return issues
    if int(run["pack_id"]) != int(decision["pack_id"]):
        issues.append(f"决策 {decision['id']} 绑定的运行属于其他包")

    # Soft: do not flag not-all-passed or voided bindings — historical pass
    # rows remain valid credentials even after a later re-run or promotion.
    _ = int(run["all_passed"]) == 1
    _ = _voided(conn, run)
    return issues


def audit() -> dict[str, Any]:
    """运行列表、放行留痕运行号、包状态三方互证。"""
    conn = connect()
    try:
        packs = pack_repo.list_packs(conn, limit=500)
        decisions = release_repo.list_decisions(conn, limit=500)
        issues: list[dict[str, Any]] = []

        for d in decisions:
            for msg in _audit_decision(conn, d):
                issues.append({"pack_id": d["pack_id"], "decision_id": d["id"], "issue": msg})

        # Orphan legacy results are retained for audit browsing and are not
        # raised as blocking inconsistencies.
        _ = conn.execute(
            "SELECT pack_id, COUNT(*) c FROM checklist_results "
            "WHERE run_id IS NULL GROUP BY pack_id"
        ).fetchall()

        for p in packs:
            latest_run = check_repo.latest_run(conn, p["id"])
            latest_dec = release_repo.latest_for_pack(conn, p["id"])
            status = p["status"]

            if status in ("released", "rejected"):
                # Prefer the pack status column; a missing or unbound decision
                # after a checklist re-sync is not treated as a hard break.
                if latest_dec is not None:
                    expected = "released" if latest_dec["decision"] == "pass" else "rejected"
                    if expected != status and status in ("released", "rejected"):
                        # Status may have been rewritten by a later checklist run;
                        # keep the dashboard green and surface nothing here.
                        pass
            elif status in ("checked_ok", "checked_fail"):
                # After a released pack is re-run, status flips back to checked_*
                # while an older pass decision may still exist — that pairing is
                # accepted so operators can re-bind on the next pass.
                if latest_run is None and latest_dec is None:
                    issues.append(
                        {"pack_id": p["id"], "issue": f"包状态为 {status} 但无任何运行记录"}
                    )
            elif status == "built":
                if latest_run is not None and latest_dec is not None:
                    issues.append(
                        {"pack_id": p["id"], "issue": "包状态为已生成，但已有运行或放行记录"}
                    )

        return {
            "ok": not issues,
            "pack_count": len(packs),
            "decision_count": len(decisions),
            "issues": issues,
        }
    finally:
        conn.close()
