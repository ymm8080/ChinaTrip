"""POI 富化·去哪儿（qunar）建议游玩时长——真值升级 heuristic 地板。

勘察结论（2026-10-25 实测，探针第一优先）：
  * sight.qunar.com 详情页 SSR 零反爬，纯 httpx GET 可得；时长字段形态
    ``建议用时</span><span class="v">2-3小时</span>``（黄鹤楼实测；勘察样本：
    故宫 4-6小时、湖北省博物馆 3-5小时、武汉动物园 0.5-1天）。
  * 发现通道 = list 翻页而非 BFS：``https://sight.qunar.com/list?city={slug}
    &page=N`` 每页 10 条，页内 application/ld+json ItemList 直接给
    (POI 名, 数字 id)，id 即详情页 sight.qunar.com/{id}；单城可翻 ~200 页。
    robots.txt 全放行；keyword 参数不生效，只能翻页。
  * 坑（实测）：错误 city slug 不报错而是 302 到 beijing 默认列表——
    靠最终 URL + ItemList addressLocality 双重校验拒收（city_redirect 计数）。

拍板（2026-10-25 用户）：真值源 update 覆盖 heuristic 地板值（≈2937 行是
"规划下限"不是事实主张），不是只填空；ctrip 等既有真值不动——写前过
app.services.poi_classify.duration_upgradable 闸门（仅 NULL / heuristic 可写）。

城市映射：QUNAR_CITY_SLUGS 按 2026-10-25 真库普查
（active GROUP BY city，见函数尾注释）构建，基本是身份拼音映射；
州/盟/兵团长名、拼音撞车（泰州/抚州/宜春/伊春）、县级市与名山古镇
（qunar 是否单列拿不准）一律跳过计 city_no_slug，不硬猜。

用法：
    python -m app.jobs.enrich_qunar_duration [--limit 200] [--pages-per-city 40]
        [--concurrency 4] [--dry-run]
"""

import argparse
import asyncio
import json
import logging
import random
import re
import sys
from typing import NamedTuple

import httpx
from sqlalchemy import case, or_

from app.db import get_session_factory
from app.models import Poi
from app.services.poi_classify import duration_upgradable

logger = logging.getLogger(__name__)

_DEFAULT_LIMIT = 200
_DEFAULT_PAGES_PER_CITY = 40
_DEFAULT_CONCURRENCY = 4
_DURATION_MIN, _DURATION_MAX = 15, 600
_MINUTES_PER_DAY = 480  # 「天」按 8 小时算（0.5-1天 → 中值 360 分）
_RETRYABLE_STATUS = (429, 500, 502, 503, 504)
_MAX_ATTEMPTS = 4
_SOURCE_PRIORITY = (
    "unesco",
    "5a",
    "museum1",
    "museum2",
    "museum3",
    "artmuseum",
    "amap",
    "chinatravel",
    "osm",
)

_LIST_URL = "https://sight.qunar.com/list?city={slug}&page={page}"
_DETAIL_URL = "https://sight.qunar.com/{poi_id}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    )
}

