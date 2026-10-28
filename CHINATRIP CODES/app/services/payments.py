# -*- coding: utf-8 -*-
"""客户付款层（DESIGN/PAYMENTS_PROGRESS.md，2026-10-25）。

定位：**公司↔客户**收款层（铁律 22 渠道 handoff 不变——渠道侧订票支付仍由
渠道完成；本层只服务两类形态）：

- ``pay_now``：客户在 H5 立即支付一笔报价金额（hosted Checkout 跳转）。
- ``save_method``：客户保存支付方式（Stripe token 保险库，**原始卡号永远
  不经过本服务器**），运营侧代订后凭 X-Operator-Token 扣款（concierge）。

网关做成可替换协议：默认 ``mock``（零网络全流程，LLM_BACKEND=mock 同款离线
哲学），``stripe`` 走 httpx 手写 REST + 手写 HMAC-SHA256 webhook 验签（无新
pip 依赖）；日后 Airwallex 等在协议后并列。金额 yuan float（repo 惯例），
只在 Stripe adapter 内转 cents。铁律 23：每条记录带 refund_summary 文案。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.services.lang_ctx import L

logger = logging.getLogger(__name__)

# 支持币种白名单（H5 下拉提供 cny/usd/eur，其余留给扩展；小写 ISO 4217）。
SUPPORTED_CURRENCIES = frozenset(
    {"cny", "usd", "eur", "gbp", "hkd", "sgd", "jpy", "cad", "aud"}
)
MAX_AMOUNT_YUAN = 100_000.0  # 单笔 sanity 上限（防手滑多打一个 0）

DEFAULT_REFUND_SUMMARY = (
    "未支付可随时取消；支付成功后退改以订单页为准，退款请联系客服。"
    "Refunds after payment: contact support; terms per order page."
)

_REFUND_SUMMARY_EN = (
    "Cancel anytime before payment; after payment, changes and refunds "
    "follow the order page - contact support for refunds."
)


def default_refund_summary() -> str:
    """按请求语言取默认退款文案（pydantic 字段默认是 import 期恒定 zh，
    请求期创建记录走本函数）。"""
    return L(DEFAULT_REFUND_SUMMARY, _REFUND_SUMMARY_EN)


PAY_STATUS_PENDING = "pending"
PAY_STATUS_SUCCEEDED = "succeeded"
PAY_STATUS_CANCELED = "canceled"
PAY_STATUS_REFUNDED = "refunded"
PAY_STATUS_METHOD_SAVED = "method_saved"

KIND_PAY_NOW = "pay_now"
KIND_SAVE_METHOD = "save_method"


class PaymentError(Exception):
    """Payment layer error. Message is safe to surface via API detail."""


class InvalidPaymentRequest(PaymentError):
    pass


class SignatureError(PaymentError):
    """Stripe-Signature verification failure (webhook must 400/400-ish)."""


class NoSavedMethodError(PaymentError):
    pass


class PaymentRecord(BaseModel):
    id: str
    device_id: str
    username: str | None = None
    kind: str  # pay_now | save_method
    amount_yuan: float | None = None
    currency: str = "cny"
    description: str = ""
    email: str | None = None
    refund_summary: str = DEFAULT_REFUND_SUMMARY
    status: str = PAY_STATUS_PENDING
    provider: str = "mock"
    provider_ref: str | None = None  # checkout session id（stripe）/ mock 假 id
    charge_ref: str | None = None  # payment_intent id（退款对账用）
    customer_ref: str | None = None
    payment_method_ref: str | None = None
    saved_method_label: str | None = None  # 仅品牌+末4位，无敏感数据
    handoff_id: str | None = None
    trip_item_id: str | None = None
    created_at: str
    updated_at: str
    paid_at: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PaymentStore:
    """内存 dict 热路径 + SQLite write-through（state_persist.py 同款模式：
    单连接 + threading.Lock + check_same_thread=False；坏行 warning 跳过，
    一条脏数据绝不能带崩收款服务）。支付记录必须可持久——不用 HandoffStore
    那种纯内存模式。"""

    def __init__(self, db_path: str) -> None:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS payments ("
            "id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self._conn.commit()
        self._lock = threading.Lock()
        self._records: dict[str, PaymentRecord] = {}
        for (payload,) in self._conn.execute("SELECT payload FROM payments"):
            try:
                rec = PaymentRecord.model_validate_json(payload)
            except Exception:
                logger.warning("payments: dropping corrupt row", exc_info=True)
                continue
            self._records[rec.id] = rec

    def put(self, record: PaymentRecord) -> None:
        with self._lock:
            self._records[record.id] = record
            self._conn.execute(
                "INSERT OR REPLACE INTO payments (id, payload) VALUES (?, ?)",
                (record.id, record.model_dump_json()),
            )
            self._conn.commit()

    def get(self, payment_id: str) -> PaymentRecord | None:
        return self._records.get(payment_id)

    def all_records(self) -> list[PaymentRecord]:
        return list(self._records.values())

    def list_for_device(self, device_id: str) -> list[PaymentRecord]:
        rows = [r for r in self._records.values() if r.device_id == device_id]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows

    def list_for_account(self, username: str) -> list[PaymentRecord]:
        rows = [r for r in self._records.values() if r.username == username]
        rows.sort(key=lambda r: r.created_at, reverse=True)
        return rows


class PaymentGateway(Protocol):
    """收银台协议：create_checkout 返回托管收银台 URL；charge_saved 用已存
    方式扣款并返回新 PaymentRecord；describe_payment_method 只回品牌+末4位。"""

    provider: str

    def create_checkout(
        self, record: PaymentRecord, success_url: str, cancel_url: str
    ) -> str: ...

    def charge_saved(
        self, source: PaymentRecord, amount_yuan: float, description: str
    ) -> PaymentRecord: ...

    def describe_payment_method(self, payment_method_id: str) -> str | None: ...


class MockGateway:
    """零网络假收银台：H5 收到 /h5/?mockpay=<id> 弹假支付层，确认按钮打
    POST /payments/{id}/confirm（仅 mock 后端开放）。"""

    provider = "mock"

    def create_checkout(
        self, record: PaymentRecord, success_url: str, cancel_url: str
    ) -> str:
        record.provider_ref = f"mock_cs_{record.id}"
        return "/h5/?mockpay=" + record.id

    def charge_saved(
        self, source: PaymentRecord, amount_yuan: float, description: str
    ) -> PaymentRecord:
        now = _now_iso()
        return PaymentRecord(
            id=_new_payment_id(),
            device_id=source.device_id,
            username=source.username,
            kind=KIND_PAY_NOW,
            amount_yuan=amount_yuan,
            currency=source.currency,
            description=description or L("代订扣款（mock）", "Concierge charge (mock)"),
            refund_summary=source.refund_summary,
            status=PAY_STATUS_SUCCEEDED,
            provider=self.provider,
            charge_ref=f"mock_pi_{uuid.uuid4().hex[:12]}",
            customer_ref=source.customer_ref,
            payment_method_ref=source.payment_method_ref,
            handoff_id=source.handoff_id,
            trip_item_id=source.trip_item_id,
            created_at=now,
            updated_at=now,
            paid_at=now,
        )

    def describe_payment_method(self, payment_method_id: str) -> str | None:
        return "Mock Card ••4242"


class StripeGateway:
    """Stripe hosted Checkout（httpx 手写 REST，无 stripe SDK 依赖）。

    - pay_now → ``mode=payment`` + line_items[0][price_data]（cents 在此转换）。
    - save_method → 先建 customer 再 ``mode=setup``（客户无感知存卡）。
    - 扣款 → ``/v1/payment_intents`` off_session confirm（需已存 pm）。
    """

    provider = "stripe"
    API_BASE = "https://api.stripe.com/v1"
    TIMEOUT_SECONDS = 10.0

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    @staticmethod
    def to_cents(amount_yuan: float) -> int:
        return int(round(amount_yuan * 100))

    def _post(self, path: str, pairs: list[tuple[str, str]]) -> dict:
        try:
            resp = httpx.post(
                self.API_BASE + path,
                data=pairs,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self.TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise PaymentError(f"stripe_unreachable: {exc}") from None
        if resp.status_code >= 400:
            detail = resp.json().get("error", {}).get("message", "")[:200]
            raise PaymentError(f"stripe_{resp.status_code}: {detail}")
        return resp.json()

    def _get(self, path: str) -> dict:
        try:
            resp = httpx.get(
                self.API_BASE + path,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self.TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise PaymentError(f"stripe_unreachable: {exc}") from None
        if resp.status_code >= 400:
            raise PaymentError(f"stripe_{resp.status_code}: {path}")
        return resp.json()

    def create_checkout(
        self, record: PaymentRecord, success_url: str, cancel_url: str
    ) -> str:
        pairs: list[tuple[str, str]] = [
            ("client_reference_id", record.id),
            ("metadata[payment_id]", record.id),
            ("success_url", success_url),
            ("cancel_url", cancel_url),
        ]
        if record.kind == KIND_PAY_NOW:
            pairs += [
                ("mode", "payment"),
                ("line_items[0][quantity]", "1"),
                ("line_items[0][price_data][currency]", record.currency),
                (
                    "line_items[0][price_data][unit_amount]",
                    str(self.to_cents(record.amount_yuan or 0.0)),
                ),
                (
                    "line_items[0][price_data][product_data][name]",
                    record.description or "ChinaTrip booking service",
                ),
            ]
        else:
            customer = self._post(
                "/customers",
                [
                    ("metadata[payment_id]", record.id),
                    *([("email", record.email)] if record.email else []),
                ],
            )
            record.customer_ref = customer["id"]
            pairs += [("mode", "setup"), ("customer", record.customer_ref)]
        session = self._post("/checkout/sessions", pairs)
        record.provider_ref = session.get("id")
        return session["url"]

    def charge_saved(
        self, source: PaymentRecord, amount_yuan: float, description: str
    ) -> PaymentRecord:
        if not source.customer_ref or not source.payment_method_ref:
            raise NoSavedMethodError("no_saved_method")
        intent = self._post(
            "/payment_intents",
            [
                ("amount", str(self.to_cents(amount_yuan))),
                ("currency", source.currency),
                ("customer", source.customer_ref),
                ("payment_method", source.payment_method_ref),
                ("confirm", "true"),
                ("off_session", "true"),
                ("description", description or "ChinaTrip concierge charge"),
            ],
        )
        now = _now_iso()
        succeeded = intent.get("status") == "succeeded"
        return PaymentRecord(
            id=_new_payment_id(),
            device_id=source.device_id,
            username=source.username,
            kind=KIND_PAY_NOW,
            amount_yuan=amount_yuan,
            currency=source.currency,
            description=description or "ChinaTrip concierge charge",
            refund_summary=source.refund_summary,
            status=PAY_STATUS_SUCCEEDED if succeeded else PAY_STATUS_PENDING,
            provider=self.provider,
            charge_ref=intent.get("id"),
            customer_ref=source.customer_ref,
            payment_method_ref=source.payment_method_ref,
            handoff_id=source.handoff_id,
            trip_item_id=source.trip_item_id,
            created_at=now,
            updated_at=now,
            paid_at=now if succeeded else None,
        )

    def describe_payment_method(self, payment_method_id: str) -> str | None:
        try:
            pm = self._get(f"/payment_methods/{payment_method_id}")
        except PaymentError:
            logger.info(
                "payments: describe_payment_method failed for %s",
                payment_method_id,
            )
            return None
        card = pm.get("card") or {}
        brand = card.get("brand") or "card"
        last4 = card.get("last4")
        return f"{brand.upper()} ••{last4}" if last4 else None


def _new_payment_id() -> str:
    return "pay_" + uuid.uuid4().hex[:12]


def verify_stripe_signature(
    payload: bytes,
    sig_header: str,
    secret: str,
    tolerance_seconds: float = 300.0,
) -> None:
    """Stripe-Signature: ``t=<ts>,v1=<hex>[,v1=...]``；HMAC-SHA256 over
    ``f"{t}." + payload``，常时比较，默认 ±300s 防重放。失败抛 SignatureError。"""
    if not sig_header or not secret:
        raise SignatureError("missing_signature")
    timestamp: str | None = None
    candidates: list[str] = []
    for part in sig_header.split(","):
        key, _, value = part.partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            candidates.append(value)
    if timestamp is None or not candidates:
        raise SignatureError("malformed_signature")
    try:
        age = abs(time.time() - float(timestamp))
    except ValueError:
        raise SignatureError("malformed_signature") from None
    if age > tolerance_seconds:
        raise SignatureError("expired_signature")
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    if not any(hmac.compare_digest(expected, c) for c in candidates):
        raise SignatureError("bad_signature")


class PaymentService:
    def __init__(self, store: PaymentStore, gateway: PaymentGateway) -> None:
        self.store = store
        self.gateway = gateway

    # --- 创建收银台 ---------------------------------------------------------

    def create_checkout(
        self,
        *,
        device_id: str,
        username: str | None,
        kind: str,
        amount_yuan: float | None,
        currency: str | None,
        description: str,
        refund_summary: str | None,
        handoff_id: str | None,
        trip_item_id: str | None,
        email: str | None,
        success_url: str | None,
        cancel_url: str | None,
        base_url: str = "",
    ) -> tuple[PaymentRecord, str]:
        if kind not in (KIND_PAY_NOW, KIND_SAVE_METHOD):
            raise InvalidPaymentRequest("invalid_kind")
        if kind == KIND_PAY_NOW:
            if amount_yuan is None or amount_yuan <= 0:
                raise InvalidPaymentRequest("amount_required")
            if amount_yuan > MAX_AMOUNT_YUAN:
                raise InvalidPaymentRequest("amount_too_large")
        curr = (currency or get_settings().payments_default_currency).lower()
        if curr not in SUPPORTED_CURRENCIES:
            raise InvalidPaymentRequest("unsupported_currency")
        now = _now_iso()
        record = PaymentRecord(
            id=_new_payment_id(),
            device_id=device_id,
            username=username,
            kind=kind,
            amount_yuan=amount_yuan,
            currency=curr,
            description=description or "",
            email=email,
            refund_summary=refund_summary or default_refund_summary(),
            provider=self.gateway.provider,
            handoff_id=handoff_id,
            trip_item_id=trip_item_id,
            created_at=now,
            updated_at=now,
        )
        # 默认回跳带 pay_return=<id>：Stripe 跳回 H5 后前端据此轮询状态；
        # 生产在 settings 配绝对地址覆盖。
        if not success_url:
            success_url = base_url.rstrip("/") + "/h5/?pay_return=" + record.id
        if not cancel_url:
            cancel_url = base_url.rstrip("/") + "/h5/"
        checkout_url = self.gateway.create_checkout(record, success_url, cancel_url)
        self.store.put(record)
        return record, checkout_url

    # --- mock 专用确认（SMTP dev-echo 同款豁免逻辑） ------------------------

    def confirm_mock(self, payment_id: str) -> PaymentRecord | None:
        if self.gateway.provider != "mock":
            raise PaymentError("mock_only")
        record = self.store.get(payment_id)
        if record is None or record.status != PAY_STATUS_PENDING:
            return record
        now = _now_iso()
        if record.kind == KIND_PAY_NOW:
            record.status = PAY_STATUS_SUCCEEDED
            record.paid_at = now
        else:
            record.status = PAY_STATUS_METHOD_SAVED
            record.payment_method_ref = "pm_mock_4242"
            record.customer_ref = record.customer_ref or f"cus_mock_{record.id}"
            record.saved_method_label = "Mock Card ••4242"
        record.updated_at = now
        self.store.put(record)
        return record

    # --- webhook 事件落账 ---------------------------------------------------

    def apply_webhook_event(self, event_type: str, data: dict) -> PaymentRecord | None:
        if event_type == "checkout.session.completed":
            payment_id = data.get("client_reference_id") or (
                data.get("metadata") or {}
            ).get("payment_id")
            record = self.store.get(payment_id) if payment_id else None
            if record is None:
                return None
            now = _now_iso()
            if record.kind == KIND_PAY_NOW:
                if data.get("payment_status", "paid") == "paid":
                    record.status = PAY_STATUS_SUCCEEDED
                    record.paid_at = now
                    record.charge_ref = data.get("payment_intent") or record.charge_ref
            else:
                record.status = PAY_STATUS_METHOD_SAVED
                pm_id = data.get("payment_method")
                if pm_id:
                    record.payment_method_ref = pm_id
                    record.saved_method_label = self.gateway.describe_payment_method(
                        pm_id
                    )
            record.updated_at = now
            self.store.put(record)
            return record
        if event_type == "checkout.session.expired":
            payment_id = data.get("client_reference_id") or (
                data.get("metadata") or {}
            ).get("payment_id")
            record = self.store.get(payment_id) if payment_id else None
            if record and record.status == PAY_STATUS_PENDING:
                record.status = PAY_STATUS_CANCELED
                record.updated_at = _now_iso()
                self.store.put(record)
            return record
        if event_type == "charge.refunded":
            intent_id = data.get("payment_intent")
            if not intent_id:
                return None
            for rec in self.store.all_records():
                if rec.charge_ref == intent_id:
                    rec.status = PAY_STATUS_REFUNDED
                    rec.updated_at = _now_iso()
                    self.store.put(rec)
                    return rec
            return None
        return None

    # --- 运营侧扣款（concierge） -------------------------------------------

    def charge_saved(
        self, payment_id: str, amount_yuan: float, description: str
    ) -> tuple[PaymentRecord, PaymentRecord]:
        """对已存支付方式扣款；返回 (源存卡记录, 新扣款记录)。"""
        source = self.store.get(payment_id)
        if source is None:
            raise PaymentError("not_found")
        if source.kind != KIND_SAVE_METHOD or source.status != PAY_STATUS_METHOD_SAVED:
            raise InvalidPaymentRequest("not_a_saved_method")
        if amount_yuan is None or amount_yuan <= 0 or amount_yuan > MAX_AMOUNT_YUAN:
            raise InvalidPaymentRequest("amount_invalid")
        charged = self.gateway.charge_saved(source, amount_yuan, description)
        self.store.put(charged)
        return source, charged


# --- 进程级单例（trip_items.py 的 lazy singleton 依赖模式） -----------------

_service_singleton: PaymentService | None = None


def build_payment_service(settings) -> PaymentService:  # noqa: ANN001 Settings
    store = PaymentStore(settings.payments_db_url.removeprefix("sqlite:///"))
    if settings.payments_backend == "stripe" and settings.stripe_api_key:
        gateway: PaymentGateway = StripeGateway(settings.stripe_api_key)
    else:
        if settings.payments_backend == "stripe":
            logger.warning(
                "payments_backend=stripe 但 stripe_api_key 未配置 → mock 诚实降级"
            )
        gateway = MockGateway()
    return PaymentService(store=store, gateway=gateway)


def get_payments_service() -> PaymentService:
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = build_payment_service(get_settings())
    return _service_singleton
