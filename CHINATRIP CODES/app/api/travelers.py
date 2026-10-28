# -*- coding: utf-8 -*-
"""出行人资料 API（DESIGN/CLIENT_DATA_REQUIREMENTS.md，2026-10-27）。

代客预订实名档案的增删改查。隐私合规要点：列表/读取只回脱敏形
（证件号/手机号打星）；``GET /export`` 是唯一明文出口（审计留痕）；
``DELETE /api/v1/travelers`` 清空本人全部数据（被遗忘权）；
新增/修改必须 ``consent=true``（知情同意先行，PIPL §17 / GDPR Art.7）。

鉴权同 itineraries.py：X-Device-ID 必填；Bearer 登录后归属自动
从设备切到账号（owner_key = username 或 device:<id>）。
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from app.api.itineraries import _account_from_auth
from app.services.travelers import (
    InvalidTraveler,
    TravelerError,
    TravelerInput,
    TravelerNotFound,
    TravelerStore,
    consent_notice,
)
from app.services.travelers import (
    get_travelers_service as _get_travelers_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/travelers", tags=["travelers"])


def get_travelers_service():
    # 薄包装：保持 FastAPI Depends 可注入（tests 直接 monkeypatch 服务层单例）。
    return _get_travelers_service()


def _owner_key(
    x_device_id: str | None,
    account: str | None,
) -> str:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    return account if account else f"device:{x_device_id}"


def _map_error(exc: TravelerError) -> HTTPException:
    if isinstance(exc, TravelerNotFound):
        return HTTPException(status_code=404, detail="traveler_not_found")
    if isinstance(exc, InvalidTraveler):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=400, detail="traveler_error")


@router.get("")
async def list_travelers(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    account: str | None = Depends(_account_from_auth),
    service: TravelerStore = Depends(get_travelers_service),
) -> dict:
    owner = _owner_key(x_device_id, account)
    return {
        "consent_notice": consent_notice(),
        "travelers": service.list_for_owner(owner),
    }


@router.post("", status_code=201)
async def create_traveler(
    body: TravelerInput,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    account: str | None = Depends(_account_from_auth),
    service: TravelerStore = Depends(get_travelers_service),
) -> dict:
    owner = _owner_key(x_device_id, account)
    try:
        return service.create(owner, body)
    except TravelerError as exc:
        raise _map_error(exc) from exc


@router.put("/{traveler_id}")
async def update_traveler(
    traveler_id: str,
    body: TravelerInput,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    account: str | None = Depends(_account_from_auth),
    service: TravelerStore = Depends(get_travelers_service),
) -> dict:
    owner = _owner_key(x_device_id, account)
    try:
        return service.update(owner, traveler_id, body)
    except TravelerError as exc:
        raise _map_error(exc) from exc


@router.delete("/{traveler_id}", status_code=204)
async def delete_traveler(
    traveler_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    account: str | None = Depends(_account_from_auth),
    service: TravelerStore = Depends(get_travelers_service),
) -> None:
    owner = _owner_key(x_device_id, account)
    try:
        service.delete(owner, traveler_id)
    except TravelerError as exc:
        raise _map_error(exc) from exc


@router.delete("", status_code=200)
async def delete_all_travelers(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    account: str | None = Depends(_account_from_auth),
    service: TravelerStore = Depends(get_travelers_service),
) -> dict:
    """清空本人全部出行人资料（被遗忘权，PIPL §47 / GDPR Art.17）。"""
    owner = _owner_key(x_device_id, account)
    return {"deleted": service.delete_all(owner)}


@router.get("/export")
async def export_travelers(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    account: str | None = Depends(_account_from_auth),
    service: TravelerStore = Depends(get_travelers_service),
) -> JSONResponse:
    """明文导出（可携权 GDPR Art.20）；服务层写审计行（动作不写内容）。"""
    owner = _owner_key(x_device_id, account)
    data = service.export_plaintext(owner)
    return JSONResponse(
        content={"travelers": data},
        headers={"Content-Disposition": 'attachment; filename="travelers.json"'},
    )
