"""POI 城市解析器（backlog P2：07 国保/06 名村/03 遗址公园无 city 列）.

城市口径：canonical = `app.services.weather.CITY_ADCODES`（=
`plan.KNOWN_CITIES`，226 座旅游城市）的注册短名；注册表外的地级市用同
一套「短名」规则（去 市/地区/盟，自治州削民族限定，生成器在
``ops/build_city_index.py``）。县/区/县级市一律上卷到属地级市。

索引 ``app/services/data/city_index.json`` 由 build_city_index.py 离线生成
（GB/T 2260 三级区划，源 CSV 存 ``DESIGN/POIS DATASOURCE/_src/``）；文件
缺失时退化为仅注册表匹配（解析器不抛异常，导入侧按 None 记 miss）。

全部纯字符串匹配、零网络、零 API 配额."""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

_INDEX_PATH = Path(__file__).resolve().parent / "data" / "city_index.json"

_KNOWN_BY_LEN: tuple[str, ...] | None = None
_INDEX: dict | None = None
_PREF_FULL: dict[str, str] | None = None  # 地级全名 → canonical 短名（跨省）
_PREF_SHORT: dict[str, str] | None = None  # 地级短名 → canonical 短名
_LOCK = threading.RLock()  # 可重入：_pref_maps 锁内还会走 _index 的锁

# 非官方双字缩写（官方短名规则覆盖不到的自治州俗称）。官方口径见
# `canonical_city` 的后缀剥离；这里只补「巴州/博州/克州」三种。
_ABBREV_ALIASES: dict[str, str] = {
    "巴州": "巴音郭楞",
    "博州": "博尔塔拉",
    "克州": "克孜勒苏",
}

# 旧库遗留书写（区划索引/变体规则覆盖不到 County-level names / 高新区），
# 归一到 canonical 短名. 2026-11-01 legacy 清点.
_CITY_ALIASES_EXTRA: dict[str, str] = {
    "二连浩特": "锡林郭勒",
    "神农架": "神农架林区",
    "格尔木": "海西",
    "梅河口": "通化",
    "汝州": "平顶山",
    "巩义": "郑州",
    "邓州": "南阳",
    "平潭": "福州",
    "玉林北流": "玉林",
    "石家庄高新区": "石家庄",
    "杨凌示范区": "咸阳",
    "济源示范区": "济源",
    "长白山管委会池北区": "延边",
    "长白山管委会池南区": "白山",
    "韩城": "渭南",
    "陵": "陵水",  # 旧生成器 bug 残值（黎族自治县短写）
    "大通县": "西宁",  # 青海大通县旧称（淮南同名为 区，不冲突）
}

_HEAD_RE = re.compile(r"^([\u4e00-\u9fa5]{2,6})(地区|县|市|旗|盟|区)")
_ADMIN_UNITS = ("省", "壮族自治区", "回族自治区", "维吾尔自治区", "自治区")

# 民族片段（长名优先），把「务川仡佬族苗族自治县」削成「务川」.
_ETHNIC = (
    "维吾尔",
    "柯尔克孜",
    "乌孜别克",
    "哈萨克",
    "塔吉克",
    "塔塔尔",
    "达斡尔",
    "鄂温克",
    "鄂伦春",
    "朝鲜",
    "俄罗斯",
    "蒙古",
    "土家",
    "布依",
    "哈尼",
    "傈僳",
    "拉祜",
    "纳西",
    "景颇",
    "仡佬",
    "仫佬",
    "毛南",
    "阿昌",
    "普米",
    "独龙",
    "裕固",
    "撒拉",
    "东乡",
    "保安",
    "锡伯",
    "德昂",
    "基诺",
    "门巴",
    "珞巴",
    "赫哲",
    "回",
    "藏",
    "苗",
    "彝",
    "壮",
    "侗",
    "瑶",
    "白",
    "傣",
    "黎",
    "佤",
    "畲",
    "水",
    "土",
    "羌",
    "怒",
    "京",
    "满",
)
_ETHNIC_SORTED = tuple(sorted(_ETHNIC, key=len, reverse=True))


