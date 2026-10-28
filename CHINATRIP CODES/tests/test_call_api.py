"""真人通话端点测试（DESIGN/paid_call_service_design_2026-10-25 §8/§11）。

TestClient 全链路 mock：买分钟 → 余额 → 直拨会话 → 坐席接听 → 轮询到点
自动 exhausted → 余额 0；提前挂断退整分钟；waiting 超时退款；402/403/401/
422 语义；records 字段；设备隔离。

单例注入：fixture 把 `call_service._service` 换成 :memory: 存储 + 打好
补丁的 settings，用完还原（不影响其他测试模块）。
"""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.services import call_service as cs_module
from app.services.call_service import CallService
from app.services.call_store import CallStore

client = TestClient(create_app())
DEVICE = {"X-Device-ID": "dev-call-api"}
DEVICE2 = {"X-Device-ID": "dev-call-other"}
HOTLINE = "+8610012345678"
AGENT_KEY = "op-secret"


@pytest.fixture(autouse=True)
def call_env(monkeypatch):
    st = get_settings()
    monkeypatch.setattr(st, "call_hotline_number", HOTLINE)
    monkeypatch.setattr(st, "agent_console_key", AGENT_KEY)
    monkeypatch.setattr(st, "call_provider", "mock")
    monkeypatch.setattr(st, "call_waiting_timeout_seconds", 120)
    svc = CallService(CallStore(":memory:"), st)
    monkeypatch.setattr(cs_module, "_service", svc)
    return svc


def _buy(minutes: int = 10, device: dict | None = None) -> str:
    r = client.post(
        "/api/v1/call/orders",
        headers=device or DEVICE,
        json={"package_code": f"call_m{minutes}", "currency": "usd"},
    )
    assert r.status_code == 201, r.text
    order_id = r.json()["order_id"]
    c = client.post(f"/api/v1/call/orders/{order_id}/confirm", headers=device or DEVICE)
    assert c.status_code == 200
    return order_id


