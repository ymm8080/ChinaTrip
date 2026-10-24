"""Itinerary CRUD + snapshot version API (design v2.0 §5.4/§6.8).

Every route requires X-Device-ID. Cross-owner access answers 404 (not
403) so foreign itinerary ids cannot be enumerated. The router is NOT
registered in app/main.py — the orchestrator wires it.
"""

import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services import trip_export
from app.services.accounts import AccountService, parse_bearer_token
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.itinerary import DiffOp, PipelineError, PoiHours
from app.services.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryRecord,
    ItineraryService,
    ItineraryStore,
    QuotaExceededError,
)
from app.services.mailer import get_mailer
from app.services.state_persist import (
    PersistentItineraryStore,
    db_path_from_url,
    get_state_backend,
)

router = APIRouter(prefix="/api/v1", tags=["itineraries"])
logger = logging.getLogger(__name__)


class CreateItineraryRequest(BaseModel):
    cities: list[str] = Field(min_length=1)
    days: int = Field(ge=1)


class MutateItineraryRequest(BaseModel):
    diffs: list[DiffOp]
    poi_hours: list[PoiHours] = Field(default_factory=list)


class CreateSnapshotRequest(BaseModel):
    name: str | None = None
    note: str | None = None


# --- dependency factories (process-level singletons, translate.py pattern) ---

_store_singleton: InMemoryItineraryStore | None = None
_entitlement_singleton: EntitlementService | None = None
_account_service_singleton: AccountService | None = None


def get_store() -> ItineraryStore:
    """Process-wide persistent singleton: itinerary state must survive
    across requests AND across uvicorn restarts (write-through SQLite)."""
    global _store_singleton
    if _store_singleton is None:
        settings = get_settings()
        _store_singleton = PersistentItineraryStore(
            get_state_backend(db_path_from_url(settings.state_db_url))
        )
    return _store_singleton


def get_entitlement_service() -> EntitlementService:
    """Process-wide singleton: quota counters must be shared across
    requests or the snapshot cap would never trigger. rules=[] = default
    free policy (§6.8 ⑥); offers get configured in the rule table later."""
    global _entitlement_singleton
    if _entitlement_singleton is None:
        _entitlement_singleton = EntitlementService(
            store=InMemoryQuotaStore(), rules=[]
        )
    return _entitlement_singleton


def get_account_service() -> AccountService:
    """Process-wide singleton: account rows live in the same SQLite file
    as the itinerary store, and claiming must mutate the SAME in-memory
    store instance the routes use — hence built on ``get_store()``. The
    factory lives here (not in api/auth.py) so auth.py can import it
    without a circular import."""
    global _account_service_singleton
    if _account_service_singleton is None:
        _account_service_singleton = AccountService(
            get_state_backend(db_path_from_url(get_settings().state_db_url)),
            get_store(),
            mailer=get_mailer(),
        )
    return _account_service_singleton


def get_itinerary_service(
    store: ItineraryStore = Depends(get_store),
) -> ItineraryService:
    # Stateless wrapper; all persistent state lives in the store singleton.
    return ItineraryService(store)


# --- helpers -----------------------------------------------------------------


def _require_device(x_device_id: str | None) -> str:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    return x_device_id


def _account_from_auth(
    authorization: str | None = Header(default=None),
    service: AccountService = Depends(get_account_service),
) -> str | None:
    """Bearer token -> username, or None. Anonymous/invalid tokens stay
    anonymous — the device-scoped behavior is untouched."""
    token = parse_bearer_token(authorization)
    if token is None:
        return None
    return service.verify_token(token)


def _owned_record(
    store: ItineraryStore,
    itinerary_id: str,
    owner_device_id: str,
    account: str | None = None,
) -> ItineraryRecord:
    record = store.get(itinerary_id)
    # 404 for foreign owners too — never confirm someone else's id exists.
    # Logged-in accounts also own itineraries claimed by/created for them,
    # regardless of which device made them.
    if record is None:
        raise HTTPException(status_code=404, detail="itinerary_not_found")
    if record.owner_device_id != owner_device_id and not (
        account is not None and record.owner_account_id == account
    ):
        raise HTTPException(status_code=404, detail="itinerary_not_found")
    return record


def _summary(record: ItineraryRecord) -> dict:
    # 行程生成时间（2026-10-20）：created_at 为 None 的存量旧记录回退到
    # 最早快照的 created_at（记录里唯一真实历史时间戳），都没有则 None。
    created_at = record.created_at
    if created_at is None and record.snapshots:
        created_at = min(s.created_at for s in record.snapshots)
    # 更新时间（2026-10-20）：随保存/变更/恢复刷新；旧记录回退创建时间。
    updated_at = record.updated_at or record.created_at or created_at
    return {
        "itinerary_id": record.itinerary_id,
        "working_sync_version": record.working_sync_version,
        "cities": record.plan.cities,
        "active_snapshot_id": record.active_snapshot_id,
        "snapshot_count": len(record.snapshots),
        "created_at": created_at,
        "updated_at": updated_at,
        "share_enabled": record.share_enabled,
    }