def _known_sorted() -> tuple[str, ...]:
    """注册表城市名，长名优先（「阿拉善盟」压过「阿拉善」，避免误剥盟后缀）。"""
    global _KNOWN_BY_LEN
    if _KNOWN_BY_LEN is None:
        from app.services.agent.plan import KNOWN_CITIES

        _KNOWN_BY_LEN = tuple(sorted(frozenset(KNOWN_CITIES), key=len, reverse=True))
    return _KNOWN_BY_LEN


def _index() -> dict:
    """区划索引；缺失/损坏时返回空表（解析退化为仅注册表）。"""
    global _INDEX
    with _LOCK:
        if _INDEX is None:
            try:
                data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
                provinces = data.get("provinces") or {}
            except (OSError, ValueError):
                provinces = {}
                # 静默回退会无痕缩小 known_cities/解析集，按项目规则留痕
                # （_INDEX 缓存后仅记一次）.
                logger.warning(
                    "city_index.json 缺失/不可读，回退仅注册表（226 城）: %s",
                    _INDEX_PATH,
                )
            _INDEX = provinces
    return _INDEX


def _build_pref_maps() -> None:
    """跨省地级映射：级全名 → canonical 短名（`阿坝藏族羌族自治州`→阿坝）
    ＋ canonical 短名 identity 表（供 `阿坝州`/`湘西州` 剥后缀兜底）.
    """
    global _PREF_FULL, _PREF_SHORT
    full: dict[str, str] = {}
    canon_set: set[str] = set()
    for entry in _index().values():
        for key, canon in entry["prefectures"].items():
            if key != canon:
                full.setdefault(key, canon)
            canon_set.add(canon)
    _PREF_FULL, _PREF_SHORT = full, {c: c for c in canon_set}


def _pref_maps() -> tuple[dict[str, str], dict[str, str]]:
    if _PREF_FULL is None or _PREF_SHORT is None:
        with _LOCK:
            if _PREF_FULL is None or _PREF_SHORT is None:
                _build_pref_maps()
    return _PREF_FULL, _PREF_SHORT  # type: ignore[return-value]


def known_cities() -> frozenset[str]:
    """全部可作为 canonical 城市名的集合：注册 226（含县级旅游城市如
    五大连池/井冈山/神农架林区）＋各地级短名＋直辖市."""
    global _KNOWN_ALL
    if _KNOWN_ALL is None:
        from app.services.agent.plan import KNOWN_CITIES

        canon_set: set[str] = set(KNOWN_CITIES)
        for entry in _index().values():
            canon_set.update(entry["prefectures"].values())
            canon_set.update(entry["counties"].values())
        _KNOWN_ALL = frozenset(canon_set)
    return _KNOWN_ALL


known_prefectures = known_cities  # 旧称兼容（下游脚本用旧名）


_KNOWN_ALL: frozenset[str] | None = None


def _province_short(name: str) -> str:
    """省级全名 → 短名（`广西壮族自治区`→广西）。不能用民族语剥法，否则
    `内蒙古/西藏/贵州` 会被削成 `内/西/贵`。"""
    for suf in _ADMIN_UNITS:
        if name.endswith(suf):
            return name[: -len(suf)]
    return name


def _province_of(province: str | None, text: str) -> str | None:
    """识别给定 text（含省全名/短名）或 province 参数的省级短名。"""
    if province:
        prov = _province_short(province.strip())
        if prov in _index() or prov in _province_short_map():
            return prov
    matches: list[str] = []
    short_map = _province_short_map()
    for prov, fulls in short_map.items():
        for cand in fulls:
            if cand and cand in text:
                matches.append((len(cand), prov))  # type: ignore[misc]
    if matches:
        matches.sort(reverse=True)  # 全名（长）优先于 短名
        return matches[0][1]
    return None


def _province_short_map() -> dict[str, tuple[str, ...]]:
    """省级短名 → 可匹配文本（短名 + 全名）。"""
    global _PROV_MAP
    if _PROV_MAP is None:
        m: dict[str, list[str]] = {}
        for short, entry in _index().items():
            full = entry.get("full") or ""
            m.setdefault(
                short,
                ({short, full} if full != short else {short}),  # type: ignore[arg-type]
            )
        _PROV_MAP = {k: tuple(sorted(v, key=len, reverse=True)) for k, v in m.items()}
    return _PROV_MAP


_PROV_MAP: dict[str, tuple[str, ...]] | None = None


