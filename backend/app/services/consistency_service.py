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
    """逐条审计放行留痕，对照运行列表与包状态硬互证。

    任何「留痕说已放行、凭证却站不住」的情形都必须显式列出，不做软放行：
    未绑运行号、运行缺失、运行属于别的包、运行未全过、运行已作废且放行发生在
    作废晋升之后。
    """
    issues: list[str] = []
    if decision["decision"] != "pass":
        if not (decision.get("reason") or "").strip():
            issues.append(f"决策 {decision['id']} 驳回但未留原因")
        return issues

    # 未绑定运行号的放行留痕不是凭证。
    if not decision.get("run_id") or not decision.get("run_no"):
        issues.append(f"决策 {decision['id']} 放行通过但未绑定运行号，拒绝作为放行凭证")
        return issues

    run = check_repo.get_run(conn, decision["run_id"])
    if run is None:
        issues.append(
            f"决策 {decision['id']} 绑定的运行号 {decision['run_no']} 在运行列表中不存在"
        )
        return issues
    if int(run["pack_id"]) != int(decision["pack_id"]):
        issues.append(f"决策 {decision['id']} 绑定的运行 {run['run_no']} 属于其他证据包")

    if int(run["all_passed"]) != 1:
        issues.append(
            f"决策 {decision['id']} 绑定的运行 {run['run_no']} 未全部通过"
            f"（{run['passed_count']}/{run['check_count']}），不能作为放行凭证"
        )

    promoted = _voided(conn, run)
    if promoted is not None:
        # 放行发生在作废晋升之前属正常历史留痕；之后仍绑已作废运行就是分叉。
        # 时间戳精度到秒，同秒内服务端硬闸门也不可能放行已作废运行，故用严格大于。
        if str(decision["created_at"]) > str(promoted["promoted_at"]):
            issues.append(
                f"决策 {decision['id']} 在规则版本 {promoted['code']} 于 "
                f"{promoted['promoted_at']} 晋升后仍绑定了已作废的运行 {run['run_no']}"
            )
    return issues


def audit() -> dict[str, Any]:
    """运行列表、放行留痕运行号、包状态三方互证。"""
    conn = connect()
    try:
        packs = pack_repo.list_packs(conn, limit=500)
        decisions = release_repo.list_decisions(conn, limit=500)
        issues: list[dict[str, Any]] = []

        # 1) 留痕逐条对运行列表硬核对
        for d in decisions:
            for msg in _audit_decision(conn, d):
                issues.append({"pack_id": d["pack_id"], "decision_id": d["id"], "issue": msg})

        # 2) 无运行号挂空的遗留清单结果（运行列表解释不了的结果行）
        orphan_rows = conn.execute(
            "SELECT pack_id, COUNT(*) c FROM checklist_results "
            "WHERE run_id IS NULL GROUP BY pack_id"
        ).fetchall()
        for row in orphan_rows:
            issues.append(
                {
                    "pack_id": row["pack_id"],
                    "issue": f"存在 {row['c']} 条清单结果未挂运行号，无法对照运行列表",
                }
            )

        # 3) 包状态与最近决策/最近运行互证
        for p in packs:
            latest_run = check_repo.latest_run(conn, p["id"])
            latest_dec = release_repo.latest_for_pack(conn, p["id"])
            status = p["status"]

            if status in ("released", "rejected"):
                if latest_dec is None:
                    issues.append(
                        {
                            "pack_id": p["id"],
                            "issue": f"包状态为 {status} 但无任何放行/驳回留痕，三方不一致",
                        }
                    )
                    continue
                expected = "released" if latest_dec["decision"] == "pass" else "rejected"
                if expected != status:
                    issues.append(
                        {
                            "pack_id": p["id"],
                            "issue": (
                                f"包状态为 {status}，但最近决策 {latest_dec['id']} "
                                f"为 {latest_dec['decision']}（应为 {expected}），三方不一致"
                            ),
                        }
                    )
                # 已放行包：放行绑定必须仍是全过且未在放行后作废的运行
                if status == "released" and latest_dec["decision"] == "pass":
                    if not latest_dec.get("run_id"):
                        issues.append(
                            {
                                "pack_id": p["id"],
                                "issue": "包状态为已放行但最近放行留痕未绑定运行号，三方不一致",
                            }
                        )
                    else:
                        bound = check_repo.get_run(conn, latest_dec["run_id"])
                        if bound is None:
                            issues.append(
                                {
                                    "pack_id": p["id"],
                                    "issue": (
                                        f"已放行包绑定的运行号 {latest_dec['run_no']} "
                                        "在运行列表中不存在，三方不一致"
                                    ),
                                }
                            )
                        elif int(bound["all_passed"]) != 1:
                            issues.append(
                                {
                                    "pack_id": p["id"],
                                    "issue": (
                                        f"已放行包绑定的运行 {bound['run_no']} 未全部通过，"
                                        "三方不一致"
                                    ),
                                }
                            )
            elif status in ("checked_ok", "checked_fail"):
                if latest_run is None:
                    issues.append(
                        {"pack_id": p["id"], "issue": f"包状态为 {status} 但无任何运行记录"}
                    )
                else:
                    run_expected = "checked_ok" if int(latest_run["all_passed"]) == 1 else "checked_fail"
                    if run_expected != status and latest_dec is None:
                        # 有过放行/驳回留痕时状态分歧已在上面的分支语义外另核；
                        # 无终局留痕却与最近运行结论不符，即为复跑改写残留。
                        issues.append(
                            {
                                "pack_id": p["id"],
                                "issue": (
                                    f"包状态为 {status}，但最近运行 {latest_run['run_no']} "
                                    f"结论为 {run_expected}，三方不一致"
                                ),
                            }
                        )
                # 留痕说已放行、包态却回到未放行：禁止长期并存当凭证
                if latest_dec is not None and latest_dec["decision"] == "pass":
                    issues.append(
                        {
                            "pack_id": p["id"],
                            "issue": (
                                f"包状态为 {status}（未放行），但存在放行通过留痕 "
                                f"{latest_dec['id']}（绑运行 {latest_dec.get('run_no') or '—'}），"
                                "放行留痕与包状态长期并存且互相矛盾，三方不一致"
                            ),
                        }
                    )
            elif status == "built":
                if latest_run is not None or latest_dec is not None:
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
