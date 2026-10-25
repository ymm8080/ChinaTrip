"""Public trip-share payload + OG card HTML (2026-10-23).

Pure logic, no HTTP imports: the API layer (app.api.share) calls
``new_share_token`` / ``public_trip_payload`` / ``og_share_html``.

Anti-enumeration: tokens are 128-bit urlsafe random (secrets), unrelated
to itinerary_id; unknown / disabled / revoked all answer the same 404.

Anti-scrape: the OG page carries only counts ("3 天 · 12 站") — no
itinerary content, no user free-text (the plan model has no title/note
that reaches this path) — so the preview bot learns nothing a card
doesn't need, and everything rendered is html.escape'd anyway.
"""

import html
import secrets

from app.services.itinerary.models import ItineraryPlan, VisitItem
from app.services.itinerary_store import ItineraryRecord
from app.services.lang_ctx import L, is_en

# /s/{token} always serves the same HTML to every User-Agent: chat-app
# crawlers (WeChat/WhatsApp/Twitter/Telegram) don't run JS and read the
# OG tags, real browsers immediately location.replace() to the H5 view.
# UA sniffing is deliberately absent — WeChat's in-app browser and its
# card crawler share UA families and misclassification is unfixable.

# Public payload whitelist (model_dump(include=...)): location/address/
# hours are public POI data; everything owner-related (device_id,
# account, snapshots, sync versions, poi/item internal ids, pinned) and
# anything not listed never leaves the server.
_VISIT_FIELDS = {
    "name",
    "category",
    "city",
    "address",
    "opening_hours",
    "day",
    "start_time",
    "end_time",
    "duration_minutes",
    "location",
    "distance_to_next_km",
    "next_walk_minutes",
}
_TRANSFER_FIELDS = {
    "day",
    "seq",
    "from_city",
    "to_city",
    "mode",
    "start_time",
    "end_time",
    "duration_minutes",
    "train_no",
}


def new_share_token() -> str:
    """128 bits of entropy: guessing one valid token is infeasible."""
    return secrets.token_urlsafe(16)


def share_enabled_record(record: ItineraryRecord) -> ItineraryRecord:
    """Idempotently turn sharing on, minting a token on first enable."""
    if not record.share_enabled:
        record.share_enabled = True
    if record.share_token is None:
        record.share_token = new_share_token()
    return record


def trip_title(plan: ItineraryPlan) -> str:
    cities = " → ".join(plan.cities) if plan.cities else L("我的行程", "My Trip")
    return f"{cities} · " + L(f"{len(plan.days)}天行程", f"{len(plan.days)}-Day Trip")


def public_trip_payload(record: ItineraryRecord) -> dict:
    """Read-only view of the working plan, whitelist-projected."""
    plan = record.plan
    days = []
    stops = 0
    for day in plan.days:
        items = []
        for item in day.items:
            if isinstance(item, VisitItem):
                fields = _VISIT_FIELDS
                kind = "visit"
                stops += 1
            else:
                fields = _TRANSFER_FIELDS
                kind = "transfer"
            payload = item.model_dump(include=fields)
            payload["kind"] = kind
            items.append(payload)
        days.append({"day": day.day, "base_city": day.base_city, "items": items})
    return {
        "title": trip_title(plan),
        "cities": list(plan.cities),
        "days_count": len(plan.days),
        "stops_count": stops,
        "days": days,
        "updated_at": record.updated_at,
    }


def og_share_html(token: str, plan: ItineraryPlan, og_image_url: str) -> str:
    """The one page /s/{token} serves. Everything dynamic is escaped;
    counts-only description keeps scrapers empty-handed."""
    title = html.escape(trip_title(plan), quote=True)
    stops = sum(len(d.items) for d in plan.days)
    description = html.escape(
        L(
            f"共 {len(plan.days)} 天 · {stops} 个行程点 · 来自 ChinaTrip 行程助手",
            f"{len(plan.days)} days · {stops} stops · ChinaTrip Trip Planner",
        ),
        quote=True,
    )
    target = html.escape(f"/h5/?share={token}", quote=True)
    image = html.escape(og_image_url, quote=True)
    page_lang = "en" if is_en() else "zh-CN"
    return (
        f'<!doctype html><html lang="{page_lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        '<meta property="og:type" content="website">'
        f'<meta property="og:title" content="{title}">'
        f'<meta property="og:description" content="{description}">'
        f'<meta property="og:image" content="{image}">'
        '<meta name="twitter:card" content="summary_large_image">'
        f'<script>location.replace("{target}")</script>'
        f'<noscript><meta http-equiv="refresh" content="0;url={target}"></noscript>'
        "</head><body>"
        f"<p>{L('正在打开行程… ', 'Opening your trip… ')}"
        f'<a href="{target}">{L("点此进入", "Tap to open")}</a></p>'
        "</body></html>"
    )
