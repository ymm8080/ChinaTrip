# -*- coding: utf-8 -*-
"""错针扫描（2026-11-07，只读，可重复跑）：全库扫描「同城同实体、低优源坐标
与高优源坐标相距 >1km」的疑似错针对。背景事故：ct_成都_2 武侯祠错针桂溪街道
锦悦西路 2 号（8.4km 假腿），同城 museum1 行成都武侯祠博物馆坐标正确。

产出：ops/wrongpin_scan_20261107.md + stdout 统计。不做任何写库操作。

比对口径（任务拍板 2026-11-07）：
- 池：status='active' 且 category 非 food/hotel/transport（观光点为主；
  餐厅/酒店同名分店是合法多门店不扫；交通设施天然多点不扫）。
- 名称相似：去括注后按后缀词典（最长优先）迭代剥尾生成核心词组（带剥尾深度
  与是否仅出自别名标记）。核心相等须≥3字；互含须短核≥3字、长短差≥2字、
  短核剥尾深度≤1；短核为纯馆类通名不认；「长核仅出自别名且余差≤2」与
  「双侧仅别名」降为弱配对 tier2 单独归档（二轮自查收紧）。
- source 优先级：B 严格高于 A 才成对。基础序 = CLAUDE.md Iron rule
  （app/services/source_tier.py SOURCE_PRIORITY）；名录外源按 2026-11-03
  名录拍板序插入：官方名录（relicpark/scenic/show/4a/histvillage）在 amap
  前，crawl/intl 候选源（baidu/curated/intl各站/ctrip/xiaohongshu…）与
  chinatravel 同档垫底区，osm 最末，manual 人工修正仅次于名录头部。
  source_poi_id 带 ct_ 前缀的行无论标称 source 一律按 chinatravel 档计
  （事故行 ct_成都_2 标称 amap 即此类），并打 ct 标记。
- 距离：haversine(location) > 1000 米。
- 假阳性自查（任务第5条）：分店/门店后缀、入口/停车场/码头/索道/游客中心等
  子设施词、零售词行直接跳过；山/湖/岛等大范围地理核打 wide_range 警示单独
  归档不进主清单。
"""

import io
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

from sqlalchemy import create_engine, text

sys.stdout.reconfigure(encoding="utf-8")

OUT_MD = r"D:/CHINATRIP/CHINATRIP CODES/ops/wrongpin_scan_20261107.md"
DSN = "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"

# ---------------------------------------------------------------- 优先级映射
# 基础序 = Iron rule；【+】为本库实有、名录外源按拍板口径插入的位置。
PRIORITY: list[str] = [
    "unesco",        # 0
    "5a",            # 1
    "manual",        # 2 【+】人工修正行，可信度高，只作 B 不作 A
    "museum1",       # 3
    "museum2",       # 4
    "museum3",       # 5
    "artmuseum",     # 6
    "street",        # 7
    "histown",       # 8
    "relicpark",     # 9 【+】国家考古遗址公园名录
    "scenic",        # 10 【+】国家级风景名胜名录（拍板序在 4a 前）
    "show",          # 11 【+】演出名录
    "4a",            # 12 【+】4A 名录
    "histvillage",   # 13 【+】历史文化名村/镇名录
    "amap",          # 14
    "chinatravel",   # 15
    "baidu",         # 16 【+】crawl 候选档（与 chinatravel 同级邻位）
    "curated",       # 17 【+】
    "reservation",   # 18 【+】
    "ctrip",         # 19 【+】intl 候选档全部垫底区
    "tripadvisor",   # 20
    "lonelyplanet",  # 21
    "sygic",         # 22
    "tiktok",        # 23
    "xiaohongshu",   # 24
    "layla",         # 25
    "tui",           # 26
    "mindtrip",      # 27
    "wonderplan",    # 28
    "osm",           # 29
]
PRIO = {s: i for i, s in enumerate(PRIORITY)}
UNRANKED = len(PRIORITY) + 5  # 未识别源：只作 B 不作 A（保守）

