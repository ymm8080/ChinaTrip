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

# --- 0009 扩展解析（DESIGN §3.1 A4/A5/A6 + §3.2 B3，真实页样本
# gs.ctrip.com Chongqing158/10377 实测 2026-10-24）---
# 评分: "4.7||/5"（标签剥离文本里 || 是空 span 分隔）
_SCORE_RE = re.compile(r"(\d\.\d)\s*\|{0,2}/\s*5")
# 点评数: "1.6万条点评" / "580条点评"（万→×10000）
_REVIEW_COUNT_RE = re.compile(r"([\d.]+)\s*(万)?\s*\|{0,2}条点评")
# 门票: "门票¥24起" / "门票¥50-80"；连字符含 U+2011 不换行连字符
_TICKET_RE = re.compile(r"门票\s*[¥￥]\s*(\d+)(?:\s*[-‑—~至]\s*[¥￥]?\s*(\d+))?")
# 建议游玩时长: "建议游玩：3-4小时" / "⏰游玩时长：3‑4小时"（榜单 AI 文本，
# 连字符变体统一字符类）；范围取中值，单值直取，分钟直接用
_DURATION_RE = re.compile(
    r"(?:建议游玩|游玩时长)\s*[：:]?\s*(\d+(?:\.\d+)?)"
    r"(?:\s*[-‑—~至]\s*(\d+(?:\.\d+)?)\s*)?(小时|分钟)"
)
# 点评标签 chips: 结构化 JSON 数组 "tagName":["亲近动物","遛娃宝藏地",...]
_TAG_NAMES_RE = re.compile(r'"tagName"\s*:\s*\[([^\]]{2,600})\]')
_TAG_ITEM_RE = re.compile(r'"([^"\\]{2,12})"')


def parse_rating(text: str) -> float | None:
    m = _SCORE_RE.search(text)
    if m is None:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v if 1.0 <= v <= 5.0 else None


def parse_rating_count(text: str) -> int | None:
    m = _REVIEW_COUNT_RE.search(text)
    if m is None:
        return None
    try:
        n = float(m.group(1))
    except ValueError:
        return None
    if m.group(2):
        n *= 10_000
    n = int(n)
    return n if 0 < n < 100_000_000 else None


def parse_ticket(html_or_text: str) -> tuple[int | None, int | None]:
    m = _TICKET_RE.search(html_or_text)
    if m is None:
        return None, None
    lo = int(m.group(1))
    hi = int(m.group(2)) if m.group(2) and int(m.group(2)) > lo else None
    return (lo, hi) if 0 < lo < 100_000 else (None, None)


def parse_duration_minutes(text: str) -> int | None:
    m = _DURATION_RE.search(text)
    if m is None:
        return None
    unit = m.group(3)
    try:
        a = float(m.group(1))
        b = float(m.group(2)) if m.group(2) else None
    except ValueError:
        return None
    value = (a + b) / 2 if b is not None else a
    minutes = int(round(value * 60)) if unit == "小时" else int(round(value))
    return minutes if 15 <= minutes <= 24 * 60 else None


def parse_review_tags(html: str) -> list[str]:
    m = _TAG_NAMES_RE.search(html)
    if m is None:
        return []
    tags = _TAG_ITEM_RE.findall(m.group(1))
    return [t for t in tags if t not in ("tagName",)][:8]


def parse_detail_fields(html: str) -> dict:
    """A4/A5/A6/B3 字段解析（纯函数，测试吃真实页片段）。

    返回键：suggested_duration_min/rating/rating_count/review_tags/
    ticket_price_min/ticket_price_max——缺失键 None/[]。
    """
    text = _strip_tags(html)
    lo, hi = parse_ticket(text)
    return {
        "suggested_duration_min": parse_duration_minutes(text),
        "rating": parse_rating(text),
        "rating_count": parse_rating_count(text),
        "review_tags": parse_review_tags(html) or None,
        "ticket_price_min": lo,
        "ticket_price_max": hi,
    }


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
        self._details: dict[str, dict | None] = {}  # url → 全字段（含 hours）
        self._misses: set[tuple[str, str]] = set()
        # Lazy loop-bound primitives: created on first use inside a
        # running loop (tests reuse a reader across asyncio.run calls;
        # never share a loop-bound semaphore/lock across loops).
        self._fetch_slots: asyncio.Semaphore | None = None
        self._city_locks: dict[str, asyncio.Lock] = {}

    async def hours_for(self, city: str, poi_name: str) -> str | None:
        """向后兼容入口（refresh_pois 既有调用）：只取开放时间。"""
        fields = await self.detail_fields_for(city, poi_name)
        return (fields or {}).get("opening_hours")

    async def detail_fields_for(self, city: str, poi_name: str) -> dict | None:
        """0009 全字段入口：开放时间 + 建议时长/评分/点评数/标签/门票。

        返回 dict（键：opening_hours/suggested_duration_min/rating/
        rating_count/review_tags/ticket_price_min/ticket_price_max，
        缺省 None）；页面拿不到时 None（调用方静默降级）。"""
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
        return await self._detail_fields(index[ctrip_name])

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

    async def _detail_fields(self, url: str) -> dict | None:
        if url in self._details:
            return self._details[url]
        try:
            async with self._slots():
                r = await self._client.get(url)
        except Exception:
            return None
        fields: dict | None = None
        if r.status_code == 200:
            hours = parse_hours(r.text)
            extras = parse_detail_fields(r.text)
            fields = {"opening_hours": hours, **extras}
        self._details[url] = fields
        return fields


_reader_singleton: CtripHoursReader | None = None


def get_ctrip_hours() -> CtripHoursReader:
    """Process-wide lazy singleton (translate.py pattern)."""
    global _reader_singleton
    if _reader_singleton is None:
        _reader_singleton = CtripHoursReader()
    return _reader_singleton
