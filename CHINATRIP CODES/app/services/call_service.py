"""真人通话咨询服务层（DESIGN/paid_call_service_design_2026-10-25 §3/§7）。

职责：套餐/余额/订单/会话的唯一写入口。账本与状态机的业务规则都在这里，
存储层（call_store）只管落库。收款走 CallPaymentGateway 协议——MVP=mock
零网络；支付宝 wap / Stripe 为门控 stub（键未配诚实 503），与客户付款层
（payments.py）的网关哲学同构，键亦共用。

会话状态机（服务端权威）：
    waiting --answer--> active --到点/挂断--> ended
       \\--超时/取消--> expired / ended（全额退）
计时以 started_at（坐席接听时刻）为锚；轮询惰性强结（设计 §3.3）。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Protocol

from app.config import Settings, get_settings
from app.services.call_store import CallStore
from app.services.lang_ctx import L

_REFUND_SUMMARY_TMPL = (
    "通话分钟为预付费虚拟权益：通话开始后按分钟消耗；提前挂断退回未用"
    "整分钟；下单未接通（{timeout} 秒无人接听）全额原路退回；到点自动结束"
    "不退当次已选时长中已消耗部分。"
)

_REFUND_SUMMARY_TMPL_EN = (
    "Call minutes are prepaid credits: minutes are consumed once the call "
    "starts; hanging up early refunds unused whole minutes; if no one "
    "answers within {timeout} seconds you get a full refund to your "
    "original payment method; minutes already used are non-refundable when "
    "the call ends at its scheduled time."
)


class CallError(Exception):
    """业务错误：API 层翻译为 HTTPException(status_code, detail)。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# -- 收款网关协议（MVP mock；alipay/stripe 门控 stub） ------------------------


class CallPaymentGateway(Protocol):
    """网关只做一件事：把订单变成「如何付款」的指令。

    返回 {"type": "mock_confirm"}（dev 一键确认）或
    {"type": "redirect", "url": ...}（hosted checkout）。
    """

    name: str

    def create_payment(self, order: dict) -> dict: ...


class MockGateway:
    """dev 零网络网关：返回 mock_confirm 指令，由 /orders/{id}/confirm 模拟回调。

    三网关统一 `__init__(settings)` 构造（get_gateway 工厂约定）。
    """

    name = "mock"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_payment(self, order: dict) -> dict:
        return {"type": "mock_confirm"}


class AlipayWapGateway:
    """支付宝手机网站支付 stub：签约键配齐才可用（个体工商户可办）。"""

    name = "alipay"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_payment(self, order: dict) -> dict:
        keys = (
            self._settings.alipay_app_id,
            self._settings.alipay_private_key,
            self._settings.alipay_alipay_public_key,
        )
        if not all(keys):
            raise CallError(503, "provider_not_configured")
        raise CallError(503, "provider_not_implemented")  # 签约后实装 wap 表单跳转


class StripeCheckoutGateway:
    """Stripe hosted Checkout stub：外卡主通道，需境外主体 + 键（与付款层共用）。"""

    name = "stripe"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_payment(self, order: dict) -> dict:
        if not self._settings.stripe_api_key:
            raise CallError(503, "provider_not_configured")
        raise CallError(503, "provider_not_implemented")  # 接线时走付款层 checkout


def get_gateway(settings: Settings) -> CallPaymentGateway:
    return {
        "mock": MockGateway,
        "alipay": AlipayWapGateway,
        "stripe": StripeCheckoutGateway,
    }[settings.call_provider](settings)


# -- 服务 ---------------------------------------------------------------------


