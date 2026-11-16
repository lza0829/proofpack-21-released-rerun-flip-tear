from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="proofpack-test-")
os.environ["DATA_DIR"] = _TMP

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    db = Path(_TMP) / "app.db"
    if db.exists():
        db.unlink()
    with TestClient(app) as c:
        yield c


def _make_pack(client, subject_code="store_dayend") -> dict:
    subjects = client.get("/api/subjects").json()
    subject = next(s for s in subjects if s["code"] == subject_code)
    batch = client.post("/api/samples/run", json={"subject_id": subject["id"]}).json()
    pack = client.post("/api/packs/build", json={"batch_id": batch["id"]}).json()
    return pack


def _run(client, pack_id: int) -> dict:
    r = client.post("/api/checklist/run", json={"pack_id": pack_id})
    assert r.status_code == 200, r.text
    return r.json()


def _pass(client, pack_id: int, **kw):
    return client.post("/api/releases/decide", json={"pack_id": pack_id, "decision": "pass", **kw})


def test_each_run_is_independent_record(client):
    pack = _make_pack(client)
    first = _run(client, pack["id"])
    second = _run(client, pack["id"])

    assert first["run_no"] != second["run_no"]
    assert first["run_id"] != second["run_id"]
    assert first["rule_version_code"] and second["rule_version_code"]
    assert first["all_passed"] is True
    # 各项结果、计数、时间都随运行落库
    assert first["check_count"] == len(first["results"]) == 3
    assert first["passed_count"] == 3 and first["failed_count"] == 0
    assert first["created_at"]

    runs = client.get(f"/api/checklist/runs?pack_id={pack['id']}").json()
    assert {r["run_no"] for r in runs} == {first["run_no"], second["run_no"]}

    # 复跑不会抹掉旧运行的结果
    results = client.get(f"/api/checklist?pack_id={pack['id']}").json()
    assert {r["run_no"] for r in results} == {first["run_no"], second["run_no"]}
    assert len(results) == 6

    run_detail = client.get(f"/api/checklist/runs/{first['run_id']}").json()
    assert len(run_detail["results"]) == 3


def test_pass_requires_run_binding(client):
    pack = _make_pack(client)
    run = _run(client, pack["id"])

    missing = _pass(client, pack["id"])
    assert missing.status_code == 400
    assert "运行号" in missing.json()["detail"]

    bogus = _pass(client, pack["id"], run_no="CR-NOPE")
    assert bogus.status_code == 404

    bogus_id = _pass(client, pack["id"], run_id=999999)
    assert bogus_id.status_code == 404


