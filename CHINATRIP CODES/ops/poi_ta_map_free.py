r"""阶段 A 免费映射（0 配额）：pois 名称 → TripAdvisor location ID。

背景（2026-11-14 定调）：1000 次免费配额全部留给 GET /locations/{id}
详情拉取，名称→ID 的映射走完全免费通道。通道实测结论：

- tripadvisor.cn（猫途鹰）国内直连、无 DataDome、无验证码 ✅；
- 三类目录内部 API（页面 bundle 逆向，2026-11-14 全部 curl 实测通过）：
  * 景点  POST restapi/soa2/20405/getPCSightList
      body {geoId, pageIndex, pageSize:30, travelRanking:false,
            needSelectedFilters:true, filters:[8 槽位]}
      → verticalData[]（taSightId/displayName/displayEnName/lat/lon/
        reviewsCount）+ page.totalResultsCount；
  * 餐厅  POST restapi/soa2/21218/restaurantListForPc
      body {geoId, pageIndex, pageSize:30, sort:"RANK", needFilters:true,
            filters:[10 槽位]}
      → masterRestaurants.restaurants[]（locationId/name/commentRating/
        commentCount/address）；
  * 酒店  POST restapi/soa2/20874/hotelListForPc
      body {geoId, pageIndex, pageSize:30, sort:"RANK"}
      → hotels[]（taLocationId/name/enName/reviewRating/reviewCount/
        address）；
- www.tripadvisor.com 全球站 DataDome 403、Bing/百度/DDG 反爬——弃用；
- 城市 gID：内置已知表（北京 294212 已用 API 验证）+ 搜狗解包兜底，
  缓存 ops/ta_city_geo.json，一次一城。

选行顺序（2026-11-14 用户拍板「按 PRIORITY 顺序，不排除 HOTEL FOOD」）：
* 按 app.services.source_tier.SOURCE_PRIORITY 铁律序（curated→…→osm）
  排行，同序内 rating 高者优先；全类目参与（hotel/food 不排除）；
* 匹配池按类目路由：hotel→酒店目录、food→餐厅目录、其余→景点目录。

流程（照 fill_hours_rating_driver 纪律）：
1) 每城市解析 gID（缓存复用；解析失败=暂时性，不入台账，整城跳过）；
2) 目录翻页爬全城（缓存 ops/ta_catalog_{city}.json 断点复用，按需爬对应
   类型）；
3) 离线模糊匹配：name_zh/name_en/aliases × 目录中英文名，difflib 阈值
   0.85 写库；同城同类目贪心一一配对（一个 TA ID 只配一个 POI）；
4) 只填空回填 ta_location_id / ta_geo_id（WHERE ta_location_id IS NULL）；
5) 目录耗尽仍无匹配 = 确定性失败 → 台账 ops/poi_ta_map_missed.txt
   只试一次；引擎网络失败不入台账，整批短路。

用法：
    python ops/poi_ta_map_free.py --city 北京 --limit 50 [--dry-run]
        [--delay 0.5] [--max-pages 45] [--threshold 0.85] [--attraction-only]
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from app.db import get_session_factory  # noqa: E402
from app.models import Poi, Restaurant  # noqa: E402
from app.services.source_tier import SOURCE_PRIORITY  # noqa: E402
from ops.ta_discover_geo import PLAN_CITIES  # noqa: E402

_OPS = Path(__file__).resolve().parent
_GEO_CACHE = _OPS / "ta_city_geo.json"
_CATALOG_DIR = _OPS / "ta_catalog"
_MISS_FILE = _OPS / "poi_ta_map_missed.txt"
_RANKED_CSV = Path(
    r"D:/CHINATRIP/DESIGN/POIS DATASOURCE/chinatrip_active_ranked_pois_2026-11-14.csv"
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _UA,
    "Content-Type": "application/json",
    "Origin": "https://www.tripadvisor.cn",
    "Referer": "https://www.tripadvisor.cn/",
}
_API = "https://api.tripadvisor.cn/restapi/soa2/{svc}/{ep}"

# 已验证的城市 gID（北京用 API 反查验证过 d319086/g294212 配对）
_KNOWN_GEO = {"北京": "294212"}

# 类目路由：POI.category → 目录类型
_POOL_OF_CATEGORY = {"hotel": "hotels", "food": "restaurants"}


def _norm(s: str | None) -> str:
    """名称归一化：全角→半角、下划线→空格、去标点、小写、压缩空白。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("_", " ")
    s = re.sub(r"[^\w\u4e00-\u9fff]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip().lower()


# 分店后缀（全/半角括号段）——匹配前剥离，消除"xxx(前门店)"噪音
_BRACKET_RE = re.compile(r"[（(][^（）()]*[)）]")


def _core_name(s: str | None) -> str:
    """去括号分店段后的核心名（归一化）。"""
    return _norm(_BRACKET_RE.sub(" ", s or ""))


def _tokens(s: str | None) -> list[str]:
    """核心名切词元（≥4 字符），用于复合名（止观小馆·辽河口渔家菜）匹配。"""
    return [t for t in _core_name(s).split() if len(t) >= 4]


def _load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _load_missed() -> set[str]:
    if _MISS_FILE.exists():
        return {ln.strip() for ln in _MISS_FILE.read_text(encoding="utf-8").splitlines() if ln.strip()}
    return set()


def _append_missed(key: str) -> None:
    """key 形如 pois:<uuid> / rest:<uuid>（兼容旧无前缀行 = pois）。"""
    with _MISS_FILE.open("a", encoding="utf-8") as f:
        f.write(key + "\n")


def _is_missed(missed: set[str], table: str, row_id) -> bool:
    rid = str(row_id)
    if table == "pois":
        return rid in missed or f"pois:{rid}" in missed
    return f"rest:{rid}" in missed


# ---------------------------------------------------------------------------
# 城市 gID 解析
# ---------------------------------------------------------------------------


def _resolve_city_geo(client: httpx.Client, city: str, delay: float) -> str | None:
    """城市 → TA gID。先查内置/缓存；miss 时搜狗解包兜底并写缓存。"""
    if city in _KNOWN_GEO:
        return _KNOWN_GEO[city]
    cache = _load_json(_GEO_CACHE, {})
    if city in cache:
        return cache[city]

    q = quote(f"{city} tripadvisor 猫途鹰 Attraction_Review")
    try:
        r = client.get(
            f"https://www.sogou.com/web?query={q}",
            timeout=20.0,
            follow_redirects=True,
        )
        r.raise_for_status()
        links = re.findall(r'href="(/link\?url=[^"]+)"', r.text)[:8]
    except httpx.HTTPError as e:
        print(f"  [city-geo] 搜狗请求失败 {city}: {e}")
        return None

    for link in links:
        time.sleep(delay)
        try:
            rr = client.get(
                "https://www.sogou.com" + link, timeout=20.0, follow_redirects=True
            )
            target = str(rr.url)
            if "location.replace" in rr.text:
                m = re.search(r"window\.location\.replace\(\"([^\"]+)\"\)", rr.text)
                if m:
                    target = m.group(1)
            gids = re.findall(r"g(\d{5,8})", target)
            if gids:
                cache[city] = gids[0]
                _save_json(_GEO_CACHE, cache)
                print(f"  [city-geo] {city} → g{gids[0]}（搜狗解包）")
                return gids[0]
        except httpx.HTTPError:
            continue
    return None


# ---------------------------------------------------------------------------
# 三类目录爬取（getPCSightList / restaurantListForPc / hotelListForPc）
# ---------------------------------------------------------------------------


def _list_page(client: httpx.Client, kind: str, gid: str, page: int) -> dict:
    """kind: attractions | restaurants | hotels。"""
    if kind == "attractions":
        body = {
            "geoId": int(gid),
            "pageIndex": page,
            "pageSize": 30,
            "travelRanking": False,
            "needSelectedFilters": True,
            "filters": [{"type": t, "param": ""} for t in (
                "subcategory", "subtype", "neighborhood", "travelerRating",
                "awards", "waypointairport", "waypointstation", "other",
            )],
        }
        ep = "20405/getPCSightList"
    elif kind == "restaurants":
        body = {
            "geoId": int(gid),
            "pageIndex": page,
            "pageSize": 30,
            "sort": "RANK",
            "needFilters": True,
            "filters": [{"type": t, "param": ""} for t in (
                "restanrantlType", "mealType", "priceTag", "cuisine", "dish",
                "dietaryRestriction", "restanrantStyle", "diningOption",
                "neighborhood", "airport",
            )],
        }
        ep = "21218/restaurantListForPc"
    else:  # hotels
        body = {"geoId": int(gid), "pageIndex": page, "pageSize": 30, "sort": "RANK"}
        ep = "20874/hotelListForPc"

    r = client.post(_API.format(svc=ep.split("/")[0], ep=ep.split("/")[1]),
                    json=body, headers=_HEADERS, timeout=20.0)
    r.raise_for_status()
    return r.json()


def _extract_items(kind: str, data: dict) -> tuple[list[dict], int | None]:
    """响应 → 统一条目 [{ta_id, name_zh, name_en, reviews}] + 总数。"""
    items: list[dict] = []
    total = None
    if kind == "attractions":
        total = (data.get("page") or {}).get("totalResultsCount")
        for v in data.get("verticalData") or []:
            items.append({
                "ta_id": str(v.get("taSightId") or ""),
                "name_zh": v.get("displayName") or "",
                "name_en": v.get("displayEnName") or "",
                "reviews": v.get("reviewsCount") or 0,
            })
    elif kind == "restaurants":
        mr = data.get("masterRestaurants") or {}
        total = mr.get("totalNum") or data.get("total")
        for v in mr.get("restaurants") or []:
            items.append({
                "ta_id": str(v.get("locationId") or v.get("restaurantId") or ""),
                "name_zh": v.get("name") or "",
                "name_en": "",
                "reviews": v.get("commentCount") or 0,
            })
    else:  # hotels
        total = data.get("total")
        for v in data.get("hotels") or []:
            items.append({
                "ta_id": str(v.get("taLocationId") or v.get("hotelId") or ""),
                "name_zh": v.get("name") or "",
                "name_en": v.get("enName") or "",
                "reviews": v.get("reviewCount") or 0,
            })
    return [i for i in items if i["ta_id"]], total


def _crawl_city_catalog(
    client: httpx.Client, city: str, gid: str, kinds: set[str],
    max_pages: int, delay: float,
) -> dict:
    """按需爬 (城市, 类型) 目录，磁盘缓存断点复用 + 增量加深。"""
    _CATALOG_DIR.mkdir(exist_ok=True)
    cache_path = _CATALOG_DIR / f"ta_catalog_{city}.json"
    cached = _load_json(cache_path, {})

    for kind in sorted(kinds):
        catalog: dict[str, dict] = cached.get(kind, {})
        done_pages = cached.get("pages_crawled", {}).get(kind, 0)
        if len(catalog) > 0 and done_pages >= max_pages:
            print(f"  [catalog] {city}/{kind} 缓存复用 {len(catalog)} 条（已爬 {done_pages} 页）")
            continue
        if len(catalog) > 0:
            print(f"  [catalog] {city}/{kind} 增量加深 {done_pages}→{max_pages} 页（已有 {len(catalog)} 条）")
        total = None
        for page in range(done_pages + 1, max_pages + 1):
            try:
                data = _list_page(client, kind, gid, page)
            except (httpx.HTTPError, ValueError) as e:
                print(f"  [catalog] {city}/{kind} 第{page}页请求失败: {e}")
                break
            items, total = _extract_items(kind, data)
            new = 0
            for it in items:
                if it["ta_id"] not in catalog:
                    catalog[it.pop("ta_id")] = it
                    new += 1
            pages_crawled = cached.setdefault("pages_crawled", {})
            pages_crawled[kind] = page
            print(f"  [catalog] {city}/{kind} 第{page}页 +{new}（累计 {len(catalog)}/{total or '?'}）")
            if total and len(catalog) >= total:
                break
            if not items:
                break
            time.sleep(delay)
        cached[kind] = catalog
        _save_json(cache_path, cached)

    cached["gid"] = gid
    _save_json(cache_path, cached)
    return cached


# ---------------------------------------------------------------------------
# 匹配
# ---------------------------------------------------------------------------


def _is_subseq(sub: str, s: str) -> bool:
    """sub 的字符是否按序出现在 s 中（非连续）。"""
    it = iter(s)
    return all(ch in it for ch in sub)


def _rank_matches(poi, catalog: dict[str, dict], threshold: float, top_n: int = 5):
    """POI × 候选池 → [(dID, score), …] 按分降序的 Top-N。

    打分（中文名多路取最高）：
    1) 归一化全名 difflib 比值；
    2) 核心名（去括号分店段）双向包含 → 0.95（≥3 字）；
    3) **中文**复合名词元（≥4 字）命中目录名 → 0.90 —— 英文词元一律不
       参与（2026-11-14 教训：museum/china/temple 泛词把旅行社/多语言
       垃圾条目顶成 0.90 假高分）；
    4) 子序列命中：目录名（≥3 字）按序嵌在查询核心名里 → 0.88
       （南京路 ⊆ 南京东路步行街 / 定陵 ⊆ 定陵地下宫殿类变体）；
    5) 垃圾目录过滤：reviews<5 的条目（旅行社/多语言重复页）只接受
       ≥0.98 的精确名匹配。
    """
    cands = [poi.name_zh, poi.name_en]
    for a in (getattr(poi, "name_aliases", None) or []):
        cands.append(a)
    cands = [c for c in cands if c]
    full_norms = [_norm(c) for c in cands]
    cores = [_core_name(c) for c in cands]
    cjk_toks = {
        t for c in cands for t in _tokens(c)
        if re.fullmatch(r"[\u4e00-\u9fff]+", t)
    }

    scored: list[tuple[float, str]] = []
    for did, item in catalog.items():
        targets = [_norm(item.get("name_zh")), _norm(item.get("name_en"))]
        score = 0.0
        for n, core in zip(full_norms, cores):
            for t in targets:
                if not n or not t:
                    continue
                s = difflib.SequenceMatcher(None, n, t).ratio()
                if core and len(core) >= 3 and (core in t or t in core):
                    s = max(s, 0.95)
                # 目录名嵌进查询名（t in core）只在长度差 ≤6 时可信：
                # 防"亚朵酒店"这类品牌短名吸走全部连锁分店行
                if t and len(t) >= 3 and t in core and len(core) - len(t) <= 6:
                    s = max(s, 0.95)
                # 子序列变体：目录名整体按序嵌进查询核心名（≥3 字）
                if len(t) >= 3 and _is_subseq(t, core):
                    s = max(s, 0.88)
                score = max(score, s)
        hit = any(
            tok and t and (tok in t or (len(t) >= 4 and t in tok))
            for tok in cjk_toks for t in targets
        )
        if hit:
            score = max(score, 0.90)
        # 垃圾目录闸：低评论条目只接受精确名
        reviews = item.get("reviews") or 0
        if reviews < 5 and score < 0.98:
            continue
        if score >= threshold:
            scored.append((score, did))

    scored.sort(key=lambda x: -x[0])
    seen: set[str] = set()
    out: list[tuple[str, float]] = []
    for s, did in scored:
        if did in seen:
            continue
        seen.add(did)
        out.append((did, s))
        if len(out) >= top_n:
            break
    return out


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", help="限定城市（可多值逗号分隔）")
    ap.add_argument("--limit", type=int, default=100, help="本批最多处理的 POI 数")
    ap.add_argument("--delay", type=float, default=0.5, help="API 请求间隔秒")
    ap.add_argument("--max-pages", type=int, default=20, help="每城每类目录最多页数（RANK 序前 20 页=600 条）")
    ap.add_argument("--threshold", type=float, default=0.85)
    ap.add_argument("--attraction-only", action="store_true", help="只映射景点类")
    ap.add_argument("--ranked-csv", action="store_true",
                    help="只处理规划页排名文件（chinatrip_active_ranked_pois_2026-11-14.csv）里的行，"
                         "pois(food 行) 与 restaurants 表都算")
    ap.add_argument("--dry-run", action="store_true", help="只报告不写库")
    args = ap.parse_args()

    cities = [c.strip() for c in args.city.split(",")] if args.city else None
    missed = _load_missed()

    factory = get_session_factory()
    with factory() as s:
        from sqlalchemy import String, case, cast, desc, nullslast

        # ---- 选行：pois（全类目）+ restaurants（餐厅底库）双表合并 --------
        targets: list[dict] = []  # {table, row, category, kind}
        ranked_pairs: set[tuple[str, str]] = set()
        ranked_order: dict[tuple[str, str], int] = {}
        if args.ranked_csv:
            # 规划页城市域（PLAN_CITIES）；括号归一化配对（全/半角、分店段）
            with open(_RANKED_CSV, encoding="utf-8-sig") as f:
                rank_i = 0
                for row in csv.DictReader(f):
                    rank_i += 1
                    city = (row.get("city") or "").strip()
                    if not city:
                        continue
                    key = (city, _core_name(row.get("name_zh")))
                    ranked_pairs.add(key)
                    ranked_order.setdefault(key, rank_i)
            csv_cities = {k[0] for k in ranked_pairs}
            if cities:
                csv_cities &= set(cities)
            print(f"排名文件模式: {len(ranked_pairs)} 个规划页站点对，{len(csv_cities)} 城")

        city_filter = cities
        if args.ranked_csv:
            city_filter = csv_cities

        q = s.query(Poi).filter(Poi.status == "active", Poi.ta_location_id.is_(None))
        if city_filter:
            q = q.filter(Poi.city.in_(city_filter))
        whens = [(Poi.source == src, rank) for rank, src in enumerate(SOURCE_PRIORITY)]
        q = q.order_by(
            case(*whens, else_=len(SOURCE_PRIORITY)),
            nullslast(desc(Poi.rating)),
            Poi.city,
        )
        pois_rows = q.all() if args.ranked_csv else q.limit(args.limit).all()
        for p in pois_rows:
            if _is_missed(missed, "pois", p.id):
                continue
            if args.ranked_csv:
                key = ((p.city or "").strip(), _core_name(p.name_zh))
                if key not in ranked_pairs:
                    continue
            targets.append({
                "table": "pois", "row": p,
                "category": p.category or "",
                "source": p.source or "",
                "rank": ranked_order.get(((p.city or "").strip(), _core_name(p.name_zh)), 10**9)
                        if args.ranked_csv else 10**9,
            })

        qr = s.query(Restaurant).filter(
            Restaurant.status == "active", Restaurant.ta_location_id.is_(None)
        )
        if city_filter:
            qr = qr.filter(Restaurant.city.in_(city_filter))
        whens_r = [(Restaurant.source == src, rank) for rank, src in enumerate(SOURCE_PRIORITY)]
        qr = qr.order_by(
            case(*whens_r, else_=len(SOURCE_PRIORITY)),
            nullslast(desc(Restaurant.rating)),
            Restaurant.city,
        )
        rest_rows = qr.all() if args.ranked_csv else qr.limit(max(0, args.limit - len(targets))).all()
        for r in rest_rows:
            if _is_missed(missed, "rest", r.id):
                continue
            if args.ranked_csv:
                key = ((r.city or "").strip(), _core_name(r.name_zh))
                if key not in ranked_pairs:
                    continue
            targets.append({
                "table": "restaurants", "row": r,
                "category": "food",
                "source": r.source or "",
                "rank": ranked_order.get(((r.city or "").strip(), _core_name(r.name_zh)), 10**9)
                        if args.ranked_csv else 10**9,
            })

        # 排名文件模式：按文件 rank 升序（规划页优先级即最终优先级）
        if args.ranked_csv:
            targets.sort(key=lambda t: t["rank"])
            seen_keys: set[tuple[str, str]] = set()
            deduped = []
            for t in targets:
                key = (t["table"], str(t["row"].id))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                deduped.append(t)
            targets = deduped

        # ---- 台账行优先重试（2026-11-14 用户拍板：台账必须全匹配，滚动重试）----
        ledger_pois_ids = {
            ln[5:] for ln in missed if ln.startswith("pois:")
        } | {ln for ln in missed if re.fullmatch(r"[0-9a-fA-F-]{36}", ln or "")}
        ledger_rest_ids = {ln[5:] for ln in missed if ln.startswith("rest:")}
        retried = 0
        if ledger_pois_ids:
            for p in (
                s.query(Poi)
                .filter(cast(Poi.id, String).in_(ledger_pois_ids))
                .all()
            ):
                if args.ranked_csv:
                    key = ((p.city or "").strip(), _core_name(p.name_zh))
                    if key not in ranked_pairs:
                        continue
                targets.append({
                    "table": "pois", "row": p,
                    "category": p.category or "",
                    "source": p.source or "",
                    "rank": ranked_order.get(key, 10**9) if args.ranked_csv else 10**9,
                })
                retried += 1
        if ledger_rest_ids:
            for r in (
                s.query(Restaurant)
                .filter(cast(Restaurant.id, String).in_(ledger_rest_ids))
                .all()
            ):
                if args.ranked_csv:
                    key = ((r.city or "").strip(), _core_name(r.name_zh))
                    if key not in ranked_pairs:
                        continue
                targets.append({
                    "table": "restaurants", "row": r,
                    "category": "food",
                    "source": r.source or "",
                    "rank": ranked_order.get(key, 10**9) if args.ranked_csv else 10**9,
                })
                retried += 1
        if retried:
            print(f"台账重试行: {retried}")

        if not targets:
            print("没有待映射行（pois + restaurants 全部已映射或在台账）")
            return
        srcs = sorted({t["source"] or "?" for t in targets})
        n_p = sum(1 for t in targets if t["table"] == "pois")
        n_r = len(targets) - n_p
        print(f"本批 {len(targets)} 行（pois {n_p} + restaurants {n_r}；source 序: {srcs[:8]}…）")

        client = httpx.Client(headers={"User-Agent": _UA})
        try:
            # 1) 城市 gID + 按需目录
            catalogs: dict[str, dict] = {}  # city -> {pools, gid}
            city_kinds: dict[str, set[str]] = {}
            for t in targets:
                kind = "attractions" if args.attraction_only else _POOL_OF_CATEGORY.get(t["category"], "attractions")
                if t["row"].city:
                    city_kinds.setdefault(t["row"].city, set()).add(kind)

            for city, kinds in sorted(city_kinds.items()):
                gid = _resolve_city_geo(client, city, args.delay)
                if not gid:
                    print(f"  [skip] {city} gID 解析失败（暂时性，不入台账）")
                    continue
                time.sleep(args.delay)
                cat = _crawl_city_catalog(client, city, gid, kinds, args.max_pages, args.delay)
                catalogs[city] = {
                    "pools": {kind: cat.get(kind) or {} for kind in kinds},
                    "gid": gid,
                }

            # 2) Top-N 候选 → 全局贪心分配（跨批次占用检查 + 轮内去重）
            occupied: dict[str, tuple[str, str]] = {}  # ta_id -> (table, row_id)
            for table, model in (("pois", Poi), ("restaurants", Restaurant)):
                for rid, tid in (
                    s.query(model.id, model.ta_location_id)
                    .filter(model.ta_location_id.isnot(None))
                    .all()
                ):
                    occupied[str(tid)] = (table, str(rid))

            cand_list: list[tuple[float, dict, str]] = []  # (score, target, did)
            unmatched: list[dict] = []
            for t in targets:
                kind = "attractions" if args.attraction_only else _POOL_OF_CATEGORY.get(t["category"], "attractions")
                pool = (catalogs.get(t["row"].city) or {}).get("pools", {}).get(kind) or {}
                if not pool:
                    unmatched.append(t)
                    continue
                ranked = _rank_matches(t["row"], pool, args.threshold)
                if not ranked:
                    best = 0.0
                    print(
                        f"  [warn] {t['row'].name_zh or t['row'].name_en}"
                        f"（{t['row'].city}/{t['category']}）无过阈候选"
                    )
                    unmatched.append(t)
                    continue
                for did, score in ranked:
                    cand_list.append((score, t, did))

            cand_list.sort(key=lambda x: -x[0])
            used: set[str] = set()
            assigned: set[int] = set()  # target 对象 id()，防同轮重复分配
            written = 0
            for score, t, did in cand_list:
                row = t["row"]
                if id(t) in assigned:
                    continue
                # 同一真实地点的多行应共享同一 TA ID —— 仅限景点/文博类
                # （≥0.95 强匹配）；酒店/餐厅分店是不同商户，一律一一对应。
                shareable = (
                    score >= 0.95
                    and t["category"] not in ("hotel", "food")
                )
                if did in used and not shareable:
                    continue
                owner = occupied.get(did)
                if owner and owner != (t["table"], str(row.id)) and not shareable:
                    continue  # 弱匹配/酒店/餐厅不得抢占或共享
                used.add(did)
                assigned.add(id(t))
                gid = (catalogs.get(t["row"].city) or {}).get("gid", "")
                tag = f"（{t['row'].city}/{t['category']}）"
                if args.dry_run:
                    print(f"  [dry] {t['table']}:{row.name_zh}{tag} ← d{did}（{score:.2f}）")
                    written += 1
                    continue
                if t["table"] == "pois":
                    s.query(Poi).filter(Poi.id == row.id, Poi.ta_location_id.is_(None)).update(
                        {"ta_location_id": did, "ta_geo_id": gid}, synchronize_session=False
                    )
                else:
                    s.query(Restaurant).filter(
                        Restaurant.id == row.id, Restaurant.ta_location_id.is_(None)
                    ).update({"ta_location_id": did, "ta_geo_id": gid}, synchronize_session=False)
                s.commit()
                written += 1
                print(f"  [ok] {t['table']}:{row.name_zh or row.name_en}{tag} ← d{did}（{score:.2f}）")

            # 3) 台账滚动重写（2026-11-14 拍板：台账必须全匹配）——本轮仍
            # 无匹配的行组成新台账（成功行自动移除；旧前缀行一并归一化）
            if not args.dry_run:
                still = [
                    f"{'pois' if t['table'] == 'pois' else 'rest'}:{t['row'].id}"
                    for t in unmatched
                ]
                _MISS_FILE.write_text(
                    "\n".join(dict.fromkeys(still)) + ("\n" if still else ""),
                    encoding="utf-8",
                )
                print(f"台账重写: 保留 {len(still)} 行滚动重试")

            print(f"\n完成：写库 {written}，未匹配 {len(unmatched)}（已入台账，下次跳过）")
        finally:
            client.close()


if __name__ == "__main__":
    main()
