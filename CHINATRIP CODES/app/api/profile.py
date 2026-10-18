"""Agent memory profile + link-history API (design v2.4 §6.14 / §5 p.8).

The profile is viewable and correctable: PUT field-level merge marks every
user-touched field as manually_set so the deterministic zero-LLM distill
MVP (stand-in for the post-session async workflow) never overwrites a
human decision; each distilled write returns an applied_id and is
undoable. Link history keeps both sources re-parseable so the mainline
wishlist glue can promote them later. All state is keyed by X-Device-ID;
cross-device access answers 404 (itineraries.py convention). The routers
are NOT registered in app/main.py — the orchestrator wires them.
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.trip_items import get_trip_item_service
from app.services.profile_store import (
    LinkStore,
    LinkValidationError,
    ProfileStore,
    ProfileValidationError,
)

logger = logging.getLogger(__name__)

profile_router = APIRouter(prefix="/api/v1/profile", tags=["profile"])
links_router = APIRouter(prefix="/api/v1/links", tags=["links"])


# --- dependency factories (process-level singletons, translate.py pattern) ---

_profile_store_singleton: ProfileStore | None = None
_link_store_singleton: LinkStore | None = None


def get_profile_store() -> ProfileStore:
    """Process-wide singleton: profile state must survive across requests."""
    global _profile_store_singleton
    if _profile_store_singleton is None:
        _profile_store_singleton = ProfileStore()
    return _profile_store_singleton


def get_link_store() -> LinkStore:
    """Process-wide singleton: link history must survive across requests."""
    global _link_store_singleton
    if _link_store_singleton is None:
        _link_store_singleton = LinkStore()
    return _link_store_singleton


# --- helpers -----------------------------------------------------------------


def _require_device(x_device_id: str | None) -> str:
    if not x_device_id:
        raise HTTPException(status_code=400, detail="missing_device_id")
    return x_device_id


# --- request models ----------------------------------------------------------


class NoteInput(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    provenance: str = Field(default="user", min_length=1, max_length=64)
    added_at: str | None = Field(default=None, max_length=40)


class ProfileUpdate(BaseModel):
    # All optional: only keys present in the request body are merged
    # (model_dump(exclude_unset=True) keeps the absent-vs-null distinction).
    budget_level: str | None = None
    travel_style: list[str] | None = None
    dietary_restrictions: list[str] | None = None
    companions: str | None = None
    stamina: str | None = None
    notes: list[NoteInput] | None = None


class DistillFact(BaseModel):
    key: str = Field(min_length=1, max_length=32)
    value: str | list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: str = Field(min_length=1, max_length=64)


class DistillRequest(BaseModel):
    facts: list[DistillFact] = Field(default_factory=list, max_length=100)


class LinkCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    source: str = Field(min_length=1, max_length=32)
    origin: str | None = Field(default=None, max_length=32)
    itinerary_id: str | None = Field(default=None, max_length=64)


# --- profile routes ------------------------------------------------------------


@profile_router.get("")
async def get_profile(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ProfileStore = Depends(get_profile_store),
) -> dict:
    device = _require_device(x_device_id)
    profile, updated_at = store.get_profile(device)
    return {"profile": profile, "updated_at": updated_at}


@profile_router.put("")
async def update_profile(
    request: ProfileUpdate,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ProfileStore = Depends(get_profile_store),
) -> dict:
    device = _require_device(x_device_id)
    patch = request.model_dump(exclude_unset=True)
    try:
        profile, updated_at = store.merge(device, patch)
    except ProfileValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid_profile") from exc
    return {"profile": profile, "updated_at": updated_at}


@profile_router.post("/distill")
async def distill_profile(
    request: DistillRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ProfileStore = Depends(get_profile_store),
) -> dict:
    device = _require_device(x_device_id)
    facts = [fact.model_dump() for fact in request.facts]
    try:
        return store.distill(device, facts)
    except ProfileValidationError as exc:
        raise HTTPException(status_code=422, detail="invalid_fact") from exc


@profile_router.post("/distill/{applied_id}/undo")
async def undo_distill(
    applied_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ProfileStore = Depends(get_profile_store),
) -> dict:
    device = _require_device(x_device_id)
    try:
        profile, updated_at = store.undo(device, applied_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="applied_not_found") from None
    return {"profile": profile, "updated_at": updated_at}


# --- link history routes --------------------------------------------------------


@links_router.post("", status_code=201)
async def create_link(
    request: LinkCreate,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: LinkStore = Depends(get_link_store),
) -> dict:
    device = _require_device(x_device_id)
    try:
        return store.add_link(
            device,
            request.url,
            request.source,
            origin=request.origin,
            itinerary_id=request.itinerary_id,
        )
    except LinkValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@links_router.get("")
async def list_links(
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: LinkStore = Depends(get_link_store),
) -> list[dict]:
    device = _require_device(x_device_id)
    return store.list_links(device)


@links_router.post("/{link_id}/reparse")
async def reparse_link(
    link_id: str,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: LinkStore = Depends(get_link_store),
) -> dict:
    device = _require_device(x_device_id)
    try:
        return store.reparse(device, link_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="link_not_found") from None


class WishlistPromote(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=50)


@links_router.post("/{link_id}/to-wishlist", status_code=201)
async def promote_link_to_wishlist(
    link_id: str,
    request: WishlistPromote,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: LinkStore = Depends(get_link_store),
) -> dict:
    """个人主页「链接 → 心愿单」：跨模块胶水，写同一张 trip_items（铁律 0 同源）。"""
    device = _require_device(x_device_id)
    link = store.get_link(device, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="link_not_found")
    item = get_trip_item_service().create(
        request.name or link["url"],
        source="paste",
        itinerary_id=link.get("itinerary_id"),
        city=request.city,
        note=link["url"],
    )
    return item
