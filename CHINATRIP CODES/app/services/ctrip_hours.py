"""Ctrip sight-page opening-hours fallback (PoC, v2.4.3 备查).

User decision 2026-10-19: 携程先行. gs.ctrip.com html5 sight pages are
server-rendered and carry a structured 开放时间 field; the city sight
directory (?pageIndex=N) is server-rendered as well, which makes a
name→page discovery possible without an API.

Discipline (this is a minimal-volume screen-scraping PoC, NOT a data
partnership — the ToS-safe path is the signed 携程联盟/景点玩乐开放平台
API at W9-10):
* city slugs are a **title-verified whitelist** — wrong slugs resolve to
  a different city's page (e.g. wuhan83 lands on 宁波), so unknown cities
  degrade instead of guessing;
* the per-city name→url index is built lazily with early stop (list
  pages fetched until the POI matches, hard page caps), cached
  process-wide;
* detail pages are fetched once and cached; any failure returns None so
  the 「以现场为准」 card fallback stays intact.
"""

from __future__ import annotations

import asyncio
import re

import httpx

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_LIST_URL = "https://gs.ctrip.com/html5/you/sight/{slug}.html?pageIndex={page}"
_SITE = "https://gs.ctrip.com"

# Windowed directory fetch (2026-10-20 latency fix): list pages are
# fetched _CRAWL_WINDOW at a time and scanned in page order. The
# per-lookup budget (4) and per-city hard cap (12) are UNCHANGED —
# worst-case volume per lookup is the same; an early hit may pull up
# to window-1 extra pages once, after which the process-wide index
# cache serves everything. Concurrent fetches to gs.ctrip.com are
# capped at _FETCH_CONCURRENCY (minimal-volume PoC discipline,
# DESIGN v2.4.4 备查 2026-10-20).
_CRAWL_WINDOW = 2
_FETCH_CONCURRENCY = 2

# Title-verified slugs (a wrong slug lands on a different city's list).
CITY_SLUGS = {
    "北京": "beijing1",
    "上海": "shanghai2",
    "杭州": "hangzhou14",
    "西安": "xian7",
    "成都": "chengdu104",
    "重庆": "chongqing158",
    "广州": "guangzhou152",
    "三亚": "sanya61",
    "桂林": "guilin32",
}

_DETAIL_URL_RE = re.compile(r"/sight/[A-Za-z]+\d+/\d+\.html$")
_LIST_ENTRY_RES = [
    re.compile(r'href="([^"]*?/sight/[^"]+\.html)"[^>]*?title="([^"]{2,30})"'),
    re.compile(r'title="([^"]{2,30})"[^>]*?href="([^"]*?/sight/[^"]+\.html)"'),
]
_HOURS_RE = re.compile(r"开放时间[：:]?\s*\n+\s*([^\n]{2,120})")


def _norm_city(city: str | None) -> str:
    return (city or "").strip().removesuffix("市")


def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", "\n", html)


def parse_list(html: str) -> dict[str, str]:
    """Extract {sight_name: absolute detail_url} from a directory page."""
    entries: dict[str, str] = {}
    for rex in _LIST_ENTRY_RES:
        for m in rex.finditer(html):
            url, name = m.group(1).strip(), m.group(2).strip()
            if not _DETAIL_URL_RE.search(url):
                continue
            if url.startswith("/"):
                url = _SITE + url
            if name and name not in entries:
                entries[name] = url
    return entries


def parse_hours(html: str) -> str | None:
    m = _HOURS_RE.search(_strip_tags(html))
    return m.group(1).strip() if m else None


def match_name(index: dict[str, str], poi_name: str) -> str | None:
    """Substring match in both directions (洪崖洞 ↔ 洪崖洞民俗风貌区)."""
    key = (poi_name or "").strip()
    if not key:
        return None
    for ctrip_name, url in index.items():
        if key in ctrip_name or ctrip_name in key:
            return ctrip_name
    return None


