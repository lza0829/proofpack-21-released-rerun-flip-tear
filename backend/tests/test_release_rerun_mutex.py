"""已放行后复跑的互斥收口专项测试。

对照用户指定的三条路径，并以运行列表、放行留痕、包状态三方互证收口：
1. 已放行后复跑改包态（方案 A 下必须改不动）
2. 留痕绑定已作废运行（晋升后仍绑旧运行必须拒放行并被互证揪出）
3. 未绑运行号放行（必须硬拒，留痕也不得出现无绑定放行）
"""
from __future__ import annotations

import pytest

# config.DATA_DIR / db.DB_PATH 在 app 首次 import 时即定型，后改环境变量无效。
# 在 fixture 里用 monkeypatch 临时重绑 db.DB_PATH（connect() 调用时读取该全局），
# 测试结束自动还原，保证本模块每个用例独立成库且不污染同进程的其他测试模块。
from app import db as _db  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    monkeypatch.setattr(_db, "DB_PATH", db_path)
    with TestClient(app) as c:
        yield c


def _make_pack(client) -> dict:
    subjects = client.get("/api/subjects").json()
    subject = next(s for s in subjects if s["code"] == "store_dayend")
    batch = client.post("/api/samples/run", json={"subject_id": subject["id"]}).json()
    return client.post("/api/packs/build", json={"batch_id": batch["id"]}).json()


def _run(client, pack_id: int) -> dict:
    r = client.post("/api/checklist/run", json={"pack_id": pack_id})
    assert r.status_code == 200, r.text
    return r.json()


def _pass(client, pack_id: int, **kw):
    return client.post(
        "/api/releases/decide",
        json={"pack_id": pack_id, "decision": "pass", **kw},
    )


def _release_a_pack(client):
    pack = _make_pack(client)
    run = _run(client, pack["id"])
    resp = _pass(client, pack["id"], run_id=run["run_id"])
    assert resp.status_code == 200, resp.text
    return pack, run


# ---- 路径一：已放行后复跑改包态 ------------------------------------------------

def test_rerun_after_release_keeps_pack_released(client):
    pack, first = _release_a_pack(client)

    rerun = _run(client, pack["id"])
    assert rerun["run_id"] != first["run_id"]
    assert rerun["run_no"] != first["run_no"]

    # 新运行只追加审计，包态必须仍是已放行
    assert rerun["pack_status"] == "released"
    assert rerun["status_changed"] is False
    pack_after = client.get(f"/api/packs/{pack['id']}").json()
    assert pack_after["status"] == "released"

    # 运行列表保留两次运行；放行留痕仍指向当时全过的旧运行且继续有效
    runs = client.get(f"/api/checklist/runs?pack_id={pack['id']}").json()
    assert {r["run_no"] for r in runs} == {first["run_no"], rerun["run_no"]}
    trace = client.get("/api/releases").json()[0]
    assert trace["run_no"] == first["run_no"]
    assert trace["run_exists"] is True
    assert trace["run_all_passed"] is True
    assert trace["run_voided"] is False
    assert trace["pack_status"] == "released"

    audit = client.get("/api/consistency").json()
    assert audit["ok"] is True, audit["issues"]