def test_pass_binds_run_and_leaves_trace(client):
    pack = _make_pack(client)
    run = _run(client, pack["id"])
    resp = _pass(client, pack["id"], run_id=run["run_id"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["run_id"] == run["run_id"]
    assert body["run_no"] == run["run_no"]
    assert body["rule_version_code"] == run["rule_version_code"]
    assert run["run_no"] in body["reason"]

    trace = client.get("/api/releases").json()[0]
    assert trace["run_no"] == run["run_no"]
    assert trace["run_exists"] is True
    assert trace["run_all_passed"] is True

    # 包状态与运行互证
    pack_after = client.get(f"/api/packs/{pack['id']}").json()
    assert pack_after["status"] == "released"
    assert pack_after["latest_run_no"] == run["run_no"]
    assert pack_after["latest_run_all_passed"] is True


def test_failed_run_cannot_be_bound(client, monkeypatch):
    pack = _make_pack(client)
    first = _run(client, pack["id"])
    assert first["all_passed"] is True

    # 直接往运行里注入一个未通过项，模拟「该运行未全过」
    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "UPDATE checklist_runs SET all_passed=0, passed_count=2, failed_count=1 WHERE id=?",
            (first["run_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    resp = _pass(client, pack["id"], run_id=first["run_id"])
    assert resp.status_code == 400
    assert "未全部通过" in resp.json()["detail"]


def test_latest_only_policy_rejects_older_run(client):
    pack = _make_pack(client)
    old = _run(client, pack["id"])
    new = _run(client, pack["id"])

    resp = _pass(client, pack["id"], run_id=old["run_id"])
    assert resp.status_code == 400
    assert "最近一次" in resp.json()["detail"]

    ok = _pass(client, pack["id"], run_id=new["run_id"])
    assert ok.status_code == 200, ok.text


def test_any_passed_policy_allows_history_then_promotion_voids(client):
    pack = _make_pack(client)
    old = _run(client, pack["id"])
    new = _run(client, pack["id"])

    r = client.post(
        "/api/settings/release-policy", json={"release_run_policy": "any_passed"}
    )
    assert r.status_code == 200, r.text

    ok = _pass(client, pack["id"], run_id=old["run_id"])
    assert ok.status_code == 200, ok.text
    trace = client.get("/api/releases").json()[0]
    assert trace["run_no"] == old["run_no"]
    assert trace["rule_version_code"] == old["rule_version_code"]

    # 晋升一个新规则版本：旧运行作废，新策略下也不能再绑
    created = client.post(
        "/api/rules",
        json={"code": "RULES-V2", "title": "基础校验规则 v2", "payload": {"checks": []}},
    ).json()
    client.post(f"/api/rules/{created['id']}/promote")

    blocked = _pass(client, pack["id"], run_id=old["run_id"])
    assert blocked.status_code == 400
    assert "作废" in blocked.json()["detail"]

    # 晋级后需要重新跑清单，得到新规则版本的运行才可放行
    fresh = _run(client, pack["id"])
    assert fresh["rule_version_code"] == "RULES-V2"
    ok2 = _pass(client, pack["id"], run_id=fresh["run_id"])
    assert ok2.status_code == 200, ok2.text


def test_reject_requires_reason_but_not_run(client):
    pack = _make_pack(client)
    _run(client, pack["id"])

    no_reason = client.post(
        "/api/releases/decide", json={"pack_id": pack["id"], "decision": "reject"}
    )
    assert no_reason.status_code == 400

    ok = client.post(
        "/api/releases/decide",
        json={"pack_id": pack["id"], "decision": "reject", "reason": "键重复，暂缓"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["run_id"] is None
    assert ok.json()["reason"] == "键重复，暂缓"


def test_run_from_other_pack_rejected(client):
    pack_a = _make_pack(client)
    pack_b = _make_pack(client)
    run_b = _run(client, pack_b["id"])

    resp = _pass(client, pack_a["id"], run_id=run_b["run_id"])
    assert resp.status_code == 400
    assert "不属于该证据包" in resp.json()["detail"]


def test_pack_status_follows_latest_run(client):
    pack = _make_pack(client)
    first = _run(client, pack["id"])
    assert client.get(f"/api/packs/{pack['id']}").json()["status"] == "checked_ok"
    assert first["run_no"] == client.get(f"/api/packs/{pack['id']}").json()["latest_run_no"]


def test_consistency_audit_reports_and_ok(client):
    pack = _make_pack(client)
    run = _run(client, pack["id"])
    assert client.get("/api/consistency").json()["ok"] is True

    ok = _pass(client, pack["id"], run_id=run["run_id"])
    assert ok.status_code == 200, ok.text
    audit = client.get("/api/consistency").json()
    assert audit["ok"] is True, audit

    # 人为破坏：把包状态改成与运行/决策不一致
    from app.db import connect

    conn = connect()
    try:
        conn.execute("UPDATE evidence_packs SET status='checked_fail' WHERE id=?", (pack["id"],))
        conn.commit()
    finally:
        conn.close()
    audit = client.get("/api/consistency").json()
    assert audit["ok"] is False
    assert any("不一致" in i["issue"] for i in audit["issues"])


def test_consistency_audit_flags_pass_without_run(client):
    pack = _make_pack(client)
    _run(client, pack["id"])

    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO release_decisions(pack_id, decision, reason, created_at) "
            "VALUES (?, 'pass', '手工放行', '2026-01-01T00:00:00Z')",
            (pack["id"],),
        )
        conn.execute(
            "UPDATE evidence_packs SET status='released' WHERE id=?", (pack["id"],)
        )
        conn.commit()
    finally:
        conn.close()

    audit = client.get("/api/consistency").json()
    assert audit["ok"] is False
    assert any("未绑定运行号" in i["issue"] for i in audit["issues"])


def test_duplicate_promote_rejected(client):
    created = client.post(
        "/api/rules",
        json={"code": "RULES-V3", "title": "基础校验规则 v3", "payload": {}},
    ).json()
    first = client.post(f"/api/rules/{created['id']}/promote")
    assert first.status_code == 200, first.text
    second = client.post(f"/api/rules/{created['id']}/promote")
    assert second.status_code == 400


def test_legacy_checked_status_without_run_detected(client):
    """旧数据里包状态是包级『已通过』但无运行记录，必须被互证自检揪出。"""
    pack = _make_pack(client)

    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "UPDATE evidence_packs SET status='checked_ok' WHERE id=?", (pack["id"],)
        )
        conn.commit()
    finally:
        conn.close()

    audit = client.get("/api/consistency").json()
    assert audit["ok"] is False
    assert any("无任何运行记录" in i["issue"] for i in audit["issues"])


def test_run_id_and_run_no_must_agree(client):
    pack = _make_pack(client)
    r1 = _run(client, pack["id"])
    r2 = _run(client, pack["id"])

    mismatch = _pass(client, pack["id"], run_id=r1["run_id"], run_no=r2["run_no"])
    assert mismatch.status_code == 400
    assert "不同运行" in mismatch.json()["detail"]

    by_no = _pass(client, pack["id"], run_no=r2["run_no"])
    assert by_no.status_code == 200, by_no.text
    assert by_no.json()["run_no"] == r2["run_no"]


def test_consistency_flags_orphan_legacy_results(client):
    pack = _make_pack(client)
    _run(client, pack["id"])

    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO checklist_results(pack_id, check_code, check_title, passed, detail, created_at) "
            "VALUES (?, 'count_match', '条数一致', 1, '旧数据', '2026-01-01T00:00:00Z')",
            (pack["id"],),
        )
        conn.commit()
    finally:
        conn.close()

    audit = client.get("/api/consistency").json()
    assert audit["ok"] is False
    assert any("未挂运行号" in i["issue"] for i in audit["issues"])


def test_historical_pass_before_promotion_is_not_flagged(client):
    """晋升前做出的历史放行留痕属正常；晋升后仍绑旧运行才违规。"""
    pack = _make_pack(client)
    run = _run(client, pack["id"])
    client.post("/api/settings/release-policy", json={"release_run_policy": "any_passed"})
    assert _pass(client, pack["id"], run_id=run["run_id"]).status_code == 200

    created = client.post(
        "/api/rules", json={"code": "RULES-V9", "title": "新规则", "payload": {}}
    ).json()
    client.post(f"/api/rules/{created['id']}/promote")

    audit = client.get("/api/consistency").json()
    assert audit["ok"] is True, audit["issues"]

    # 伪造一条「晋升之后仍绑旧运行」的放行留痕，应被识别
    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO release_decisions(pack_id, decision, reason, run_id, run_no, "
            "rule_version_id, rule_version_code, policy, created_at) "
            "VALUES (?, 'pass', '伪造', ?, ?, ?, ?, 'any_passed', '2099-01-01T00:00:00Z')",
            (pack["id"], run["run_id"], run["run_no"], run["rule_version_id"], run["rule_version_code"]),
        )
        conn.commit()
    finally:
        conn.close()
    audit = client.get("/api/consistency").json()
    assert audit["ok"] is False
    assert any("晋升后仍绑定了已作废的运行" in i["issue"] for i in audit["issues"])