class CtripHoursReader:
    """Lazy directory crawler with hard caps; all caches process-wide."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 8.0,
        max_pages_per_lookup: int = 4,
        max_total_pages_per_city: int = 12,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout_seconds,
            headers=_UA,
            transport=transport,
            follow_redirects=True,
        )
        self._max_pages_per_lookup = max_pages_per_lookup
        self._max_total_pages_per_city = max_total_pages_per_city
        self._index: dict[str, dict[str, str]] = {}
        self._pages_done: dict[str, int] = {}
        self._exhausted: set[str] = set()
        self._hours: dict[str, str | None] = {}
        self._misses: set[tuple[str, str]] = set()
        # Lazy loop-bound primitives: created on first use inside a
        # running loop (tests reuse a reader across asyncio.run calls;
        # never share a loop-bound semaphore/lock across loops).
        self._fetch_slots: asyncio.Semaphore | None = None
        self._city_locks: dict[str, asyncio.Lock] = {}

    async def hours_for(self, city: str, poi_name: str) -> str | None:
        slug = CITY_SLUGS.get(_norm_city(city))
        key = (_norm_city(city), (poi_name or "").strip())
        if not slug or slug in self._exhausted or key in self._misses:
            return None
        index = self._index.setdefault(slug, {})
        ctrip_name = match_name(index, poi_name)
        if ctrip_name is None:
            async with self._city_lock(slug):
                # re-check: a sibling item may have crawled while we waited
                ctrip_name = match_name(index, poi_name)
                if ctrip_name is None:
                    ctrip_name = await self._crawl_until_found(slug, poi_name)
        if ctrip_name is None:
            self._misses.add(key)
            return None
        return await self._detail_hours(index[ctrip_name])

    def _slots(self) -> asyncio.Semaphore:
        if self._fetch_slots is None:
            self._fetch_slots = asyncio.Semaphore(_FETCH_CONCURRENCY)
        return self._fetch_slots

    def _city_lock(self, slug: str) -> asyncio.Lock:
        lock = self._city_locks.get(slug)
        if lock is None:
            lock = asyncio.Lock()
            self._city_locks[slug] = lock
        return lock

    async def _fetch_page(self, slug: str, page: int) -> tuple[bool, str | None]:
        """One directory page: (False, None) = transport error (transient);
        (True, None) = non-200 (caller marks the city exhausted); else the
        page body."""
        try:
            async with self._slots():
                r = await self._client.get(_LIST_URL.format(slug=slug, page=page))
        except Exception:
            return False, None
        if r.status_code != 200:
            return True, None
        return True, r.text

    async def _crawl_until_found(self, slug: str, poi_name: str) -> str | None:
        index = self._index.setdefault(slug, {})
        budget = self._max_pages_per_lookup
        while budget > 0 and slug not in self._exhausted:
            window = min(budget, _CRAWL_WINDOW)
            first = self._pages_done.get(slug, 0) + 1
            pages = [
                p
                for p in range(first, first + window)
                if p <= self._max_total_pages_per_city
            ]
            if not pages:
                self._exhausted.add(slug)
                return None
            htmls = await asyncio.gather(*[self._fetch_page(slug, p) for p in pages])
            for page, (ok, html) in zip(pages, htmls):
                if not ok:  # transport error — transient, stop this lookup
                    return None
                if html is None:  # non-200 — treat the city as exhausted
                    self._exhausted.add(slug)
                    return None
                self._pages_done[slug] = page
                entries = parse_list(html)
                if not entries:
                    self._exhausted.add(slug)
                    return None
                index.update(entries)
                hit = match_name(index, poi_name)
                if hit is not None:
                    return hit
            budget -= window
        return None

    async def _detail_hours(self, url: str) -> str | None:
        if url in self._hours:
            return self._hours[url]
        try:
            async with self._slots():
                r = await self._client.get(url)
        except Exception:
            return None
        hours = parse_hours(r.text) if r.status_code == 200 else None
        self._hours[url] = hours
        return hours


_reader_singleton: CtripHoursReader | None = None


def get_ctrip_hours() -> CtripHoursReader:
    """Process-wide lazy singleton (translate.py pattern)."""
    global _reader_singleton
    if _reader_singleton is None:
        _reader_singleton = CtripHoursReader()
    return _reader_singleton
