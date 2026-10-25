# -*- coding: utf-8 -*-
"""客户付款层测试（DESIGN/PAYMENTS_PROGRESS.md T7）。

覆盖：SQLite 写穿透 store 往返/重启重载/坏行跳过；mock 全流程（checkout →
confirm → succeeded / 存卡 → method_saved → 运营扣款）；参数校验；Stripe
webhook 验签（好/坏/过期/畸形）；webhook 事件落账（paid/setup/refunded/
expired）；StripeGateway form payload 与错误映射（monkeypatch httpx，仿
amap 测试风格）；API 守卫（设备头缺失 / confirm 仅 mock / operator token）。
"""

import hashlib
import hmac
import json
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from app.api import payments as papi
from app.main import create_app
from app.services import payments as psvc

client = TestClient(create_app())
DEVICE = {"X-Device-ID": "dev-pay"}


# --- 环境搭建 ----------------------------------------------------------------


def _settings(
    tmp_path, *, backend="mock", operator="", webhook_secret="whsec_t", with_key=False
):
    # with_key 默认 False：stripe 后端测试一律走"无 key 诚实降级"，绝不出网。
    class _S:
        payments_backend = backend
        payments_db_url = f"sqlite:///{tmp_path / 'p.db'}"
        stripe_api_key = "sk_test_x" if with_key else ""
        stripe_webhook_secret = webhook_secret
        payments_default_currency = "cny"
        payments_success_url = ""
        payments_cancel_url = ""
        payments_operator_token = operator

    return _S()


def _patch_env(monkeypatch, tmp_path, **kw):
    """API + 服务两层 get_settings 全部指向测试配置，单例强制重建。"""
    s = _settings(tmp_path, **kw)
    monkeypatch.setattr(psvc, "get_settings", lambda: s)
    monkeypatch.setattr(papi, "get_settings", lambda: s)
    monkeypatch.setattr(psvc, "_service_singleton", None)
    return s


def _rec(pid="pay_t1", device="dev-x", **kw):
    base = dict(
        id=pid,
        device_id=device,
        kind="pay_now",
        created_at="2026-10-25T00:00:00+00:00",
        updated_at="2026-10-25T00:00:00+00:00",
    )
    base.update(kw)
    return psvc.PaymentRecord(**base)


def _svc(tmp_path, **kw):
    return psvc.build_payment_service(_settings(tmp_path, **kw))


def _checkout(s, kind="pay_now", **kw):
    args = dict(
        device_id="d1",
        username=None,
        kind=kind,
        amount_yuan=100.0 if kind == "pay_now" else None,
        currency=None,
        description="测试单",
        refund_summary=None,
        handoff_id=None,
        trip_item_id=None,
        email=None,
        success_url=None,
        cancel_url=None,
        base_url="http://test",
    )
    args.update(kw)
    return s.create_checkout(**args)


# --- store：写穿透 / 重启重载 / 坏行跳过 --------------------------------------


def test_store_roundtrip_and_reload(tmp_path):
    db = str(tmp_path / "p.db")
    s1 = psvc.PaymentStore(db)
    s1.put(_rec(amount_yuan=553.0, description="d1"))
    s2 = psvc.PaymentStore(db)  # 模拟重启重载
    got = s2.get("pay_t1")
    assert got is not None
    assert got.amount_yuan == 553.0 and got.description == "d1"
    assert [r.id for r in s2.list_for_device("dev-x")] == ["pay_t1"]
    assert [r.id for r in s2.list_for_account("nope")] == []
    assert len(s2.all_records()) == 1


def test_store_drops_corrupt_row(tmp_path):
    db = str(tmp_path / "p.db")
    s1 = psvc.PaymentStore(db)
    s1.put(_rec())
    conn = sqlite3.connect(db)
    conn.execute("UPDATE payments SET payload='{bad json'")
    conn.commit()
    conn.close()
    s2 = psvc.PaymentStore(db)  # 坏行 warning 跳过，绝不带崩服务
    assert s2.get("pay_t1") is None


# --- 服务层：mock 全流程 / 校验 / confirm 豁免边界 ----------------------------