# --- routes ------------------------------------------------------------------


@router.post("/itineraries", status_code=201)
async def create_itinerary(
    request: CreateItineraryRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    device = _require_device(x_device_id)
    record = service.create(device, request.cities, days_count=request.days)
    if account is not None:
        # Logged-in: the new itinerary belongs to the account immediately,
        # so it shows up on every device of that account.
        record.owner_account_id = account
        store.put(record)
    return _summary(record)


@router.get("/itineraries")
async def list_itineraries(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> list[dict]:
    device = _require_device(x_device_id)
    if account is not None:
        return [_summary(r) for r in store.list_by_account(account)]
    return [_summary(r) for r in store.list_by_owner(device)]


@router.get("/itineraries/{itinerary_id}")
async def get_itinerary(
    itinerary_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> ItineraryRecord:
    device = _require_device(x_device_id)
    return _owned_record(store, itinerary_id, device, account)


@router.put("/itineraries/{itinerary_id}")
async def mutate_itinerary(
    itinerary_id: str,
    request: MutateItineraryRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    try:
        record, report, summary = service.mutate(
            record, request.diffs, poi_hours=request.poi_hours
        )
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail="invalid_diff") from exc
    if not report.ok:
        # Error-severity violation: version untouched, caller must repair.
        raise HTTPException(status_code=422, detail=report.model_dump())
    return {
        "record": _summary(record),
        "validation": report.model_dump(),
        "change_summary": summary.model_dump(),
    }


@router.post("/itineraries/{itinerary_id}/snapshots", status_code=201)
async def create_snapshot(
    itinerary_id: str,
    request: CreateSnapshotRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    entitlement: EntitlementService = Depends(get_entitlement_service),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    try:
        snapshot = service.create_snapshot(
            record,
            name=request.name,
            note=request.note,
            entitlement=entitlement,
            subject_id=device,
        )
    except QuotaExceededError as exc:
        # §6.8: the client PaywallGate reports this trigger and we answer
        # with the same trigger so the gate can match an offer client-side.
        raise HTTPException(
            status_code=402,
            detail={
                "denied_reason": exc.denied_reason or "quota_exhausted",
                "paywall_trigger": exc.paywall_trigger,
            },
        ) from exc
    return snapshot.model_dump(exclude={"plan"})


@router.get("/itineraries/{itinerary_id}/snapshots")
async def list_snapshots(
    itinerary_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> list[dict]:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    return [s.model_dump(exclude={"plan"}) for s in record.snapshots]


@router.post("/itineraries/{itinerary_id}/snapshots/{snapshot_id}/restore")
async def restore_snapshot(
    itinerary_id: str,
    snapshot_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
    account: str | None = Depends(_account_from_auth),
) -> ItineraryRecord:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    try:
        record = service.restore(record, snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="snapshot_not_found") from exc
    return record


@router.get("/itineraries/{itinerary_id}/export")
async def export_itinerary(
    itinerary_id: str,
    fmt: str = Query("pdf", alias="format", pattern="^(pdf|docx|xlsx)$"),
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> Response:
    """行程导出（2026-10-23，gap #2 行程的出口）：pdf = 打印 HTML（前端
    iframe 调浏览器「另存为 PDF」，TREK 零依赖方案）；docx / xlsx = 服务端
    生成二进制。鉴权与其余路由一致：跨 owner 一律 404。"""
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    filename = quote(trip_export.safe_filename(record.plan))
    if fmt == "pdf":
        return HTMLResponse(
            trip_export.render_html(record.plan),
            headers={
                "Content-Disposition": f"inline; filename*=UTF-8''{filename}.html"
            },
        )
    if fmt == "docx":
        data = trip_export.render_docx(record.plan)
        media = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        data = trip_export.render_xlsx(record.plan)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=data,
        media_type=media,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename}.{fmt}"
        },
    )


@router.delete("/itineraries/{itinerary_id}", status_code=204)
async def delete_itinerary(
    itinerary_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> None:
    """Delete an owned itinerary together with its snapshots (2026-10-20:
    「行程」页 per-trip 查看/删除 buttons). Unknown / foreign-owner ids
    answer 404 like every other route (no enumeration). trip_items are
    intentionally untouched — the 行程中心 kanban is its own source of
    truth (铁律 0); deleting a trip never destroys wishlist data."""
    device = _require_device(x_device_id)
    _owned_record(store, itinerary_id, device, account)
    store.delete(itinerary_id)