def canonical_city(name: str) -> str:
    """「城市名」字符串 → canonical 短名（不认识就原样返回）.

    覆盖注册名（`西安`），注册市全名（`西安市`→西安）、特别行政区全称
    （`澳门特别行政区`→澳门）、自治州全名（`阿坝藏族羌族自治州`→`阿坝`）、
    后缀变体（`阿坝州`→`阿坝`、`阿克苏地区`→`阿克苏`、`锡林郭勒盟`→
    `锡林郭勒`）、非官方缩写（`巴州`→`巴音郭楞`）。
    """
    s = (name or "").strip()
    if not s:
        return s
    known = _known_sorted()
    if s in known:
        return s
    pref_full, pref_short = _pref_maps()
    if s in pref_full:
        return pref_full[s]
    if s == "特别行政区" or s.endswith("特别行政区"):
        s2 = s[: -len("特别行政区")]
        if s2 in known or s2 in pref_short:
            return pref_short.get(s2, s2)
        return s2
    for suf in ("市", "地区", "盟", "州"):
        if s.endswith(suf) and len(s) > len(suf):
            base = s[: -len(suf)]
            if base in known or base in pref_short:
                return pref_short.get(base, base)
            break
    for abbr, canon in _ABBREV_ALIASES.items():
        if s == abbr:
            return canon
    if s in _CITY_ALIASES_EXTRA:
        return _CITY_ALIASES_EXTRA[s]
    if s in pref_short:
        return pref_short[s]
    return s


def _strip_admin_suffixes(name: str) -> str:
    """县级名剥行划后缀 + 民族片段：`凤翔区`→凤翔、
    `巍山彝族回族自治县`→巍山（撤并改名口径兜底用）."""
    stem = name
    changed = True
    while changed:
        changed = False
        for suf in ("自治县", "自治旗", "自治州", "自治区", "特别行政区"):
            if stem.endswith(suf) and len(stem) > len(suf):
                stem = stem[: -len(suf)]
                changed = True
        for eth in _ETHNIC_SORTED:
            if stem.endswith(eth + "族") and len(stem) > len(eth) + 1:
                stem = stem[: -len(eth) - 1]
                changed = True
    for suf in ("区", "县", "市", "旗"):
        if stem.endswith(suf) and len(stem) > len(suf):
            return stem[: -len(suf)]
    return stem


# 单字 stem 县（变体规则 len>=2 覆盖不到）等个别历史书写.
_RENAMED_COUNTY_ALIASES: dict[str, str] = {"沙县": "三明"}


_COUNTY_VARIANTS: dict[str, dict[str, str]] = {}
_GLOBAL_COUNTY: list[tuple[str, str]] | None = None  # 全库县名（长名优先）


def _county_variants(prov: str, entry: dict) -> dict[str, str]:
    """旧县级名 → 属地级市（撤并改名：index 现名 凤翔区/偃师区/繁昌区 的
    旧书写 凤翔县/偃师市/繁昌县）。同省同 stem 冲突则丢."""
    cached = _COUNTY_VARIANTS.get(prov)
    if cached is not None:
        return cached
    spots: dict[str, dict[str, str]] = {}
    for county, city in entry["counties"].items():
        stem = _strip_admin_suffixes(county)
        if len(stem) < 2:
            continue
        # 裸 stem 不入变体（「涪陵区青羊镇」会被 成都青羊 误吞），只认
        # 带 行划后缀 的旧写法.
        for v in {stem + "县", stem + "市", stem + "旗"}:
            if v not in entry["counties"]:
                spots.setdefault(v, {})[city] = city
    flat = {name: next(iter(spot)) for name, spot in spots.items() if len(spot) == 1}
    _COUNTY_VARIANTS[prov] = flat
    return flat


