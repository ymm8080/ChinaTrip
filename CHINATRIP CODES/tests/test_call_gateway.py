"""真人通话网关测试（DESIGN/paid_call_service_design_2026-10-25 §7.1/§11）。

Mock 形状、支付宝/Stripe 门控 stub（键未配 503）、webhook 幂等与语义。
"""

import pytest

from app.config import get_settings
from app.services.call_service import (
    AlipayWapGateway,
    CallError,
    CallService,
    MockGateway,
    StripeCheckoutGateway,
    get_gateway,
)
from app.services.call_store import CallStore


@pytest.fixture()
def svc(monkeypatch) -> CallService:
    st = get_settings()
    monkeypatch.setattr(st, "call_hotline_number", "+8610012345678")
    monkeypatch.setattr(st, "call_provider", "mock")
    return CallService(CallStore(":memory:"), st)


def test_mock_gateway_shape(svc):
    assert MockGateway(svc.settings).create_payment({}) == {"type": "mock_confirm"}
    assert get_gateway(svc.settings).name == "mock"


def test_alipay_stub_requires_keys(svc, monkeypatch):
    gw = AlipayWapGateway(svc.settings)
    with pytest.raises(CallError) as ei:
        gw.create_payment({"id": "x"})
    assert ei.value.status_code == 503
    assert ei.value.detail == "provider_not_configured"
    # 键配齐后进入「未实装」态（签约后实装 wap 表单）
    monkeypatch.setattr(svc.settings, "alipay_app_id", "2026xxx")
    monkeypatch.setattr(svc.settings, "alipay_private_key", "key")
    monkeypatch.setattr(svc.settings, "alipay_alipay_public_key", "pub")
    with pytest.raises(CallError) as ei2:
        gw.create_payment({"id": "x"})
    assert ei2.value.detail == "provider_not_implemented"


def test_stripe_stub_requires_key(svc, monkeypatch):
    with pytest.raises(CallError) as ei:
        StripeCheckoutGateway(svc.settings).create_payment({"id": "x"})
    assert ei.value.detail == "provider_not_configured"
    monkeypatch.setattr(svc.settings, "stripe_api_key", "sk_test_x")
    with pytest.raises(CallError) as ei2:
        StripeCheckoutGateway(svc.settings).create_payment({"id": "x"})
    assert ei2.value.detail == "provider_not_implemented"


def test_create_order_uses_gateway_provider(svc, monkeypatch):
    monkeypatch.setattr(svc.settings, "call_provider", "alipay")
    svc.gateway = get_gateway(svc.settings)
    with pytest.raises(CallError) as ei:
        svc.create_order("d1", None, "call_m5", "cny")
    assert ei.value.status_code == 503  # 诚实降级：不给假收银台


def test_webhook_mock_idempotent(svc):
    order = svc.create_order("d1", None, "call_m10", "usd")
    svc.handle_webhook("mock", {"order_id": order["order_id"]})
    svc.handle_webhook("mock", {"order_id": order["order_id"], "provider_ref": "r2"})
    assert svc.balance("d1") == 10  # 重复回调只入账一次
    with pytest.raises(CallError) as ei:
        svc.handle_webhook("mock", {"order_id": "missing"})
    assert ei.value.status_code == 404
    with pytest.raises(CallError) as ei2:
        svc.handle_webhook("alipay", {"order_id": order["order_id"]})
    assert ei2.value.status_code == 503  # 渠道不匹配 = 未配置