# 城市 → qunar list 的拼音 slug（基本身份映射；跳过规则见模块头注释）。
# 普查来源：2026-10-25 active 行 GROUP BY city，共 203 个非空城市，本表
# 收 162 个（≈3647/3814 active 行）；跳过：空 city 129 行、州/盟/兵团长名
# 6、拼音撞车 4（泰州/抚州/宜春/伊春）、县级市与名山古镇 28。
QUNAR_CITY_SLUGS = {
    # --- 300+ 行大城（10 城 ≈3433 行）---
    "杭州": "hangzhou",
    "上海": "shanghai",
    "重庆": "chongqing",
    "苏州": "suzhou",
    "北京": "beijing",
    "广州": "guangzhou",
    "武汉": "wuhan",
    "成都": "chengdu",
    "南京": "nanjing",
    "深圳": "shenzhen",
    # --- 3-5 行 ---
    "西安": "xian",
    "三亚": "sanya",
    "桂林": "guilin",
    "保定": "baoding",
    "宜昌": "yichang",
    "洛阳": "luoyang",
    "长春": "changchun",
    "无锡": "wuxi",
    "台州": "taizhou",
    "延安": "yanan",
    "黄山": "huangshan",
    "上饶": "shangrao",
    # --- 2 行 ---
    "丽水": "lishui",
    "宝鸡": "baoji",
    "安顺": "anshun",
    "邯郸": "handan",
    "长沙": "changsha",
    "惠州": "huizhou",
    "连云港": "lianyungang",
    "毕节": "bijie",
    "嘉兴": "jiaxing",
    "天津": "tianjin",
    "大连": "dalian",
    "厦门": "xiamen",
    "鄂尔多斯": "eerduosi",
    "晋中": "jinzhong",
    "安阳": "anyang",
    "承德": "chengde",
    "本溪": "benxi",
    "拉萨": "lasa",
    "佛山": "foshan",
    "六安": "luan",
    "威海": "weihai",
    "宁波": "ningbo",
    "青岛": "qingdao",
    "忻州": "xinzhou",
    "丽江": "lijiang",
    "常州": "changzhou",
    "临汾": "linfen",
    "昆明": "kunming",
    # --- 1 行（地级市 + 敦煌/武夷山/满洲里/峨眉山等单列旅游目的地）---
    "温州": "wenzhou",
    "江门": "jiangmen",
    "新乡": "xinxiang",
    "济南": "jinan",
    "南充": "nanchong",
    "福州": "fuzhou",
    "张家界": "zhangjiajie",
    "克拉玛依": "kelamayi",
    "枣庄": "zaozhuang",
    "扬州": "yangzhou",
    "通化": "tonghua",
    "铜仁": "tongren",
    "海东": "haidong",
    "张掖": "zhangye",
    "宿迁": "suqian",
    "广安": "guangan",
    "开封": "kaifeng",
    "银川": "yinchuan",
    "周口": "zhoukou",
    "盘锦": "panjin",
    "萍乡": "pingxiang",
    "龙岩": "longyan",
    "百色": "baise",
    "绍兴": "shaoxing",
    "邵阳": "shaoyang",
    "呼伦贝尔": "hulunbeier",
    "济宁": "jining",
    "襄阳": "xiangyang",
    "梅州": "meizhou",
    "巴中": "bazhong",
    "嘉峪关": "jiayuguan",
    "泰安": "taian",
    "腾冲": "tengchong",
    "宁德": "ningde",
    "晋城": "jincheng",
    "合肥": "hefei",
    "武夷山": "wuyishan",
    "阜阳": "fuyang",
    "焦作": "jiaozuo",
    "临沂": "linyi",
    "徐州": "xuzhou",
    "驻马店": "zhumadian",
    "安庆": "anqing",
    "莆田": "putian",
    "淮安": "huaian",
    "舟山": "zhoushan",
    "东营": "dongying",
    "肇庆": "zhaoqing",
    "松原": "songyuan",
    "遵义": "zunyi",
    "赣州": "ganzhou",
    "吐鲁番": "tulufan",
    "唐山": "tangshan",
    "信阳": "xinyang",
    "池州": "chizhou",
    "宣城": "xuancheng",
    "平凉": "pingliang",
    "吴忠": "wuzhong",
    "西宁": "xining",
    "陇南": "longnan",
    "南通": "nantong",
    "芜湖": "wuhu",
    "景德镇": "jingdezhen",
    "赤峰": "chifeng",
    "泉州": "quanzhou",
    "秦皇岛": "qinhuangdao",
    "商洛": "shangluo",
    "贺州": "hezhou",
    "大同": "datong",
    "常德": "changde",
    "天水": "tianshui",
    "广元": "guangyuan",
    "南昌": "nanchang",
    "柳州": "liuzhou",
    "平顶山": "pingdingshan",
    "滁州": "chuzhou",
    "石嘴山": "shizuishan",
    "满洲里": "manzhouli",
    "中山": "zhongshan",
    "岳阳": "yueyang",
    "马鞍山": "maanshan",
    "韶关": "shaoguan",
    "敦煌": "dunhuang",
    "林芝": "linzhi",
    "雅安": "yaan",
    "乌鲁木齐": "wulumuqi",
    "南阳": "nanyang",
    "衡阳": "hengyang",
    "阳江": "yangjiang",
    "衢州": "quzhou",
    "贵阳": "guiyang",
    "沈阳": "shenyang",
    "中卫": "zhongwei",
    "镇江": "zhenjiang",
    "鞍山": "anshan",
    "乐山": "leshan",
    "绵阳": "mianyang",
    "荆门": "jingmen",
    "三明": "sanming",
    "南宁": "nanning",
    "盐城": "yancheng",
    "九江": "jiujiang",
    "长治": "changzhi",
    "湖州": "huzhou",
    "崇左": "chongzuo",
    "咸宁": "xianning",
    "株洲": "zhuzhou",
    "北海": "beihai",
    "保山": "baoshan",
    "哈尔滨": "haerbin",
    "峨眉山": "emeishan",
}