class CallService:
    def __init__(self, store: CallStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings
        self.gateway = get_gateway(settings)

    # -- 套餐与余额 -----------------------------------------------------------

    def refund_summary(self) -> str:
        return L(_REFUND_SUMMARY_TMPL, _REFUND_SUMMARY_TMPL_EN).format(
            timeout=self.settings.call_waiting_timeout_seconds
        )

    def packages(self) -> dict:
        raw = json.loads(self.settings.call_packages_json)
        if not isinstance(raw, list) or not raw:
            raise CallError(500, "bad_call_packages_config")
        out = []
        for p in raw:
            try:
                out.append(
                    {
                        "code": str(p["code"]),
                        "minutes": int(p["minutes"]),
                        "price_cny": float(p["price_cny"]),
                        "price_usd": float(p["price_usd"]),
                    }
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CallError(500, "bad_call_packages_config") from exc
        return {
            "packages": out,
            "min_minutes": self.settings.call_min_minutes,
            "max_minutes": self.settings.call_max_minutes,
            "provider": self.settings.call_provider,
            "hotline": self.settings.call_hotline_number,
            "direct_dial_enabled": bool(self.settings.call_hotline_number),
        }

    def _package(self, code: str) -> dict:
        for p in self.packages()["packages"]:
            if p["code"] == code:
                return p
        raise CallError(422, "unknown_package")

    def balance(self, device_id: str) -> int:
        return self.store.balance(device_id)

    # -- 购买流（§7.1） --------------------------------------------------------

    def create_order(
        self, device_id: str, username: str | None, package_code: str, currency: str
    ) -> dict:
        pkg = self._package(package_code)
        if currency == "cny":
            amount = pkg["price_cny"]
        elif currency == "usd":
            amount = pkg["price_usd"]
        else:
            raise CallError(422, "unknown_currency")
        order = self.store.create_order(
            device_id,
            username,
            pkg["code"],
            pkg["minutes"],
            currency,
            amount,
            self.settings.call_provider,
            self.refund_summary(),
        )
        pay = self.gateway.create_payment(order)
        return {
            "order_id": order["id"],
            "status": order["status"],
            "minutes": order["minutes"],
            "currency": order["currency"],
            "amount_yuan": order["amount_yuan"],
            "pay": pay,
            "refund_summary": order["refund_summary"],
        }

    def mock_confirm(self, device_id: str, order_id: str) -> dict:
        """dev 专用：模拟网关回调成功（call_provider != mock 时 403）。"""
        if self.settings.call_provider != "mock":
            raise CallError(403, "mock_only")
        order = self.store.get_order(order_id)
        if order is None or order["device_id"] != device_id:
            raise CallError(404, "order_not_found")
        if order["status"] == "created":
            self.store.mark_order_paid(order_id, f"mock-{order_id}")
        return self._order_result(order_id, device_id)

    def handle_webhook(self, provider: str, payload: dict) -> dict:
        """网关回调。MVP 仅 mock 渠道（dev webhook 透传 order_id）；真实渠道
        实装时在此验签 + 按 provider_ref 找单（幂等由 mark_order_paid 保证）。
        """
        if provider != self.settings.call_provider:
            raise CallError(503, "provider_not_configured")
        if provider != "mock":
            raise CallError(503, "provider_not_implemented")
        order_id = str(payload.get("order_id") or "")
        if not order_id or self.store.get_order(order_id) is None:
            raise CallError(404, "order_not_found")
        ref = str(payload.get("provider_ref") or f"mock-{order_id}")
        self.store.mark_order_paid(order_id, ref)
        return {"received": True, "order_id": order_id}

    def _order_result(self, order_id: str, device_id: str) -> dict:
        order = self.store.get_order(order_id)
        assert order is not None  # 调用方已校验
        return {
            "order_id": order_id,
            "status": order["status"],
            "minutes": order["minutes"],
            "balance": self.store.balance(device_id),
        }

    # -- 通话流（§7.2） --------------------------------------------------------

    def create_session(
        self,
        device_id: str,
        username: str | None,
        duration_minutes: int,
        mode: str = "direct",
        phone: str | None = None,
    ) -> dict:
        cfg = self.settings
        if mode not in ("direct", "callback"):
            raise CallError(422, "unknown_mode")
        lo, hi = cfg.call_min_minutes, cfg.call_max_minutes
        if (
            not isinstance(duration_minutes, int)
            or duration_minutes < lo
            or duration_minutes > hi
            or duration_minutes % lo != 0
        ):
            raise CallError(422, "invalid_duration")
        if mode == "direct" and not cfg.call_hotline_number:
            # 直拨未配置热线：客户端应降级为 callback（设计 §12）
            raise CallError(422, "hotline_not_configured")
        if mode == "callback" and not (phone or "").strip():
            raise CallError(422, "phone_required")
        if self.store.balance(device_id) < duration_minutes:
            raise CallError(402, "insufficient_minutes")
        session = self.store.create_session(
            device_id, username, (phone or "").strip() or None, mode, duration_minutes
        )
        if not self.store.try_consume(
            device_id, username, duration_minutes, session_id=session["id"]
        ):
            self.store.update_session(
                session["id"], status="failed", end_reason="error"
            )
            raise CallError(402, "insufficient_minutes")
        out = dict(session)
        out["session_id"] = session["id"]  # API 视角统一叫 session_id
        out["balance"] = self.store.balance(device_id)
        if mode == "direct":
            out["dial"] = {"type": "tel", "number": cfg.call_hotline_number}
        return out

    def _parse(self, ts: str | None) -> datetime | None:
        return datetime.fromisoformat(ts) if ts else None

    def poll_session(self, session_id: str, device_id: str | None = None) -> dict:
        """旅客轮询（device_id 校验归属）。内含惰性强结：
        waiting 超时 → expired 全额退；active 到点 → ended(exhausted)。
        """
        s = self.store.get_session(session_id)
        if s is None or (device_id is not None and s["device_id"] != device_id):
            raise CallError(404, "session_not_found")
        now = datetime.now()
        if s["status"] == "waiting":
            created = self._parse(s["created_at"])
            timeout = self.settings.call_waiting_timeout_seconds
            if created and (now - created).total_seconds() > timeout:
                s = self._end(
                    s, status="expired", reason="timeout", refund=s["granted_minutes"]
                )
        elif s["status"] == "active":
            started = self._parse(s["started_at"])
            granted_secs = s["granted_minutes"] * 60
            elapsed = int((now - started).total_seconds()) if started else 0
            consumed = max(s["consumed_seconds"], min(elapsed, granted_secs))
            if elapsed >= granted_secs:
                s = self._end(
                    s,
                    status="ended",
                    reason="exhausted",
                    refund=0,
                    consumed=granted_secs,
                )
            elif consumed != s["consumed_seconds"]:
                s = self.store.update_session(session_id, consumed_seconds=consumed)
        return self._session_view(s)

    def end_session(self, session_id: str, device_id: str, by: str = "user") -> dict:
        s = self.store.get_session(session_id)
        if s is None or s["device_id"] != device_id:
            raise CallError(404, "session_not_found")
        if s["status"] in ("ended", "expired", "failed"):
            return self._session_view(s)  # 幂等
        if s["status"] == "waiting":
            s = self._end(s, status="ended", reason=by, refund=s["granted_minutes"])
            return self._session_view(s)
        # active：按实际用时退整分钟
        started = self._parse(s["started_at"])
        granted_secs = s["granted_minutes"] * 60
        consumed = (
            min(int((datetime.now() - started).total_seconds()), granted_secs)
            if started
            else 0
        )
        refund = (granted_secs - consumed) // 60
        s = self._end(s, status="ended", reason=by, refund=refund, consumed=consumed)
        return self._session_view(s)

    def _end(
        self,
        s: dict,
        *,
        status: str,
        reason: str,
        refund: int,
        consumed: int | None = None,
    ) -> dict:
        updates: dict = {
            "status": status,
            "end_reason": reason,
            "ended_at": datetime.now().isoformat(timespec="seconds"),
            "refund_minutes": refund,
        }
        if consumed is not None:
            updates["consumed_seconds"] = consumed
        if refund > 0:
            self.store.add_entry(
                s["device_id"],
                s["username"],
                refund,
                "refund",
                session_id=s["id"],
                note=f"end_reason={reason}",
            )
        return self.store.update_session(s["id"], **updates)

    def _session_view(self, s: dict) -> dict:
        granted_secs = s["granted_minutes"] * 60
        remaining = max(0, granted_secs - s["consumed_seconds"])
        view = {
            "session_id": s["id"],
            "status": s["status"],
            "mode": s["mode"],
            "granted_minutes": s["granted_minutes"],
            "consumed_seconds": s["consumed_seconds"],
            "remaining_seconds": remaining,
            "refund_minutes": s["refund_minutes"],
            "started_at": s["started_at"],
            "ended_at": s["ended_at"],
            "end_reason": s["end_reason"],
            "agent": s["agent"],
            "created_at": s["created_at"],
        }
        if s["mode"] == "direct":
            view["dial"] = {"type": "tel", "number": self.settings.call_hotline_number}
        else:
            view["phone"] = s["phone"]
        return view

    # -- 坐席台（§7.3） ---------------------------------------------------------

    def agent_queue(self) -> dict:
        items = self.store.list_agent_queue()
        now = datetime.now()
        for it in items:
            created = self._parse(it["created_at"])
            it["wait_seconds"] = int((now - created).total_seconds()) if created else 0
        return {
            "sessions": items,
            "hotline": self.settings.call_hotline_number,
        }

    def agent_answer(self, session_id: str, agent: str) -> dict:
        s = self.store.get_session(session_id)
        if s is None:
            raise CallError(404, "session_not_found")
        if s["status"] == "expired":
            raise CallError(409, "session_expired")
        if s["status"] != "waiting":
            raise CallError(409, "invalid_state")
        s = self.store.update_session(
            session_id,
            status="active",
            agent=agent,
            started_at=datetime.now().isoformat(timespec="seconds"),
            consumed_seconds=0,
        )
        return self._session_view(s)

    def agent_end(self, session_id: str) -> dict:
        s = self.store.get_session(session_id)
        if s is None:
            raise CallError(404, "session_not_found")
        if s["status"] == "active":
            granted_secs = s["granted_minutes"] * 60
            started = self._parse(s["started_at"])
            consumed = (
                min(int((datetime.now() - started).total_seconds()), granted_secs)
                if started
                else 0
            )
            refund = (granted_secs - consumed) // 60
            s = self._end(
                s, status="ended", reason="agent", refund=refund, consumed=consumed
            )
        return self._session_view(s)

    # -- 记录与认领 -------------------------------------------------------------

    def records(self, device_id: str) -> dict:
        sessions = []
        for s in self.store.list_sessions(device_id):
            view = self._session_view(s)
            view["duration_label"] = (
                f"{s['consumed_seconds'] // 60:02d}:{s['consumed_seconds'] % 60:02d}"
            )
            sessions.append(view)
        return {
            "sessions": sessions,
            "orders": self.store.list_orders(device_id),
            "balance": self.store.balance(device_id),
        }

    def claim_device(self, device_id: str, username: str) -> dict:
        return {"claimed": self.store.claim_device(device_id, username)}


# -- 进程级单例（照 trip_items.py lazy singleton 模式） -----------------------

_service: CallService | None = None


def get_call_service() -> CallService:
    global _service
    if _service is None:
        _service = CallService(CallStore(get_settings().call_db_url), get_settings())
    return _service
