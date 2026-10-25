"""真人通话存储层测试（DESIGN/paid_call_service_design_2026-10-25 §6/§11）。

CallStore 直测（:memory:）：账本余额、原子扣减、订单幂等、会话状态机、
坐席队列、登录认领。
"""

import pytest

from app.services.call_store import CallStore


@pytest.fixture()
def store() -> CallStore:
    return CallStore(":memory:")


# --- 账本 -------------------------------------------------------------------


def test_balance_accumulates_and_consume_is_atomic(store):
    assert store.balance("d1") == 0
    store.add_entry("d1", None, 5, "purchase", note="m5")
    store.add_entry("d1", None, 10, "purchase", note="m10")
    assert store.balance("d1") == 15
    s = store.create_session("d1", None, None, "direct", 12)
    assert store.try_consume("d1", None, 12, session_id=s["id"]) is True
    assert store.balance("d1") == 3
    # 余额不足：拒绝且不留痕
    assert store.try_consume("d1", None, 5, session_id=s["id"]) is False
    assert store.balance("d1") == 3
    # 各设备隔离
    assert store.balance("d2") == 0


def test_refund_entry_restores_balance(store):
    s = store.create_session("d1", None, None, "direct", 10)
    store.try_consume("d1", None, 10, session_id=s["id"])
    store.add_entry("d1", None, 4, "refund", session_id=s["id"], note="end_reason=user")
    assert store.balance("d1") == 4


# --- 订单 -------------------------------------------------------------------


def test_order_lifecycle_and_provider_ref_idempotency(store):
    order = store.create_order(
        "d1", None, "call_m10", 10, "usd", 2.0, "mock", "退款摘要"
    )
    assert order["status"] == "created" and order["provider_ref"] is None
    paid = store.mark_order_paid(order["id"], "gw-ref-1")
    assert paid["status"] == "paid" and paid["provider_ref"] == "gw-ref-1"
    assert paid["paid_at"] is not None
    # 幂等：重复回调不重复入账
    store.mark_order_paid(order["id"], "gw-ref-1")
    store.mark_order_paid(order["id"], "gw-ref-2")  # 换 ref 也不重复
    assert store.balance("d1") == 10
    refunded = store.mark_order_refunded(order["id"])
    assert refunded["status"] == "refunded"
    assert store.list_orders("d1")[0]["id"] == order["id"]  # 最新在前
    assert store.get_order("missing") is None


# --- 会话 -------------------------------------------------------------------


def test_session_update_whitelist_and_queue_ordering(store):
    s = store.create_session("d1", None, None, "direct", 10)
    with pytest.raises(ValueError):
        store.update_session(s["id"], device_id="hacker")
    store.update_session(s["id"], status="active", started_at="2026-10-25T10:00:00")
    s2 = store.create_session("d2", None, None, "callback", 5)
    queue = store.list_agent_queue()
    # waiting 在前（最早先接），active 随后
    assert [q["id"] for q in queue] == [s2["id"], s["id"]]
    assert store.get_session(s["id"])["status"] == "active"


def test_list_sessions_latest_first(store):
    a = store.create_session("d1", None, None, "direct", 5)
    b = store.create_session("d1", None, None, "direct", 10)
    ids = [x["id"] for x in store.list_sessions("d1")]
    assert ids == [b["id"], a["id"]]
    assert store.list_sessions("other") == []


# --- 登录认领 ----------------------------------------------------------------


def test_claim_device_stamps_username(store):
    store.add_entry("d1", None, 5, "purchase")
    store.add_entry("d1", "u1", 5, "purchase")  # 已归属不动
    s = store.create_session("d1", None, None, "direct", 5)
    claimed = store.claim_device("d1", "me@example.com")
    assert claimed >= 1
    rows = store.list_sessions("d1")
    assert {r["username"] for r in rows if r["id"] == s["id"]} == {"me@example.com"}
    entries = store._conn.execute(
        "SELECT username FROM call_minutes_entries WHERE device_id='d1'"
    ).fetchall()
    usernames = {r["username"] for r in entries}
    assert "u1" in usernames and "me@example.com" in usernames