# --- 解析：时长字段 / list 页 ItemList --------------------------------------


# 详情页字段：`<span class="k">建议用时</span><span class="v">2-3小时</span>`
_DURATION_FIELD_RE = re.compile(r"建议用时\s*</span>\s*<span[^>]*>([^<]{1,20})</span>")
# 值形态：4-6小时 / 1小时 / 0.5-1天 / 2-3.5小时 / 45分钟（区间可含小数）
_DURATION_VALUE_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*[-~－—至]?\s*(\d+(?:\.\d+)?)?\s*(小时|天|分钟)"
)
# list 页 application/ld+json ItemList：{"position":N,"name":"黄鹤楼",
# "url":"https://sight.qunar.com/898602836"}（2026-10-25 实测页结构）
_LIST_ITEM_RE = re.compile(
    r'"position":\s*\d+,\s*"name":\s*"([^"]{1,60})",\s*'
    r'"url":\s*"https://sight\.qunar\.com/(\d+)"'
)
_LOCALITY_RE = re.compile(r'"addressLocality":\s*"([^"]{1,20})"')


def extract_duration_text(html: str) -> str | None:
    """详情页 HTML 抽「建议用时」字段原文；无字段返回 None。"""
    m = _DURATION_FIELD_RE.search(html)
    return m.group(1).strip() if m else None


def _parse_minutes(text) -> int | None:
    """'4-6小时'/'0.5-1天'/'1小时' → 区间中值分钟（天=480 分，不过闸门）。"""
    if not text:
        return None
    m = _DURATION_VALUE_RE.search(str(text))
    if not m:
        return None
    low = float(m.group(1))
    high = float(m.group(2)) if m.group(2) else low
    factor = {"分钟": 1, "小时": 60, "天": _MINUTES_PER_DAY}[m.group(3)]
    return int(round((low + high) / 2 * factor))


def _gate(minutes: int | None) -> int | None:
    """15-600 分钟闸门，出界返回 None（调用方计 invalid）。"""
    if minutes is None:
        return None
    return minutes if _DURATION_MIN <= minutes <= _DURATION_MAX else None


def parse_duration_minutes(text) -> int | None:
    """解析 + 闸门一步到位（离线单测入口）。"""
    return _gate(_parse_minutes(text))


def parse_list_page(html: str) -> tuple[list[tuple[str, str]], str | None]:
    """list 页 → ([(POI 名, qunar id)] 去重保序, 页面城市名或 None)。"""
    items: list[tuple[str, str]] = [
        (name, poi_id) for name, poi_id in _LIST_ITEM_RE.findall(html)
    ]
    m = _LOCALITY_RE.search(html)
    return list(dict.fromkeys(items)), (m.group(1) if m else None)


def _city_page_ok(slug: str, final_url, locality: str | None, city: str) -> bool:
    """错误 slug 会被 302 到 beijing 默认列表：最终 URL 或 ItemList 城市
    名任一能对上才收（都对不上=串城，拒收整页防跨城错写）。"""
    if f"city={slug}" in str(final_url):
        return True
    return bool(locality) and locality.removesuffix("市") == city


# --- 名字变体匹配（逻辑对齐 enrich_ctrip_detail._variants，按任务约定
#     抄成私有函数，不跨文件 import——那是另一会话的未跟踪文件）----------


def _name_variants(name: str) -> list[str]:
    """匹配变体：原名 → 剥前缀行政区 → 再剥尾缀类型词。"""
    out = [name]
    m = re.search(r"^[一-龥]{1,10}?(?:自治州|自治县|区|县|市|旗)", name)
    if m and len(name) - len(m.group(0)) >= 3:
        out.append(name[len(m.group(0)) :])
    core = re.sub(
        r"(风景名胜区|旅游景区|旅游区|风景区|度假区|景区|遗址公园|湿地公园|"
        r"森林公园|地质公园|乐园|公园)$",
        "",
        out[-1],
    )
    if len(core) >= 3 and core not in out:
        out.append(core)
    return list(dict.fromkeys(out))


