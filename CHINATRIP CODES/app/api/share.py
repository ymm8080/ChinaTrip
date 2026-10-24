"""Trip-share routes (2026-10-23): owner-side toggle + public read-only.

Three surfaces, one token:
  * POST /api/v1/itineraries/{id}/share   — owner-only on/off switch
  * GET  /api/v1/public/trips/{token}     — sanitized JSON for the H5
    read-only view (whitelist payload, never owner/account fields)
  * GET  /s/{token}                       — OG card HTML for chat-app
    link previews + JS redirect to the H5 view (same page for every UA)

Anti-enumeration: 128-bit random tokens; unknown / disabled / revoked
answer the identical 404. Anti-crawler: every public route passes a
second, IP-keyed tight limiter on top of the global middleware, and the
OG page is noindex (robots.txt still allows /s/ so card bots render).
"""

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from app.api.itineraries import (
    _account_from_auth,
    _owned_record,
    _require_device,
    get_store,
)
from app.config import get_settings
from app.middleware.ratelimit import RateLimiter
from app.services.itinerary_store import ItineraryRecord, ItineraryStore
from app.services.trip_share import (
    og_share_html,
    public_trip_payload,
    share_enabled_record,
)

router = APIRouter(tags=["trip-share"])
logger = logging.getLogger(__name__)


class ShareToggleRequest(BaseModel):
    enabled: bool


# --- per-IP tight limiter for the public surfaces ----------------------------

_limiter_singleton: RateLimiter | None = None


def _public_limiter() -> RateLimiter:
    global _limiter_singleton
    if _limiter_singleton is None:
        settings = get_settings()
        _limiter_singleton = RateLimiter(
            per_minute=settings.share_public_rate_per_minute,
            per_hour=settings.share_public_rate_per_hour,
        )
    return _limiter_singleton


def reset_public_limiter_for_tests() -> None:
    global _limiter_singleton
    _limiter_singleton = None


async def public_rate_guard(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    result = _public_limiter().check(f"share:{client_ip}")
    if not result.allowed:
        raise HTTPException(
            status_code=429,
            detail="rate_limited",
            headers={"Retry-After": str(result.retry_after)},
        )


# --- owner-side toggle --------------------------------------------------------


def _share_state(record: ItineraryRecord) -> dict:
    return {
        "itinerary_id": record.itinerary_id,
        "share_enabled": record.share_enabled,
        # Token only while sharing is on: an off state must not hand the
        # (still valid) token back to a device that lost ownership meanwhile.
        "share_token": record.share_token if record.share_enabled else None,
    }


@router.post("/api/v1/itineraries/{itinerary_id}/share")
async def toggle_trip_share(
    itinerary_id: str,
    request: ShareToggleRequest,
    x_device_id: str | None = Header(default=None, alias="X-Device-ID"),
    store: ItineraryStore = Depends(get_store),
    account: str | None = Depends(_account_from_auth),
) -> dict:
    device = _require_device(x_device_id)
    record = _owned_record(store, itinerary_id, device, account)
    if request.enabled:
        # Idempotent: first enable mints the token, re-enabling (e.g. the
        # 复制链接 button) returns the same link without rotating it.
        share_enabled_record(record)
    else:
        # Token is kept so re-enabling restores the same link; flipping
        # off immediately 404s every public surface (find_by_share_token
        # filters on share_enabled).
        record.share_enabled = False
    store.put(record)
    return _share_state(record)


# --- public read-only surfaces -------------------------------------------------


@router.get("/api/v1/public/trips/{token}", dependencies=[Depends(public_rate_guard)])
async def get_public_trip(
    token: str, store: ItineraryStore = Depends(get_store)
) -> dict:
    record = store.find_by_share_token(token)
    if record is None:
        # Same 404 body whether the token never existed, sharing is off,
        # or the trip was deleted — no oracle for token validity.
        raise HTTPException(status_code=404, detail="not_found")
    return public_trip_payload(record)


@router.get("/s/{token}", dependencies=[Depends(public_rate_guard)])
async def share_landing(
    token: str, request: Request, store: ItineraryStore = Depends(get_store)
) -> HTMLResponse:
    record = store.find_by_share_token(token)
    if record is None:
        raise HTTPException(status_code=404, detail="not_found")
    base = str(request.base_url).rstrip("/")
    html = og_share_html(token, record.plan, og_image_url=f"{base}/h5/og-default.png")
    return HTMLResponse(
        html,
        headers={
            "Cache-Control": "no-store",
            "X-Robots-Tag": "noindex, nofollow",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.get("/robots.txt", include_in_schema=False)
async def robots_txt() -> PlainTextResponse:
    # /s/ stays allowed: Twitterbot et al. must fetch it to render link
    # cards (noindex headers keep search engines from indexing trips).
    return PlainTextResponse("User-agent: *\nDisallow: /api/\n")