def _open(minutes: int = 10, mode: str = "direct", device: dict | None = None) -> dict:
    r = client.post(
        "/api/v1/call/sessions",
        headers=device or DEVICE,
        json={"duration_minutes": minutes, "mode": mode},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _agent(headers: dict | None = None):
    return {"X-Agent-Key": AGENT_KEY, **(headers or {})}


# --- 全链路：买 → 拨 → 接 → 到点强结 -----------------------------------------


def test_full_chain_direct_exhausts_at_zero():
    _buy(10)
    assert client.get("/api/v1/call/balance", headers=DEVICE).json() == {"minutes": 10}
    s = _open(10)
    assert s["dial"] == {"type": "tel", "number": HOTLINE}
    assert s["balance"] == 0  # 划入会话
    assert s["status"] == "waiting"
    # 坐席队列可见；错键 401
    q = client.get("/api/v1/call/agent/queue", headers=_agent()).json()
    assert q["hotline"] == HOTLINE and q["sessions"][0]["id"] == s["session_id"]
    assert (
        client.get(
            "/api/v1/call/agent/queue", headers={"X-Agent-Key": "wrong"}
        ).status_code
        == 401
    )
    a = client.post(
        f"/api/v1/call/agent/sessions/{s['session_id']}/answer",
        headers=_agent({"X-Agent-Name": "op1"}),
    )
    assert a.status_code == 200 and a.json()["status"] == "active"
    assert a.json()["agent"] == "op1"
    # 轮询 active：剩余满额
    v = client.get(f"/api/v1/call/sessions/{s['session_id']}", headers=DEVICE).json()
    assert v["status"] == "active" and v["remaining_seconds"] == 600
    assert v["started_at"] is not None
    # 回拨计时起点 10 分钟前 → 到点强结 exhausted，余额 0 不退
    get_call_service = cs_module.get_call_service()
    get_call_service.store.update_session(
        s["session_id"], started_at="2026-10-25T09:00:00"
    )
    v2 = client.get(f"/api/v1/call/sessions/{s['session_id']}", headers=DEVICE).json()
    assert v2["status"] == "ended" and v2["end_reason"] == "exhausted"
    assert v2["consumed_seconds"] == 600 and v2["remaining_seconds"] == 0
    assert v2["refund_minutes"] == 0
    assert client.get("/api/v1/call/balance", headers=DEVICE).json() == {"minutes": 0}


def test_early_end_refunds_whole_minutes():
    _buy(10)
    s = _open(10)
    client.post(
        f"/api/v1/call/agent/sessions/{s['session_id']}/answer", headers=_agent()
    )
    svc = cs_module.get_call_service()
    # 回拨接通时刻到 3 分 30 秒前：600-210=390s → 退 6 整分钟
    from datetime import datetime, timedelta

    started = datetime.now() - timedelta(minutes=3, seconds=30)
    svc.store.update_session(
        s["session_id"], started_at=started.isoformat(timespec="seconds")
    )
    e = client.post(f"/api/v1/call/sessions/{s['session_id']}/end", headers=DEVICE)
    body = e.json()
    assert body["status"] == "ended" and body["end_reason"] == "user"
    assert body["refund_minutes"] == 6
    assert 209 <= body["consumed_seconds"] <= 211
    assert client.get("/api/v1/call/balance", headers=DEVICE).json() == {"minutes": 6}


def test_waiting_timeout_expires_and_refunds():
    _buy(5)
    s = _open(5)
    svc = cs_module.get_call_service()
    svc.store.update_session(s["session_id"], created_at="2026-10-25T09:00:00")
    v = client.get(f"/api/v1/call/sessions/{s['session_id']}", headers=DEVICE).json()
    assert v["status"] == "expired" and v["end_reason"] == "timeout"
    assert v["refund_minutes"] == 5
    assert client.get("/api/v1/call/balance", headers=DEVICE).json() == {"minutes": 5}


# --- 校验与错误语义 -----------------------------------------------------------


def test_insufficient_minutes_402():
    _buy(5)
    r = client.post(
        "/api/v1/call/sessions", headers=DEVICE, json={"duration_minutes": 10}
    )
    assert r.status_code == 402 and r.json() == {"detail": "insufficient_minutes"}


def test_duration_validation_422():
    _buy(20)
    for minutes, mode in ((7, "direct"), (3, "direct"), (65, "direct")):
        r = client.post(
            "/api/v1/call/sessions",
            headers=DEVICE,
            json={"duration_minutes": minutes, "mode": mode},
        )
        assert r.status_code == 422 and r.json() == {"detail": "invalid_duration"}


def test_direct_requires_hotline_and_callback_requires_phone(monkeypatch):
    _buy(5)
    st = get_settings()
    monkeypatch.setattr(st, "call_hotline_number", "")
    r = client.post(
        "/api/v1/call/sessions", headers=DEVICE, json={"duration_minutes": 5}
    )
    assert r.status_code == 422 and r.json() == {"detail": "hotline_not_configured"}
    monkeypatch.setattr(st, "call_hotline_number", HOTLINE)
    r2 = client.post(
        "/api/v1/call/sessions",
        headers=DEVICE,
        json={"duration_minutes": 5, "mode": "callback"},
    )
    assert r2.status_code == 422 and r2.json() == {"detail": "phone_required"}
    r3 = client.post(
        "/api/v1/call/sessions",
        headers=DEVICE,
        json={"duration_minutes": 5, "mode": "callback", "phone": "+12025550123"},
    )
    assert r3.status_code == 201 and r3.json()["phone"] == "+12025550123"


def test_mock_confirm_403_when_provider_not_mock(monkeypatch):
    order = _buy(5)
    st = get_settings()
    monkeypatch.setattr(st, "call_provider", "stripe")
    r = client.post(f"/api/v1/call/orders/{order}/confirm", headers=DEVICE)
    assert r.status_code == 403 and r.json() == {"detail": "mock_only"}


def test_device_header_required_and_device_isolation():
    assert client.get("/api/v1/call/balance").status_code == 422
    _buy(5)
    s = _open(5)
    # 其他设备看不到、也结束不了本会话
    assert (
        client.get(
            f"/api/v1/call/sessions/{s['session_id']}", headers=DEVICE2
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/call/sessions/{s['session_id']}/end", headers=DEVICE2
        ).status_code
        == 404
    )
    assert client.get("/api/v1/call/balance", headers=DEVICE2).json() == {"minutes": 0}


# --- 记录（v1.2 评审要求：日期时间/时长/状态/分钟流水） ------------------------


def test_records_show_start_end_duration_and_minutes(monkeypatch):
    # 冻结 call_service 的时钟：answer→end 的真实墙钟间隔在全量跑满载时若
    # 超过 60s，「≈0 用时整分钟退回」前提被击穿（2026-10-28 偶发 balance 9）。
    # 冻结后 started_at == ended_at，consumed=0 成为确定性前提。
    from datetime import datetime as _dt

    import app.services.call_service as call_mod

    class _FrozenDT(_dt):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 28, 12, 0, 0)

    monkeypatch.setattr(call_mod, "datetime", _FrozenDT)

    order_id = _buy(10)
    s = _open(10)
    client.post(
        f"/api/v1/call/agent/sessions/{s['session_id']}/answer",
        headers=_agent({"X-Agent-Name": "op9"}),
    )
    client.post(f"/api/v1/call/sessions/{s['session_id']}/end", headers=DEVICE)
    rec = client.get("/api/v1/call/records", headers=DEVICE).json()
    assert rec["balance"] == 10  # 10 划入又整分钟退回（≈0 用时）
    assert len(rec["sessions"]) == 1
    row = rec["sessions"][0]
    for field in (
        "created_at",
        "started_at",
        "ended_at",
        "duration_label",
        "status",
        "end_reason",
        "refund_minutes",
        "consumed_seconds",
        "granted_minutes",
        "agent",
    ):
        assert field in row, field
    assert row["agent"] == "op9" and row["end_reason"] == "user"
    mm, ss = row["duration_label"].split(":")  # mm:ss 形态
    assert len(mm) == 2 and len(ss) == 2 and int(ss) < 60
    assert rec["orders"][0]["id"] == order_id and rec["orders"][0]["status"] == "paid"