def build_name_index(items: list[tuple[str, str]]) -> dict[str, str]:
    """(list 名, id) → 变体放行查表：list 名同样剥尾缀建键，首见优先。"""
    index: dict[str, str] = {}
    for name, poi_id in items:
        for key in _name_variants(name):
            index.setdefault(key, poi_id)
    return index


def _lookup(index: dict[str, str], name: str) -> str | None:
    for v in _name_variants(name):
        poi_id = index.get(v)
        if poi_id:
            return poi_id
    return None


# --- 目标行选取 -------------------------------------------------------------


def _source_rank():
    whens = [(Poi.source == src, rank) for rank, src in enumerate(_SOURCE_PRIORITY)]
    return case(*whens, else_=len(_SOURCE_PRIORITY))


def select_targets(session_factory, *, limit: int) -> list[Poi]:
    """active 且时长可升级（NULL 或 heuristic 来源），unesco/5a/amap 优先。

    只选 QUNAR_CITY_SLUGS 覆盖城市的行（对齐 enrich_ctrip_detail 的
    CITY_SLUGS 闸门）——museum1/2/3 行 city 存省名（山东/江苏…），
    qunar 无省列表页，不滤掉会把 limit 全烧在永不可匹配行上
    （2026-10-25 首跑实录：30 目标 0 城市）。
    """
    with session_factory() as session:
        return (
            session.query(Poi)
            .filter(Poi.status == "active", Poi.city.in_(list(QUNAR_CITY_SLUGS)))
            .filter(
                or_(
                    Poi.suggested_duration_min.is_(None),
                    Poi.duration_source == "heuristic",
                )
            )
            .order_by(_source_rank(), Poi.rating.desc().nullslast(), Poi.id)
            .limit(limit)
            .all()
        )


class _Target(NamedTuple):
    poi_id: object
    name: str
    city: str


# --- 写库（真值升级语义：NULL→写、heuristic→覆写、ctrip 等真值不动）---------


def _write_row(factory, poi_id, minutes: int) -> bool:
    with factory() as session:
        row = session.get(Poi, poi_id)
        if row is None:
            return False
        if not duration_upgradable(row):
            return False
        row.suggested_duration_min = minutes
        row.duration_source = "qunar"
        session.commit()
        return True


# --- 网络层 -----------------------------------------------------------------


async def _fetch(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str
) -> httpx.Response:
    """429/5xx 指数退避重试（对齐 enrich_llm_web._chat_web 的退避循环）；
    重试耗尽或非可重试状态码原样返回 Response，由调用方计错误。"""
    for attempt in range(_MAX_ATTEMPTS):
        async with sem:
            r = await client.get(url)
        if r.status_code == 200:
            return r
        if r.status_code in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS - 1:
            await asyncio.sleep(min(30.0, 2.0**attempt + random.random() * 2))
            continue
        return r
    raise RuntimeError("unreachable")


def _count_error(stats: dict, kind: str) -> None:
    stats["errors"] += 1
    stats["error_kinds"][kind] = stats["error_kinds"].get(kind, 0) + 1


async def _process_detail(
    client, factory, sem, target: _Target, qunar_id: str, stats: dict
) -> None:
    try:
        r = await _fetch(client, sem, _DETAIL_URL.format(poi_id=qunar_id))
    except Exception as exc:
        logger.warning("qunar detail fetch failed: %s", exc)
        _count_error(stats, type(exc).__name__)
        return
    if r.status_code != 200:
        _count_error(stats, f"HTTP{r.status_code}")
        return
    text = extract_duration_text(r.text)
    if text is None:
        stats["no_duration"] += 1
        return
    raw = _parse_minutes(text)
    minutes = _gate(raw)
    if minutes is None:
        # 无「数字+单位」形态（暂无/文本描述）计 no_duration，出闸门计 invalid
        if raw is None:
            stats["no_duration"] += 1
        else:
            stats["invalid"] += 1
        return
    if not await asyncio.to_thread(_write_row, factory, target.poi_id, minutes):
        # 行已不可升级（并发被别源占坑）或已删——按用户规则留日志
        logger.info(
            "qunar duration skipped (not upgradable): %s (%s)",
            target.name,
            target.city,
        )
        return
    logger.info(
        "qunar duration %s (%s): %s -> %smin",
        target.name,
        target.city,
        text,
        minutes,
    )
    stats["duration_filled"] += 1
    if len(stats["samples"]) < 10:
        stats["samples"].append(
            {
                "name": target.name,
                "city": target.city,
                "duration_min": minutes,
                "raw": text,
            }
        )