def test_mock_full_flow_pay_now_save_and_charge(tmp_path):
    s = _svc(tmp_path)
    rec, url = _checkout(s)
    assert url == "/h5/?mockpay=" + rec.id
    assert rec.status == "pending" and rec.refund_summary  # 铁律 23 恒有摘要
    done = s.confirm_mock(rec.id)
    assert done.status == "succeeded" and done.paid_at

    rec2, _ = _checkout(s, kind="save_method", email="a@b.c")
    done2 = s.confirm_mock(rec2.id)
    assert done2.status == "method_saved"
    assert done2.saved_method_label == "Mock Card ••4242"
    assert done2.payment_method_ref == "pm_mock_4242"

    src, charged = s.charge_saved(rec2.id, 88.0, "代订扣款")
    assert src.id == rec2.id
    assert charged.status == "succeeded"
    assert charged.amount_yuan == 88.0 and charged.device_id == "d1"
    assert charged.kind == "pay_now" and charged.charge_ref


def test_create_checkout_validation(tmp_path):
    s = _svc(tmp_path)
    with pytest.raises(psvc.InvalidPaymentRequest):
        _checkout(s, amount_yuan=None)  # pay_now 缺金额
    with pytest.raises(psvc.InvalidPaymentRequest):
        _checkout(s, amount_yuan=0)
    with pytest.raises(psvc.InvalidPaymentRequest):
        _checkout(s, amount_yuan=psvc.MAX_AMOUNT_YUAN + 1)
    with pytest.raises(psvc.InvalidPaymentRequest):
        _checkout(s, currency="xyz")
    with pytest.raises(psvc.InvalidPaymentRequest):
        _checkout(s, kind="whatever")


def test_confirm_mock_rejected_on_stripe_gateway(tmp_path):
    s = psvc.PaymentService(
        store=psvc.PaymentStore(str(tmp_path / "p.db")),
        gateway=psvc.StripeGateway("sk_test_x"),
    )
    with pytest.raises(psvc.PaymentError):
        s.confirm_mock("pay_nope")


def test_default_return_urls_carry_payment_id(tmp_path):
    s = _svc(tmp_path)
    rec, _ = _checkout(s)
    assert rec.provider_ref == "mock_cs_" + rec.id


# --- Stripe webhook 验签 ------------------------------------------------------