# ---------------------------------------------------------------- 名称核心词
SUFFIX_WORDS = [
    # 长词在前，迭代剥尾
    "国家考古遗址公园", "国家森林公园", "国家湿地公园", "国家地质公园",
    "国家风景名胜区", "风景名胜区", "旅游度假区", "旅游区", "度假区",
    "风景区", "名胜区", "景区", "遗址公园", "森林公园", "湿地公园",
    "地质公园", "国家公园", "考古遗址公园",
    "博物馆", "美术馆", "陈列馆", "纪念馆", "展览馆", "科技馆", "博览馆",
    "规划馆", "民俗馆", "文化馆", "图书馆",
    "历史街区", "历史文化街区", "街区", "古镇", "古城", "古街", "老街",
    "公园", "广场", "遗址", "故城", "城址", "旧址", "故居", "陵园",
    "中心", "大厦",
    "祠", "寺", "庙", "塔", "楼", "阁", "宫", "观", "庵", "堂",
    "陵", "桥", "关", "坊", "巷", "街", "村", "镇", "城", "园", "馆", "院",
    "亭", "山", "湖", "岛", "峰", "泉", "洞", "岩", "瀑", "滩", "潭",
]
_SUFFIX_SORTED = sorted(SUFFIX_WORDS, key=len, reverse=True)

BRANCH_PAT = re.compile(r"[（(][^（）()]*店[)）]|分店|旗舰店|门店|一店|二店|三店|四店|五店|总店")
SUBFACILITY_PAT = re.compile(
    r"入口|出口|停车场|码头|渡口|索道|缆车|售票处|售票房|游客中心|游客服务|游客服务区"
    r"|游客接待|集散中心|观景台|观景平台|观光车站|索道上站|索道下站|栈道|步道|登山步道"
    r"|服务区|收费站|公交站|地铁站|客运站|候机楼|安检口|西门|东门|南门|北门|正门|侧门|后门"
)
RETAIL_PAT = re.compile(
    r"便利店|超市|咖啡|奶茶|面包|烘焙|药店|大药房|银行|ATM|网吧|影城|电影院|KTV"
    r"|健身房|美容院|理发|洗车|加油站|4S店|数码|手机卖场|服装店|文具店|书店|书局"
)
HOTELISH_PAT = re.compile(r"酒店|饭店|宾馆|民宿|公寓|客栈|旅馆|招待所|青旅|公馆|山庄|度假村")
GEO_FEATURE_PAT = re.compile(r"山|湖|岛|峰|岭|谷|草原|森林|温泉|峡|瀑布|海滩|沙漠|江|河|海|洞")
EXCLUDE_CATEGORY = {"food", "hotel", "transport"}

BRACKET_PAT = re.compile(r"[（(【\[][^（）()【\】\]]*[）)【\】\]]")
SEG_PAT = re.compile(r"[·•—–\-、,，]")


def strip_suffixes(s: str) -> list[str]:
    """迭代剥尾（最长后缀优先，单步可剥多字），返回 [core: depth] 沿途全核。"""
    out = []
    cur = s
    depth = 0
    while True:
        if len(cur) >= 2:
            out.append((cur, depth))
        hit = None
        for w in _SUFFIX_SORTED:
            if cur.endswith(w) and len(cur) > len(w):
                hit = w
                break
        if not hit:
            break
        cur = cur[: -len(hit)]
        depth += 1
    return out


# 纯馆类通名词：裸核（无正名前缀）不参与匹配，防「科技馆」配一切 *科技馆
GENRE_WORDS = {
    "科技馆", "博物馆", "美术馆", "纪念馆", "展览馆", "陈列馆", "文化馆",
    "规划馆", "民俗馆", "图书馆", "博览馆", "动物园", "植物园", "游乐园",
    "欢乐谷", "森林公园", "湿地公园", "地质公园", "遗址公园", "国家公园",
}
# 裸政区名短核（广东省/北京市…）：官方前缀泛名，互配皆为异实体
ADMIN_CORE_PAT = re.compile(r"^.{0,2}[省市县区旗]$")


