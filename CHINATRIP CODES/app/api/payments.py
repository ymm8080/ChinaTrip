# -*- coding: utf-8 -*-
"""客户付款 API（DESIGN/PAYMENTS_PROGRESS.md，2026-10-25）。

公司与客户之间的收款层（铁律 22 渠道 handoff 不变；本路由只管收款）：

- ``POST /payments/checkout``     建收银台（pay_now / save_method）→ checkout_url
- ``GET  /payments/{id}``         单条状态（返回后 H5 轮询）
- ``GET  /payments/mine``         本设备/账号的付款记录
- ``POST /payments/{id}/confirm`` 仅 mock 后端：模拟支付成功（dev-echo 豁免）
- ``POST /payments/webhook/stripe`` Stripe webhook（无设备鉴权，验签放行）
- ``POST /payments/{id}/charge``  运营侧对已存方式扣款（X-Operator-Token 守卫）

错误映射：InvalidPaymentRequest → 400；SignatureError → 400 invalid_signature；
PaymentError/NoSavedMethodError → 400/404 语义化 detail。鉴权同 itineraries.py：
X-Device-ID 必填，Bearer 可选（登录态只用于记录归属）。
"""

import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.itineraries import _account_from_auth
from app.config import get_settings
from app.services.payments import (
    InvalidPaymentRequest,
    NoSavedMethodError,
    PaymentError,
    PaymentRecord,
    SignatureError,
    verify_stripe_signature,
)
from app.services.payments import (
    get_payments_service as _get_payments_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


def get_payments_service():
    # 薄包装：保持 FastAPI Depends 可注入（tests 直接 monkeypatch 服务层单例）。
    return _get_payments_service()


class CheckoutRequest(BaseModel):
    kind: str = Field(pattern="^(pay_now|save_method)$")
    amount_yuan: float | None = Field(default=None, gt=0, le=100_000)
    currency: str | None = Field(default=None, max_length=8)
    description: str | None = Field(default=None, max_length=500)
    refund_summary: str | None = Field(default=None, max_length=1000)
    handoff_id: str | None = Field(default=None, max_length=128)
    trip_item_id: str | None = Field(default=None, max_length=128)
    email: str | None = Field(default=None, max_length=254)


class OperatorChargeRequest(BaseModel):
    amount_yuan: float = Field(gt=0, le=100_000)
    description: str | None = Field(default=None, max_length=500)


def _require_device(x_device_id: str | None) -> str:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    return x_device_id


def _return_urls(request: Request) -> tuple[str | None, str | None, str]:
    """settings 配置优先；空则传 None 由服务层按 base_url 生成默认回跳
    （success 带 pay_return=<payment_id> 供前端轮询）。"""
    settings = get_settings()
    base = str(request.base_url).rstrip("/")
    return (
        settings.payments_success_url or None,
        settings.payments_cancel_url or None,
        base,
    )


@router.post("/checkout")
async def create_checkout(
    body: CheckoutRequest,
    request: Request,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    account: str | None = Depends(_account_from_auth),
    service=Depends(get_payments_service),
) -> dict:
    device_id = _require_device(x_device_id)
    success_url, cancel_url, base_url = _return_urls(request)
    try:
        record, checkout_url = service.create_checkout(
            device_id=device_id,
            username=account,
            kind=body.kind,
            amount_yuan=body.amount_yuan,
            currency=body.currency,
            description=body.description or "",
            refund_summary=body.refund_summary,
            handoff_id=body.handoff_id,
            trip_item_id=body.trip_item_id,
            email=body.email,
            success_url=success_url,
            cancel_url=cancel_url,
            base_url=base_url,
        )
    except InvalidPaymentRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except PaymentError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from None
    return {
        "payment_id": record.id,
        "checkout_url": checkout_url,
        "status": record.status,
        "refund_summary": record.refund_summary,
    }


@router.get("/mine")
async def list_mine(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    account: str | None = Depends(_account_from_auth),
    service=Depends(get_payments_service),
) -> dict:
    device_id = _require_device(x_device_id)
    rows = service.store.list_for_device(device_id)
    if account is not None:
        seen = {r.id for r in rows}
        rows += [r for r in service.store.list_for_account(account) if r.id not in seen]
    rows.sort(key=lambda r: r.created_at, reverse=True)
    return {"payments": [r.model_dump() for r in rows]}


@router.post("/webhook/stripe")
async def stripe_webhook(
    request: Request,
    service=Depends(get_payments_service),
) -> dict:
    """无设备鉴权：靠 Stripe-Signature 验签放行。原始 body 必须原样参与验签。"""
    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    secret = get_settings().stripe_webhook_secret
    try:
        verify_stripe_signature(payload, sig, secret)
    except SignatureError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    try:
        envelope = json.loads(payload)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid_payload") from None
    event_type = envelope.get("type", "")
    record = service.apply_webhook_event(event_type, envelope.get("data") or {})
    return {"received": True, "payment_id": record.id if record else None}


@router.get("/{payment_id}")
async def get_payment(
    payment_id: str,
    service=Depends(get_payments_service),
) -> dict:
    record: PaymentRecord | None = service.store.get(payment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="payment_not_found")
    return record.model_dump()


@router.post("/{payment_id}/confirm")
async def confirm_mock(
    payment_id: str,
    service=Depends(get_payments_service),
) -> dict:
    """仅 mock 后端：模拟支付成功（dev 联调零网络；SMTP echo 同款豁免）。"""
    if get_settings().payments_backend != "mock":
        raise HTTPException(status_code=403, detail="mock_backend_only")
    try:
        record = service.confirm_mock(payment_id)
    except PaymentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    if record is None:
        raise HTTPException(status_code=404, detail="payment_not_found")
    return record.model_dump()


@router.post("/{payment_id}/charge")
async def operator_charge(
    payment_id: str,
    body: OperatorChargeRequest,
    x_operator_token: str | None = Header(default=None, alias="X-Operator-Token"),
    service=Depends(get_payments_service),
) -> dict:
    """运营侧 concierge 扣款：X-Operator-Token 共享密钥；未配置 ⇒ 整体禁用。"""
    expected = get_settings().payments_operator_token
    if not expected or not x_operator_token or x_operator_token != expected:
        raise HTTPException(status_code=403, detail="operator_only")
    try:
        _source, charged = service.charge_saved(
            payment_id, body.amount_yuan, body.description or ""
        )
    except NoSavedMethodError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except InvalidPaymentRequest as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except PaymentError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return charged.model_dump()