def _sig_header(secret: str, payload: bytes, ts: int | None = None) -> str:
    t = str(ts if ts is not None else int(time.time()))
    v1 = hmac.new(
        secret.encode(), t.encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    return f"t={t},v1={v1}"


def test_verify_signature_ok_and_bad():
    payload = b'{"a":1}'
    psvc.verify_stripe_signature(payload, _sig_header("whsec", payload), "whsec")
    with pytest.raises(psvc.SignatureError):
        psvc.verify_stripe_signature(payload, _sig_header("other", payload), "whsec")
    with pytest.raises(psvc.SignatureError):  # 超时窗（防重放）
        psvc.verify_stripe_signature(
            payload, _sig_header("whsec", payload, ts=int(time.time()) - 9999), "whsec"
        )
    with pytest.raises(psvc.SignatureError):
        psvc.verify_stripe_signature(payload, "garbage", "whsec")
    with pytest.raises(psvc.SignatureError):
        psvc.verify_stripe_signature(payload, "", "whsec")
    with pytest.raises(psvc.SignatureError):
        psvc.verify_stripe_signature(payload, _sig_header("whsec", payload), "")


# --- webhook 事件落账 --------------------------------------------------------


def test_webhook_events_update_records(tmp_path):
    s = _svc(tmp_path)
    rec, _ = _checkout(s, amount_yuan=200.0)
    out = s.apply_webhook_event(
        "checkout.session.completed",
        {
            "client_reference_id": rec.id,
            "payment_status": "paid",
            "payment_intent": "pi_1",
        },
    )
    assert out.status == "succeeded" and out.charge_ref == "pi_1" and out.paid_at
    out2 = s.apply_webhook_event("charge.refunded", {"payment_intent": "pi_1"})
    assert out2.status == "refunded"

    rec2, _ = _checkout(s, kind="save_method")
    out3 = s.apply_webhook_event(
        "checkout.session.completed",
        {"metadata": {"payment_id": rec2.id}, "payment_method": "pm_1"},
    )
    assert out3.status == "method_saved" and out3.payment_method_ref == "pm_1"

    rec3, _ = _checkout(s, amount_yuan=5.0)
    s.apply_webhook_event("checkout.session.expired", {"client_reference_id": rec3.id})
    assert s.store.get(rec3.id).status == "canceled"

    # 未匹配 / 未知事件 → None，绝不抛
    assert s.apply_webhook_event("payout.paid", {}) is None
    assert (
        s.apply_webhook_event(
            "checkout.session.completed", {"client_reference_id": "pay_nope"}
        )
        is None
    )


# --- StripeGateway：payload / 客户建档 / 扣款 / 错误映射 ----------------------


class _Resp:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


def test_to_cents():
    assert psvc.StripeGateway.to_cents(553) == 55300
    assert psvc.StripeGateway.to_cents(12.5) == 1250


def test_stripe_gateway_checkout_payload(monkeypatch):
    seen = {}

    def fake_post(url, data=None, headers=None, timeout=None):
        seen.update({"url": url, "data": data, "headers": headers})
        return _Resp(
            {"id": "cs_test_1", "url": "https://checkout.stripe.com/pay/cs_test_1"}
        )

    monkeypatch.setattr(psvc.httpx, "post", fake_post)
    gw = psvc.StripeGateway("sk_test_x")
    rec = _rec(amount_yuan=553.0, currency="cny", description="门票")
    url = gw.create_checkout(rec, "https://h/h5/?pay_return=x", "https://h/h5/")
    assert url.endswith("cs_test_1") and rec.provider_ref == "cs_test_1"
    d = dict(seen["data"])
    assert d["mode"] == "payment"
    assert d["line_items[0][price_data][unit_amount]"] == "55300"
    assert d["line_items[0][price_data][currency]"] == "cny"
    assert d["client_reference_id"] == rec.id
    assert d["success_url"] == "https://h/h5/?pay_return=x"
    assert seen["headers"]["Authorization"] == "Bearer sk_test_x"


def test_stripe_gateway_setup_creates_customer(monkeypatch):
    def fake_post(url, data=None, headers=None, timeout=None):
        if url.endswith("/customers"):
            return _Resp({"id": "cus_1"})
        return _Resp({"id": "cs_2", "url": "https://stripe/x"})

    monkeypatch.setattr(psvc.httpx, "post", fake_post)
    rec = _rec(kind="save_method", email="a@b.c")
    psvc.StripeGateway("sk_test_x").create_checkout(rec, "s", "c")
    assert rec.customer_ref == "cus_1"


def test_stripe_gateway_charge_and_errors(monkeypatch):
    gw = psvc.StripeGateway("sk_test_x")
    src = _rec(
        id="pay_s",
        kind="save_method",
        status="method_saved",
        customer_ref="cus_1",
        payment_method_ref="pm_1",
    )

    def fake_post(url, data=None, headers=None, timeout=None):
        assert url.endswith("/payment_intents")
        d = dict(data)
        assert (
            d["amount"] == "12300"
            and d["off_session"] == "true"
            and d["confirm"] == "true"
        )
        assert d["customer"] == "cus_1" and d["payment_method"] == "pm_1"
        return _Resp({"id": "pi_9", "status": "succeeded"})

    monkeypatch.setattr(psvc.httpx, "post", fake_post)
    charged = gw.charge_saved(src, 123.0, "代订")
    assert charged.status == "succeeded" and charged.charge_ref == "pi_9"

    with pytest.raises(psvc.NoSavedMethodError):  # 缺存卡方式
        gw.charge_saved(_rec(kind="save_method", status="method_saved"), 1.0, "x")

    monkeypatch.setattr(
        psvc.httpx,
        "post",
        lambda *a, **k: _Resp({"error": {"message": "card_declined"}}, 402),
    )
    with pytest.raises(psvc.PaymentError):
        gw.charge_saved(src, 1.0, "x")


def test_stripe_describe_payment_method(monkeypatch):
    gw = psvc.StripeGateway("sk_test_x")
    monkeypatch.setattr(
        psvc.httpx,
        "get",
        lambda *a, **k: _Resp({"card": {"brand": "visa", "last4": "4242"}}),
    )
    assert gw.describe_payment_method("pm_1") == "VISA ••4242"

    def _boom(*a, **k):
        raise psvc.PaymentError("x")

    monkeypatch.setattr(psvc.httpx, "get", _boom)
    assert gw.describe_payment_method("pm_1") is None


# --- API 面：mock 流程 / 守卫 / webhook --------------------------------------


def test_api_mock_flow(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path)
    r = client.post(
        "/api/v1/payments/checkout",
        json={
            "kind": "pay_now",
            "amount_yuan": 553,
            "currency": "cny",
            "description": "smoke",
        },
        headers=DEVICE,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["checkout_url"].startswith("/h5/?mockpay=")
    assert body["refund_summary"]

    assert (
        client.post(
            "/api/v1/payments/checkout", json={"kind": "pay_now", "amount_yuan": 1}
        ).status_code
        == 400
    )  # 缺设备头
    assert (
        client.post(
            "/api/v1/payments/checkout", json={"kind": "pay_now"}, headers=DEVICE
        ).status_code
        == 400
    )  # 缺金额

    rc = client.post(f"/api/v1/payments/{body['payment_id']}/confirm")
    assert rc.status_code == 200 and rc.json()["status"] == "succeeded"

    rm = client.get("/api/v1/payments/mine", headers=DEVICE)
    assert any(p["id"] == body["payment_id"] for p in rm.json()["payments"])
    assert client.get("/api/v1/payments/pay_nope").status_code == 404


def test_api_confirm_403_under_stripe_backend(monkeypatch, tmp_path):
    _patch_env(
        monkeypatch, tmp_path, backend="stripe"
    )  # 无 key → mock 网关降级，但路由守卫仍 403
    r = client.post(
        "/api/v1/payments/checkout",
        json={"kind": "pay_now", "amount_yuan": 5},
        headers=DEVICE,
    )
    pid = r.json()["payment_id"]
    assert client.post(f"/api/v1/payments/{pid}/confirm").status_code == 403


def test_api_charge_guard_and_success(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, operator="op_tok")
    assert (
        client.post(
            "/api/v1/payments/pay_x/charge", json={"amount_yuan": 10}
        ).status_code
        == 403
    )  # 未带 token
    assert (
        client.post(
            "/api/v1/payments/pay_x/charge",
            json={"amount_yuan": 10},
            headers={"X-Operator-Token": "wrong"},
        ).status_code
        == 403
    )  # 错 token

    r = client.post(
        "/api/v1/payments/checkout", json={"kind": "save_method"}, headers=DEVICE
    )
    pid = r.json()["payment_id"]
    client.post(f"/api/v1/payments/{pid}/confirm")
    r2 = client.post(
        f"/api/v1/payments/{pid}/charge",
        json={"amount_yuan": 66.5, "description": "代订"},
        headers={"X-Operator-Token": "op_tok"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["status"] == "succeeded" and body["amount_yuan"] == 66.5

    rp = client.post(
        "/api/v1/payments/checkout",
        json={"kind": "pay_now", "amount_yuan": 5},
        headers=DEVICE,
    )
    r3 = client.post(
        f"/api/v1/payments/{rp.json()['payment_id']}/charge",
        json={"amount_yuan": 5},
        headers={"X-Operator-Token": "op_tok"},
    )
    assert r3.status_code == 400  # 对非存卡记录扣款


def test_api_charge_disabled_without_operator(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, operator="")
    r = client.post(
        "/api/v1/payments/pay_x/charge",
        json={"amount_yuan": 10},
        headers={"X-Operator-Token": "anything"},
    )
    assert r.status_code == 403


def test_api_webhook_signature_and_settlement(monkeypatch, tmp_path):
    _patch_env(monkeypatch, tmp_path, webhook_secret="whsec_t")
    r = client.post(
        "/api/v1/payments/checkout",
        json={"kind": "pay_now", "amount_yuan": 20},
        headers=DEVICE,
    )
    pid = r.json()["payment_id"]
    payload = json.dumps(
        {
            "type": "checkout.session.completed",
            "data": {
                "client_reference_id": pid,
                "payment_status": "paid",
                "payment_intent": "pi_live",
            },
        }
    ).encode()

    bad = client.post(
        "/api/v1/payments/webhook/stripe",
        content=payload,
        headers={
            "Stripe-Signature": "t=1,v1=deadbeef",
            "Content-Type": "application/json",
        },
    )
    assert bad.status_code == 400

    good = client.post(
        "/api/v1/payments/webhook/stripe",
        content=payload,
        headers={
            "Stripe-Signature": _sig_header("whsec_t", payload),
            "Content-Type": "application/json",
        },
    )
    assert good.status_code == 200 and good.json()["payment_id"] == pid
    assert client.get(f"/api/v1/payments/{pid}").json()["status"] == "succeeded"