def cores_of(name: str, aliases) -> dict[str, tuple[int, bool]]:
    """核心词组 → {core: (剥尾深度, 是否仅出自别名)}。

    基底：去括注后的全串 + ·/—/- 等分隔的前后段；本名基底先算，别名基底
    只补本名没有的核（并标 from_alias）。
    """
    bases = set()
    for base in [name] + list(aliases or []):
        b = BRACKET_PAT.sub("", str(base)).strip()
        if not b:
            continue
        bases.add(b)
        segs = [x.strip() for x in SEG_PAT.split(b) if x.strip()]
        if len(segs) > 1:
            bases.add(segs[0])
            bases.add(segs[-1])
    name_bases = {BRACKET_PAT.sub("", name).strip()}
    segs0 = SEG_PAT.split(BRACKET_PAT.sub("", name).strip())
    if len(segs0) > 1:
        name_bases.add(segs0[0].strip())
        name_bases.add(segs0[-1].strip())
    cores: dict[str, tuple[int, bool]] = {}
    for b in name_bases:
        if not b:
            continue
        for c, d in strip_suffixes(b):
            if len(c) >= 2 and (c not in cores or d < cores[c][0]):
                cores[c] = (d, False)
    for b in bases - name_bases:
        for c, d in strip_suffixes(b):
            if len(c) >= 2 and c not in cores:
                cores[c] = (d, True)
    return cores


def name_match(
    coreA: dict, coreB: dict, name_a: str, name_b: str, name_cores_a: set, name_cores_b: set
) -> tuple[str, str] | None:
    """返回 (命中核, tier)；tier='1' 主清单 / '2' 弱配对（须人工复核）。

    口径（2026-11-07 三轮自查后收紧）：
    - 核心相等 ≥3 字；互含短核 ≥3 字且长短差 ≥2 字；
    - 参与互含的短核剥尾深度 ≤1（防过剥残核 上海大 ⊂ 上海大学）；
    - 短核为纯馆类通名（裸核无正名）不认（防 科技馆 配一切 *科技馆）；
    - 长核仅出自别名且余差 ≤2 字 → 降弱档（防 上海科技馆分馆 整含 上海科技馆；
      事故形态长核 成都武侯祠 出自本名，不受影响）；
    - 短核属短核侧「本名衍生核集合」（含剥尾形）且长核仅出自别名 → 降弱档
      （防 上海宝龙美术馆 别名整含 龙美术馆 本名、故宫博物院钟表馆 别名整含
      故宫博物院 及其剥尾形 故宫博物）；
    - 双侧参与核均仅出自别名 → 降弱档（防 中共一大 × 中共一大会址）；
    - 参与互含的短核仅出自别名且不在短核侧本名核集合、长短差 ≤3 字 → 降弱档
      （防 品牌泛名 南山区华侨城旅游度假区 别名整含 华侨城 配 东部华侨城）；
    - 短核为裸政区名（≤4 字且以省/市/县/区/旗收尾）→ 降弱档
      （防 官方前缀泛名 广东省 配 广东省博物馆）；
    - 遍历按排序序，命中确定（PYTHONHASHSEED 无关）。
    """
    best: tuple[str, str] | None = None

    def consider(core: str, tier: str) -> None:
        nonlocal best
        if best is None or tier < best[1]:
            best = (core, tier)

    for a in sorted(coreA):
        for b in sorted(coreB):
            da, fa = coreA[a]
            db, fb = coreB[b]
            if a == b:
                if len(a) >= 3 and da <= 1 and db <= 1 and a not in GENRE_WORDS:
                    admin = bool(ADMIN_CORE_PAT.match(a))
                    consider(a, "2" if (fa and fb) or admin else "1")
                continue
            if len(a) >= 3 and da <= 1 and a in b and (len(b) - len(a)) >= 2:
                if a in GENRE_WORDS:
                    continue
                admin = bool(ADMIN_CORE_PAT.match(a))
                weak = (
                    (fb and len(b) - len(a) <= 2)
                    or (fa and fb)
                    or (fb and a in name_cores_a)
                    or admin
                    or (fa and a not in name_cores_a and len(b) - len(a) <= 3)
                )
                consider(a, "2" if weak else "1")
            elif len(b) >= 3 and db <= 1 and b in a and (len(a) - len(b)) >= 2:
                if b in GENRE_WORDS:
                    continue
                admin = bool(ADMIN_CORE_PAT.match(b))
                weak = (
                    (fa and len(a) - len(b) <= 2)
                    or (fa and fb)
                    or (fa and b in name_cores_b)
                    or admin
                    or (fb and b not in name_cores_b and len(a) - len(b) <= 3)
                )
                consider(b, "2" if weak else "1")
    return best


