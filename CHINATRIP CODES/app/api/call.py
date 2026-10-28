"""真人通话咨询端点（DESIGN/paid_call_service_design_2026-10-25 §8）。

身份：X-Device-ID 必带（匿名单轨；username 字段留账本归属，MVP 不解析
Bearer）。坐席端点以 X-Agent-Key 共享密钥护门——未配置 = 整体 503
（agent_disabled），配错 = 401（agent_key_invalid）。
"""

from functools import wraps

from fastapi import APIRouter, Body, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.call_service import CallError, CallService, get_call_service

router = APIRouter(prefix="/api/v1/call", tags=["call"])


def _svc() -> CallService:
    return get_call_service()


def _device(x_device_id: str | None) -> str:
    if not x_device_id:
        raise HTTPException(status_code=422, detail="device_id_required")
    return x_device_id


def _agent(x_agent_key: str | None) -> None:
    key = get_settings().agent_console_key
    if not key:
        raise HTTPException(status_code=503, detail="agent_disabled")
    if x_agent_key != key:
        raise HTTPException(status_code=401, detail="agent_key_invalid")


def _wrap(fn):
    """CallError → HTTPException 统一翻译。"""

    @wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except CallError as exc:
            raise HTTPException(
                status_code=exc.status_code, detail=exc.detail
            ) from None

    return inner


class OrderRequest(BaseModel):
    package_code: str = Field(min_length=1, max_length=40)
    currency: str = Field(default="cny", pattern="^(cny|usd)$")


class SessionRequest(BaseModel):
    duration_minutes: int = Field(ge=1, le=240)
    mode: str = Field(default="direct", pattern="^(direct|callback)$")
    phone: str | None = Field(default=None, max_length=30)


# -- 旅客端 --------------------------------------------------------------------


@router.get("/packages")
@_wrap
def packages() -> dict:
    return _svc().packages()


@router.get("/balance")
@_wrap
def balance(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> dict:
    return {"minutes": _svc().balance(_device(x_device_id))}


@router.post("/orders", status_code=201)
@_wrap
def create_order(
    body: OrderRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> dict:
    return _svc().create_order(
        _device(x_device_id), None, body.package_code, body.currency
    )


@router.post("/orders/{order_id}/confirm")
@_wrap
def confirm_order(
    order_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> dict:
    """仅 mock 后端可用（真实网关走 webhook），模拟回调成功。"""
    return _svc().mock_confirm(_device(x_device_id), order_id)


@router.post("/webhooks/{provider}")
@_wrap
def webhook(provider: str, payload: dict = Body(...)) -> dict:
    return _svc().handle_webhook(provider, payload)


@router.get("/records")
@_wrap
def records(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> dict:
    return _svc().records(_device(x_device_id))


@router.post("/sessions", status_code=201)
@_wrap
def create_session(
    body: SessionRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> dict:
    return _svc().create_session(
        _device(x_device_id), None, body.duration_minutes, body.mode, body.phone
    )


@router.get("/sessions/{session_id}")
@_wrap
def poll_session(
    session_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> dict:
    """轮询：内含服务端惰性强结（waiting 超时 / active 到点）。"""
    return _svc().poll_session(session_id, _device(x_device_id))


@router.post("/sessions/{session_id}/end")
@_wrap
def end_session(
    session_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
) -> dict:
    return _svc().end_session(session_id, _device(x_device_id), by="user")


# -- 坐席台（X-Agent-Key 护门） ---------------------------------------------------


@router.get("/agent/queue")
@_wrap
def agent_queue(
    x_agent_key: str | None = Header(default=None, alias="X-Agent-Key"),
) -> dict:
    _agent(x_agent_key)
    return _svc().agent_queue()


@router.post("/agent/sessions/{session_id}/answer")
@_wrap
def agent_answer(
    session_id: str,
    x_agent_key: str | None = Header(default=None, alias="X-Agent-Key"),
    x_agent_name: str | None = Header(default=None, alias="X-Agent-Name"),
) -> dict:
    _agent(x_agent_key)
    return _svc().agent_answer(session_id, x_agent_name or "agent")


@router.post("/agent/sessions/{session_id}/end")
@_wrap
def agent_end(
    session_id: str,
    x_agent_key: str | None = Header(default=None, alias="X-Agent-Key"),
) -> dict:
    _agent(x_agent_key)
    return _svc().agent_end(session_id)