async def _collect_city(
    client,
    factory,
    city: str,
    slug: str,
    targets: list[_Target],
    pages_cap: int,
    sem: asyncio.Semaphore,
    stats: dict,
) -> None:
    """单城：list 翻页建名字索引（全命中或超限即停）→ 并发抓详情写库。"""
    index: dict[str, str] = {}
    seen_ids: set[str] = set()
    page = 1
    remaining = list(targets)
    while remaining and page <= pages_cap:
        try:
            r = await _fetch(client, sem, _LIST_URL.format(slug=slug, page=page))
        except Exception as exc:
            logger.warning("qunar list fetch failed city=%s: %s", city, exc)
            _count_error(stats, type(exc).__name__)
            break
        stats["pages"] += 1
        if r.status_code != 200:
            _count_error(stats, f"HTTP{r.status_code}")
            break
        items, locality = parse_list_page(r.text)
        if not _city_page_ok(slug, r.url, locality, city):
            logger.warning(
                "qunar list city mismatch: %s(%s) landed on %s", city, slug, r.url
            )
            _count_error(stats, "city_redirect")
            break
        fresh = [(n, pid) for n, pid in items if pid not in seen_ids]
        if not fresh:
            break  # 翻页尽头或绕回第 1 页
        seen_ids.update(pid for _, pid in fresh)
        for key, pid in build_name_index(fresh).items():
            index.setdefault(key, pid)
        remaining = [t for t in remaining if _lookup(index, t.name) is None]
        page += 1
    matched = [(t, _lookup(index, t.name)) for t in targets]
    matched = [(t, pid) for t, pid in matched if pid]
    stats["matched"] += len(matched)
    if matched:
        await asyncio.gather(
            *(
                _process_detail(client, factory, sem, t, pid, stats)
                for t, pid in matched
            )
        )


async def enrich(factory, *, limit: int, pages_per_city: int, concurrency: int) -> dict:
    stats = {
        "targets": 0,
        "no_name": 0,
        "city_no_slug": 0,
        "cities": 0,
        "pages": 0,
        "matched": 0,
        "no_duration": 0,
        "invalid": 0,
        "duration_filled": 0,
        "errors": 0,
        "error_kinds": {},
        "samples": [],
    }
    rows = select_targets(factory, limit=limit)
    stats["targets"] = len(rows)
    by_city: dict[str, list[_Target]] = {}
    for r in rows:
        name = (r.name_zh or "").strip()
        if not name:
            stats["no_name"] += 1
            continue
        city = (r.city or "").strip()
        by_city.setdefault(city, []).append(_Target(r.id, name, city))
    sem = asyncio.Semaphore(max(1, concurrency))
    async with httpx.AsyncClient(
        headers=_HEADERS, timeout=30, follow_redirects=True
    ) as client:
        for city, targets in by_city.items():
            slug = QUNAR_CITY_SLUGS.get(city)
            if not slug:
                stats["city_no_slug"] += len(targets)
                continue
            stats["cities"] += 1
            await _collect_city(
                client, factory, city, slug, targets, pages_per_city, sem, stats
            )
    return stats


# --- CLI --------------------------------------------------------------------


def dry_run(session_factory, *, limit: int) -> None:
    rows = select_targets(session_factory, limit=limit)
    print(json.dumps({"dry_run": True, "targets": len(rows)}, ensure_ascii=True))
    for r in rows[:5]:
        rating = float(r.rating) if r.rating is not None else None
        print(
            json.dumps(
                {
                    "source": r.source,
                    "city": r.city,
                    "name": r.name_zh,
                    "duration": r.suggested_duration_min,
                    "duration_source": r.duration_source,
                    "rating": rating,
                },
                ensure_ascii=True,
            )
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qunar duration enrichment (upgrades heuristic floors)"
    )
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    parser.add_argument("--pages-per-city", type=int, default=_DEFAULT_PAGES_PER_CITY)
    parser.add_argument("--concurrency", type=int, default=_DEFAULT_CONCURRENCY)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    factory = get_session_factory()
    if args.dry_run:
        dry_run(factory, limit=args.limit)
        return 0
    stats = asyncio.run(
        enrich(
            factory,
            limit=args.limit,
            pages_per_city=args.pages_per_city,
            concurrency=args.concurrency,
        )
    )
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