def _global_county_sorted() -> list[tuple[str, str]]:
    """全库县名（仅索引现名），长名优先；跨省同 key 冲突则丢.

    故意**不含**省scoped 变体：'大通县'在青海(西宁)和淮南(大通区)各有一份
    旧写法，全局无省上下文时无法裁决——那种走 resolve_city 的省分支.
    """
    global _GLOBAL_COUNTY
    if _GLOBAL_COUNTY is None:
        spots: dict[str, dict[str, str]] = {}
        for _prov, entry in _index().items():
            for county, city in entry["counties"].items():
                spots.setdefault(county, {})[city] = city
        _GLOBAL_COUNTY = sorted(
            (
                (name, next(iter(spot)))
                for name, spot in spots.items()
                if len(spot) == 1
            ),
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
    return _GLOBAL_COUNTY


_COUNTY_SORTED: dict[str, list[tuple[str, str]]] = {}
_PREF_SORTED: dict[str, list[tuple[str, str]]] = {}


def _county_hit(prov: str, entry: dict, text: str) -> str | None:
    """同省县级名上卷：任一县级名出现在 text（最长优先），返回属地级
    canonical。省划撤并（如 邢台县→襄都区）导致的旧县名不在索引内，由
    resolve_city 的首段兜底处理."""
    items = _COUNTY_SORTED.get(prov)
    if items is None:
        items = sorted(
            entry["counties"].items(), key=lambda kv: len(kv[0]), reverse=True
        )
        _COUNTY_SORTED[prov] = items
    for county, city in items:
        if county in text:
            return city
    return None


def _resolve(prov: str | None, t: str) -> str | None:
    entry = _index().get(prov) if prov else None
    if entry is None:
        return None
    if prov in {"北京", "上海", "天津", "重庆"}:
        return prov
    items = _PREF_SORTED.get(prov)
    if items is None:
        items = sorted(
            entry["prefectures"].items(), key=lambda kv: len(kv[0]), reverse=True
        )
        _PREF_SORTED[prov] = items
    # 3) 同省地级前缀（「张家口市崇礼区」→张家口）
    for full, canon in items:
        if (t.startswith(full) or t.startswith(canon)) and (full in t or canon in t):
            return canon
    # 4) 同省县级名上卷（「怀来县鸡鸣驿乡」→张家口）
    county_city = _county_hit(prov, entry, t)
    if county_city:
        return county_city
    # 4b) 同省旧县名后缀变体（撤并改名：凤翔县→凤翔区）
    for old, city in sorted(
        _county_variants(prov, entry).items(), key=lambda kv: len(kv[0]), reverse=True
    ):
        if old in t:
            return city
    # 4c) 个别历史 county 别名（单字 stem 变体规则覆盖不到）
    for old, city in _RENAMED_COUNTY_ALIASES.items():
        if old in t:
            return city
    # 5) 首段县级行政名按同省地级短名识别（邢台县 2020 撤并后索引无此县）
    head = _HEAD_RE.match(t)
    if head:
        stem = head.group(1)
        if stem in entry["prefectures"]:
            return entry["prefectures"][stem]
    # 6) 同省地级短名子串兜底（「四川省阿坝州…」类写法）
    for _full, canon in items:
        if len(canon) >= 2 and canon in t:
            return canon
    return _global_county_fallback(t)


def _global_county_fallback(t: str) -> str | None:
    """跨省县名兜底（省划迁管，如 四川 claim 下的 涪陵区→重庆）。仅在最
    后接手，同 key 跨省冲突的县不参与（_global_county_sorted 已过滤）."""
    for name, city in _global_county_sorted():
        if name in t:
            return city
    return None


def resolve_city(province: str | None, text: str) -> str | None:
    """从「省份 + 自由文本（address/locality）」解析地级城市.

    步骤：1 注册表名全文命中（最长优先，`景德镇市`→景德镇）；2 直辖市；
    2a 旧书写别名；3-6 见 `_resolve`；最后跨省县名兜底.
    """
    t = (text or "").strip()
    if not t:
        return None
    for name in _known_sorted():
        if name in t:
            return canonical_city(name)
    # 2a) 旧库遗留书写（高新区/管委会/直辖县级市短写；无省也能命中）
    # ≤2 字别名只做全等（「陵」子串会命中一切），≥3 字用包含.
    for old, city in _CITY_ALIASES_EXTRA.items():
        if t == old or (len(old) > 2 and old in t):
            return city
    hit = _resolve(_province_of(province, t), t)
    if hit:
        return hit
    hit = _global_county_fallback(t)
    if hit:
        return hit
    # 7) 省外裸地级串（normalize 第二遍的「烟台市 / 迪庆州」）：canonical
    # 层认识就直接给；不认识（原样返回）则按 None 保守处理.
    canon = canonical_city(t)
    return canon if canon != t else None
