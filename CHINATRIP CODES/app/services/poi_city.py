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
import re
import threading
from pathlib import Path

_INDEX_PATH = Path(__file__).resolve().parent / "data" / "city_index.json"

_KNOWN_BY_LEN: tuple[str, ...] | None = None
_INDEX: dict | None = None
_PREF_FULL: dict[str, str] | None = None  # 地级全名 → canonical 短名（跨省）
_PREF_SHORT: dict[str, str] | None = None  # 地级短名 → canonical 短名
_LOCK = threading.Lock()

# 非官方双字缩写（官方短名规则覆盖不到的自治州俗称）。官方口径见
# `canonical_city` 的后缀剥离；这里只补「巴州/博州/克州」三种。
_ABBREV_ALIASES: dict[str, str] = {
    "巴州": "巴音郭楞",
    "博州": "博尔塔拉",
    "克州": "克孜勒苏",
}

_HEAD_RE = re.compile(r"^([\u4e00-\u9fa5]{2,6})(地区|县|市|旗|盟|区)")
_ADMIN_UNITS = ("省", "壮族自治区", "回族自治区", "维吾尔自治区", "自治区")


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


def known_prefectures() -> frozenset[str]:
    """全部 canonical 城市名（注册 226 + 各省地级短名）。"""
    _, pref_short = _pref_maps()
    return frozenset(pref_short.values())


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
    if s in pref_short:
        return pref_short[s]
    return s


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
    if not prov:
        return None
    entry = _index().get(prov)
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
    return None


def resolve_city(province: str | None, text: str) -> str | None:
    """从「省份 + 自由文本（address/locality）」解析地级城市.

    步骤：1 注册表名全文命中（最长优先，`景德镇市`→景德镇）；2 省级直接
    城市（直辖市）；3-6 见 `_resolve`。识别不了返回 None.
    """
    t = (text or "").strip()
    if not t:
        return None
    for name in _known_sorted():
        if name in t:
            return canonical_city(name)
    return _resolve(_province_of(province, t), t)
