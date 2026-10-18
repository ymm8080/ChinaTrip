"""Itinerary CRUD + snapshot version API (design v2.0 §5.4/§6.8).

Every route requires X-Device-ID. Cross-owner access answers 404 (not
403) so foreign itinerary ids cannot be enumerated. The router is NOT
registered in app/main.py — the orchestrator wires it.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.entitlement import EntitlementService, InMemoryQuotaStore
from app.services.itinerary import DiffOp, PipelineError, PoiHours
from app.services.itinerary_store import (
    InMemoryItineraryStore,
    ItineraryRecord,
    ItineraryService,
    ItineraryStore,
    QuotaExceededError,
)
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


def _owned_record(
    store: ItineraryStore, itinerary_id: str, owner_device_id: str
) -> ItineraryRecord:
    record = store.get(itinerary_id)
    # 404 for foreign owners too — never confirm someone else's id exists.
    if record is None or record.owner_device_id != owner_device_id:
        raise HTTPException(status_code=404, detail="itinerary_not_found")
    return record


def _summary(record: ItineraryRecord) -> dict:
    return {
        "itinerary_id": record.itinerary_id,
        "working_sync_version": record.working_sync_version,
        "cities": record.plan.cities,
        "active_snapshot_id": record.active_snapshot_id,
        "snapshot_count": len(record.snapshots),
    }


# --- routes ------------------------------------------------------------------


@router.post("/itineraries", status_code=201)
async def create_itinerary(
    request: CreateItineraryRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    service: ItineraryService = Depends(get_itinerary_service),
) -> dict:
    device = _require_device(x_device_id)
    record = service.create(device, request.cities, days_count=request.days)
    return _summary(record)


@router.get("/itineraries")
async def list_itineraries(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
) -> list[dict]:
    device = _require_device(x_device_id)
    return [_summary(r) for r in store.list_by_owner(device)]


@router.get("/itineraries/{itinerary_id}")
async def get_itinerary(
    itinerary_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
) -> ItineraryRecord:
    device = _require_device(x_device_id)
    return _owned_record(store, itinerary_id, device)


@router.put("/itineraries/{itinerary_id}")
async def mutate_itinerary(
    itinerary_id: str,
    request: MutateItineraryRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
) -> dict:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device)
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
) -> dict:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device)
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
) -> list[dict]:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device)
    return [s.model_dump(exclude={"plan"}) for s in record.snapshots]


@router.post("/itineraries/{itinerary_id}/snapshots/{snapshot_id}/restore")
async def restore_snapshot(
    itinerary_id: str,
    snapshot_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    service: ItineraryService = Depends(get_itinerary_service),
) -> ItineraryRecord:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device)
    try:
        record = service.restore(record, snapshot_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="snapshot_not_found") from exc
    return record