def test_rerun_after_release_cannot_flip_even_when_new_run_fails(client):
    pack, first = _release_a_pack(client)

    # 人为让复跑产出的新运行未全过：已放行包态依旧不得被改写
    rerun = _run(client, pack["id"])
    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "UPDATE checklist_runs SET all_passed=0, passed_count=2, failed_count=1 WHERE id=?",
            (rerun["run_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    again = _run(client, pack["id"])
    assert again["pack_status"] == "released"
    assert client.get(f"/api/packs/{pack['id']}").json()["status"] == "released"
    # 原放行绑定的旧运行仍是全过凭证
    trace = client.get("/api/releases").json()[0]
    assert trace["run_no"] == first["run_no"]
    assert trace["run_all_passed"] is True
    audit = client.get("/api/consistency").json()
    assert audit["ok"] is True, audit["issues"]


def test_rejected_pack_rerun_resets_and_can_rebind_and_release(client):
    pack = _make_pack(client)
    _run(client, pack["id"])
    rej = client.post(
        "/api/releases/decide",
        json={"pack_id": pack["id"], "decision": "reject", "reason": "暂缓"},
    )
    assert rej.status_code == 200, rej.text
    assert client.get(f"/api/packs/{pack['id']}").json()["status"] == "rejected"

    rerun = _run(client, pack["id"])
    # 驳回不是放行终局：复跑带回校验结论
    assert rerun["pack_status"] == "checked_ok"
    assert rerun["status_changed"] is True

    ok = _pass(client, pack["id"], run_id=rerun["run_id"])
    assert ok.status_code == 200, ok.text
    assert client.get(f"/api/packs/{pack['id']}").json()["status"] == "released"
    assert client.get("/api/consistency").json()["ok"] is True


def test_released_pack_can_manually_reject_then_rerun_and_rebind(client):
    """人工决策是状态机权威：已放行后驳回必须真正落状态，不能被复跑保护挡死。"""
    pack, first = _release_a_pack(client)

    rej = client.post(
        "/api/releases/decide",
        json={"pack_id": pack["id"], "decision": "reject", "reason": "事后发现疑点，撤回放行"},
    )
    assert rej.status_code == 200, rej.text
    assert client.get(f"/api/packs/{pack['id']}").json()["status"] == "rejected"

    rerun = _run(client, pack["id"])
    assert rerun["pack_status"] == "checked_ok"
    ok = _pass(client, pack["id"], run_id=rerun["run_id"])
    assert ok.status_code == 200, ok.text
    assert client.get(f"/api/consistency").json()["ok"] is True


# ---- 路径二：留痕绑定已作废运行 ------------------------------------------------

def test_pass_rejects_run_voided_by_promotion(client):
    pack = _make_pack(client)
    old = _run(client, pack["id"])

    created = client.post(
        "/api/rules",
        json={"code": "RULES-V2", "title": "v2", "payload": {"checks": []}},
    ).json()
    prom = client.post(f"/api/rules/{created['id']}/promote")
    assert prom.status_code == 200, prom.text

    # 旧运行已作废：两种策略下都不得放行
    blocked = _pass(client, pack["id"], run_id=old["run_id"])
    assert blocked.status_code == 400
    assert "作废" in blocked.json()["detail"]
    assert client.get(f"/api/packs/{pack['id']}").json()["status"] != "released"

    # 新规则版本下重新跑，得到现行全过运行后才能放行
    fresh = _run(client, pack["id"])
    assert fresh["rule_version_code"] == "RULES-V2"
    ok = _pass(client, pack["id"], run_id=fresh["run_id"])
    assert ok.status_code == 200, ok.text


def test_audit_flags_ledger_binding_to_voided_run(client):
    pack, run = _release_a_pack(client)
    created = client.post(
        "/api/rules",
        json={"code": "RULES-V2", "title": "v2", "payload": {"checks": []}},
    ).json()
    client.post(f"/api/rules/{created['id']}/promote")

    # 伪造一条晋升之后仍绑旧运行的放行留痕，互证必须揪出
    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO release_decisions(pack_id, decision, reason, run_id, run_no, "
            "rule_version_id, rule_version_code, policy, created_at) "
            "VALUES (?, 'pass', '伪造', ?, ?, ?, ?, 'latest_only', '2099-01-01T00:00:00Z')",
            (pack["id"], run["run_id"], run["run_no"],
             run["rule_version_id"], run["rule_version_code"]),
        )
        conn.commit()
    finally:
        conn.close()

    audit = client.get("/api/consistency").json()
    assert audit["ok"] is False
    assert any("已作废" in i["issue"] for i in audit["issues"])


# ---- 路径三：未绑运行号放行 ----------------------------------------------------

def test_pass_without_run_binding_is_hard_refused(client):
    pack = _make_pack(client)
    _run(client, pack["id"])  # 即使存在最近运行，也不得自动兜底

    missing = _pass(client, pack["id"])
    assert missing.status_code == 400
    assert "运行号" in missing.json()["detail"]

    blank = _pass(client, pack["id"], run_no="  ")
    assert blank.status_code == 400
    assert "运行号" in blank.json()["detail"]

    # 包未被放行，留痕里也不得出现无绑定的 pass
    assert client.get(f"/api/packs/{pack['id']}").json()["status"] == "checked_ok"
    assert client.get("/api/releases").json() == []


def test_pass_with_nonexistent_and_failed_run_refused(client):
    pack = _make_pack(client)
    run = _run(client, pack["id"])

    no_such = _pass(client, pack["id"], run_no="CR-GHOST-999")
    assert no_such.status_code == 404
    no_such_id = _pass(client, pack["id"], run_id=999999)
    assert no_such_id.status_code == 404

    from app.db import connect

    conn = connect()
    try:
        conn.execute(
            "UPDATE checklist_runs SET all_passed=0, passed_count=2, failed_count=1 WHERE id=?",
            (run["run_id"],),
        )
        conn.commit()
    finally:
        conn.close()

    failed = _pass(client, pack["id"], run_id=run["run_id"])
    assert failed.status_code == 400
    assert "未全部通过" in failed.json()["detail"]

    # 运行被篡改未全过、包态却仍是校验通过：该分叉本身也须被三方互证捕获
    audit = client.get("/api/consistency").json()
    assert audit["ok"] is False
    assert any("三方不一致" in i["issue"] for i in audit["issues"])


def test_audit_flags_unbound_pass_ledger(client):
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