def haversine(lon1, lat1, lon2, lat2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- 拉数
eng = create_engine(DSN, connect_args={"connect_timeout": 3})
with eng.connect() as c:
    rows = c.execute(
        text(
            "select id, name_zh, source, source_poi_id, city, category, "
            "address, name_aliases::text as aliases, "
            "ST_X(location::geometry) as lon, ST_Y(location::geometry) as lat "
            "from pois where status='active' "
            "and (category is null or category not in ('food','hotel','transport')) "
            "and location is not null"
        )
    ).mappings().all()

pool = []
fp_skipped = Counter()
for r in rows:
    name = (r["name_zh"] or "").strip()
    if not name:
        continue
    src = (r["source"] or "").strip()
    spid = (r["source_poi_id"] or "").strip()
    cat = (r["category"] or "").strip()
    # 行级假阳性剔除：分店/子设施/零售/酒店词（含误标行）
    reason = None
    if BRANCH_PAT.search(name):
        reason = "branch"
    elif SUBFACILITY_PAT.search(name):
        reason = "subfacility"
    elif RETAIL_PAT.search(name):
        reason = "retail"
    elif HOTELISH_PAT.search(name):
        reason = "hotelish"
    if reason:
        fp_skipped[reason] += 1
        continue
    try:
        aliases = json.loads(r["aliases"]) if r["aliases"] else []
    except Exception:
        aliases = []
    ct_id = spid.startswith("ct_")
    eff_src = "chinatravel" if (ct_id and src != "chinatravel") else src
    rank = PRIO.get(eff_src, UNRANKED)
    cores = cores_of(name, aliases)
    pool.append(
        {
            "id": str(r["id"]),
            "name": name,
            "source": src,
            "eff_src": eff_src,
            "spid": spid,
            "city": (r["city"] or "").strip(),
            "cat": cat,
            "addr": (r["address"] or "").strip(),
            "lon": float(r["lon"]),
            "lat": float(r["lat"]),
            "rank": rank,
            "ct": ct_id,
            "cores": cores,
            "name_cores": {c for c, (_, f) in cores.items() if not f},
        }
    )

by_city = defaultdict(list)
for p in pool:
    by_city[p["city"]].append(p)

# ---------------------------------------------------------------- 配对
pairs = []
pair_count_raw = 0
caution_pairs = []
for city, ps in by_city.items():
    ps.sort(key=lambda p: p["rank"])
    for i, a in enumerate(ps):
        if a["rank"] >= UNRANKED:
            continue  # 未识别源不作 A
        for b in ps:
            if b["rank"] >= a["rank"]:
                continue  # B 须严格高于 A
            if not a["cores"] or not b["cores"]:
                continue
            hit = name_match(
                a["cores"],
                b["cores"],
                a["name"],
                b["name"],
                a["name_cores"],
                b["name_cores"],
            )
            if not hit:
                continue
            hit_core, tier = hit
            dlon = abs(a["lon"] - b["lon"])
            dlat = abs(a["lat"] - b["lat"])
            if dlon > 0.5 or dlat > 0.5:  # bbox 预滤 ~50km
                continue
            dist = haversine(a["lon"], a["lat"], b["lon"], b["lat"])
            if dist <= 1000:
                continue
            pair_count_raw += 1
            # B 为区块/面实体（景区/古镇/镇/街区/遗址公园类）：子点位距中心
            # 1-5km 属合法几何，不按错针处理，打标提示人工缓判。
            b_area = bool(
                re.search(r"景区|古镇|古街|街区|镇$|遗址公园|国家公园|风景名胜", b["name"])
            ) or b["cat"] in {"ancient_town", "citywalk"}
            notes = []
            if b_area:
                notes.append("B区块")
            if a["cat"] and b["cat"] and a["cat"] != b["cat"]:
                notes.append(f"类别差{a['cat']}/{b['cat']}")
            pairs.append(
                {
                    "city": city,
                    "a": a,
                    "b": b,
                    "dist_m": dist,
                    "gap": a["rank"] - b["rank"],
                    "ct": a["ct"] or a["eff_src"] == "chinatravel",
                    "geo": bool(GEO_FEATURE_PAT.search(hit_core)),
                    "tier": tier,
                    "notes": notes,
                }
            )

# 每个 A 留最优 B：tier1 优先于 tier2，再按 gap 大、距离大
best_per_a = {}
for p in pairs:
    key = p["a"]["id"]
    cur = best_per_a.get(key)
    cand = (p["tier"] == "1", p["gap"], p["dist_m"])
    if cur is None or cand > (cur["tier"] == "1", cur["gap"], cur["dist_m"]):
        best_per_a[key] = p
dedup = sorted(
    best_per_a.values(),
    key=lambda p: (not p["ct"], p["tier"], p["city"], -p["gap"], -p["dist_m"]),
)

main_pairs = [p for p in dedup if p["tier"] == "1" and not p["geo"]]
weak_pairs = [p for p in dedup if p["tier"] == "2" and not p["geo"]]
caution_geo = [p for p in dedup if p["geo"]]

# ---------------------------------------------------------------- 输出
def fmt_pair(p):
    a, b = p["a"], p["b"]
    return (
        f"| {p['city']} | {a['name']} | {a['source']}"
        f"{'→' + a['eff_src'] if a['eff_src'] != a['source'] else ''} | `{a['spid']}` | "
        f"{a['lon']:.5f},{a['lat']:.5f} | {a['cat'] or '-'} | "
        f"{b['name']} | {b['source']} | "
        f"{b['lon']:.5f},{b['lat']:.5f} | {b['cat'] or '-'} | "
        f"{p['dist_m'] / 1000:.2f} | {p['gap']} | {'、'.join(p['notes']) or '-'} |"
    )


HDR = (
    "| 城市 | A 名（疑错针） | A source | A source_poi_id | A 坐标 | A cat "
    "| B 名（疑真实） | B source | B 坐标 | B cat | 距离km | 优先级差 | 备注 |\n"
    "|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"
)

now = datetime.now().isoformat(timespec="seconds")
ct_pairs = [p for p in main_pairs if p["ct"]]
other_pairs = [p for p in main_pairs if not p["ct"]]
weak_ct = [p for p in weak_pairs if p["ct"]]
weak_other = [p for p in weak_pairs if not p["ct"]]

md = []
md.append(f"# 错针扫描清单（2026-11-07，只读）\n")
md.append(
    "> 扫描口径：active 非 food/hotel/transport；同城、名称互含/核心相等、"
    "B 优先级严格高于 A、haversine > 1km。每 A 留最优 B（优先级差最大→距离最远）。"
    "优先级基础序 = Iron rule（app/services/source_tier.py），名录外源按 2026-11-03 "
    "拍板序插入；`ct_` 前缀 source_poi_id 行按 chinatravel 档计（事故形态）。"
    f"扫描时刻 {now}，全流程只读未写库。\n"
)
md.append(f"\n## 统计\n")
md.append(f"- 扫入池行数：{len(pool)}（active 非 food/hotel/transport，坐标非空）\n")
md.append(f"- 行级假阳性剔除：{dict(fp_skipped)}（branch/subfacility/retail/hotelish）\n")
md.append(f"- 城市（有池行）数：{len(by_city)}\n")
md.append(f"- 原始可疑对（A×B 全对，>1km）：{pair_count_raw}\n")
md.append(f"- 去重后（每 A 留一 B）：{len(dedup)}；主清单（tier1）{len(main_pairs)}"
          f"（其中 ct 形态 {len(ct_pairs)}），弱配对（tier2 仅别名命中）{len(weak_pairs)}，"
          f"地理核警示 {len(caution_geo)}\n")
md.append(f"- ct 标记行数（source_poi_id 带 ct_ 前缀）：{sum(1 for p in pool if p['ct'])}\n")
src_ct = Counter(p["source"] for p in pool if p["ct"])
md.append(f"- ct 标记行按标称 source：{dict(src_ct)}\n")
top_cities = sorted(by_city.items(), key=lambda kv: -len(kv[1]))[:8]
md.append(f"- 池行 Top 城市：{', '.join(f'{c}:{len(v)}' for c, v in top_cities)}\n")

md.append(f"\n## A. 重点：chinatravel / ct_ 形态可疑对（{len(ct_pairs)} 对）\n\n")
md.append(HDR)
for p in ct_pairs:
    md.append(fmt_pair(p) + "\n")

md.append(f"\n## B. 其他源可疑对（{len(other_pairs)} 对，按城市/优先级差/距离排）\n\n")
md.append(HDR)
for p in other_pairs:
    md.append(fmt_pair(p) + "\n")

md.append(f"\n## C. 地理核警示（山/湖/岛/河等通用地理名匹配或大范围实体，两入口可合法 >1km，{len(caution_geo)} 对）\n\n")
md.append(HDR)
for p in caution_geo:
    md.append(fmt_pair(p) + "\n")

md.append(f"\n## D. 弱配对（tier2：名称命中仅靠别名达成，须人工复核，{len(weak_pairs)} 对）\n\n")
md.append(HDR)
for p in weak_ct + weak_other:
    md.append(fmt_pair(p) + "\n")

md.append(
    "\n## 假阳性剔除与自查记录（任务第5条，一轮自查后口径收紧）\n\n"
    "- 分店/门店（`店)` 括注、分店/旗舰店/一店…）：连锁多门店合法分布，跳过。\n"
    "- 子设施词（入口/停车场/码头/索道/售票/游客中心/观景台/东西南北门/公交地铁站等）："
    "同实体附属点位天然离主点 >1km，跳过。\n"
    "- 零售词（便利店/超市/咖啡/影城/书店/银行等）与酒店词行（含公馆/山庄/度假村误标行）："
    "不属观光点池，跳过。\n"
    "- 一/二轮自查发现并已收口的误配形态（单测复核 debug 见 ops/debug 脚本，已删）：\n"
    "  1. 别名整含他馆本名——宝龙美术馆 别名「上海宝龙美术馆」整含 龙美术馆 本名、"
    "故宫钟表馆 别名「故宫博物院钟表馆」整含 故宫博物院 本名、上海自然博物馆 别名"
    "「上海科技馆分馆/自然分馆」整含 上海科技馆；修法：长核仅出自别名且（余差≤2字"
    "或短核=短核侧本名全串）→ 降弱档 §D（事故形态长核 成都武侯祠 出自 B 本名剥尾，"
    "不受影响）。\n"
    "  2. 纯馆类通名裸核——上海科技馆 别名「科技馆」配到 上海隧道科技馆；修法："
    "裸通名核（科技馆/博物馆/美术馆…无正名前缀）不参与匹配。\n"
    "  3. 双别名缩写命中——中共一大纪念馆 别名剥出「中共一大」× 中共一大会址纪念馆"
    "别名「中共一大会址纪念馆」；修法：双侧参与核均仅出自别名 → 降弱档 §D。\n"
    "  4. 过剥尾残核——上海大观园 剥出「上海大」配 上海大学博物馆；修法：参与互含"
    "的短核剥尾深度须 ≤1。\n"
    "  5. 通用地理别名——「大运河」配 5A 景区等，命中核含山/湖/岛/河等地理词归 §C。\n"
    "  6. 1 字差嵌入（龙美术馆 ⊂ 宝龙美术馆 本名层）由互含长短差 ≥2 字闸拦下；"
    "2 字残核（人民公园/人民广场 剥出「人民」）一律不认；命中核按排序取保证确定性。\n"
    "- B 为区块/面实体（名含景区/古镇/街区/镇/遗址公园或类别 ancient_town/citywalk）："
    "子点位离中心 1-5km 属合法几何，备注列打「B区块」提示缓判。\n"
    "- 跨城同名：已在同城过滤内天然排除。\n"
    "- 局限：同为低优源的同名重复行（如两条 chinatravel 同名）不在本次口径内；"
    "未识别 source 行只作 B 不作 A；城市内街区型点位（武康路 vs 武康路-安福路街区）"
    "与面实体子点（明十三陵陵寝 vs 景区中心）属于「坐标都对但相距 >1km」的合法形态，"
    "靠备注列人工缓判。\n"
)
md.append(
    "\n## 修复与回滚思路（本次未执行）\n\n"
    "1. 逐对人工确认（看 address 字段：事故形态 A 地址会落在错误街道，如锦悦西路）。\n"
    "2. 确认错针后两条路（任选，逐行执行前先 dump A/B 全字段）：\n"
    "   - 针拷贝：`UPDATE pois SET location=B.location, wgs84_location=B.wgs84_location, "
    "address=B.address, updated_at=NOW() WHERE id=A.id` —— 保留 A 行其余字段；\n"
    "   - 软删让位：`UPDATE pois SET status='inactive', updated_at=NOW() WHERE id=A.id` "
    "—— 引擎读池自动改用 B（既有口径：退役先查同城 active 同实体）。\n"
    "3. 回滚：修复前 `CREATE TABLE pois_wrongpin_bak_20261107 AS SELECT * FROM pois "
    "WHERE id IN (…A ids…)`，回滚即 `UPDATE pois SET (location, wgs84_location, address, status) "
    "= (SELECT … FROM bak) WHERE id=…` 或 `status='active'`。\n"
    "4. 若批量处置，建议像 parks 清洗一样单开 exec 脚本 + md 记录处置行与回滚语句。\n"
)

with io.open(OUT_MD, "w", encoding="utf-8", newline="\n") as f:
    f.write("".join(md))

print("== STATS ==")
print(f"pool_rows={len(pool)} cities={len(by_city)} raw_pairs={pair_count_raw} "
      f"dedup={len(dedup)} main={len(main_pairs)} ct={len(ct_pairs)} "
      f"weak={len(weak_pairs)} caution_geo={len(caution_geo)}")
print("fp_skipped:", dict(fp_skipped))
print("ct_rows_by_source:", dict(src_ct))
print("top_cities:", [(c, len(v)) for c, v in top_cities])
print("\n== TOP 30 (ct first) ==")
for p in dedup[:30]:
    a, b = p["a"], p["b"]
    flag = "CT" if p["ct"] else "  "
    src_a = a["source"] if a["eff_src"] == a["source"] else f"{a['source']}->{a['eff_src']}"
    print(
        f"[{flag}] {p['city']:6s} {p['dist_m']/1000:7.2f}km gap={p['gap']:2d} "
        f"A={a['name']}({src_a},{a['spid']},{a['lon']:.5f},{a['lat']:.5f},{a['addr'][:20]}) "
        f"B={b['name']}({b['source']},{b['lon']:.5f},{b['lat']:.5f})"
    )
print("\nmd written:", OUT_MD)
