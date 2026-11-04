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
    """注册表城市名，长名优先（「阿拉善盟」压过「阿拉善」，避免误剥盟后缀）。

    同长度按字典序兜底：`sorted(frozenset, key=len)` 的同长顺序取决于
    str hash 随机化，跨进程会翻转（`长春市朝阳区…` 里「长春」/「朝阳」都
    是 2 字子串 → city 随机），必须给确定的全序.
    """
    global _KNOWN_BY_LEN
    if _KNOWN_BY_LEN is None:
        from app.services.agent.plan import KNOWN_CITIES

        _KNOWN_BY_LEN = tuple(
            sorted(frozenset(KNOWN_CITIES), key=lambda s: (-len(s), s))
        )
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


_COUNTY_EXACT: dict[str, str] | None = None
_COUNTY_FULL_SORTED: list[tuple[str, str]] | None = None
_COUNTY_SUFFIXES = ("市", "县", "区", "旗")


def _county_exact_map() -> dict[str, str]:
    """全库县级单位「全名 / 裸 stem」→ 属地级市；跨省同名冲突则丢.

    只服务**整串相等**匹配（`city` 列遗留值 `太仓`/`邛崃`/`孟连县`），
    不做子串——子串路径见 `_global_county_fallback`（避免「沙溪镇」被
    外省同名镇吞掉）.

    裸 stem 一律让位给省/地级名：`河北`（河北区,天津）与 `河南`（河南
    蒙古族自治县,黄南）会被省名撞车，省名输入必须保持「不是城市」。
    """
    global _COUNTY_EXACT
    if _COUNTY_EXACT is None:
        higher: set[str] = set(_index())
        for entry in _index().values():
            higher.update(entry["prefectures"])
            higher.update(entry["prefectures"].values())
        higher.update(_known_sorted())
        spots: dict[str, dict[str, str]] = {}
        for _prov, entry in _index().items():
            for county, city in entry["counties"].items():
                spots.setdefault(county, {})[city] = city
                stem = _strip_admin_suffixes(county)
                if len(stem) >= 2 and stem not in higher:
                    spots.setdefault(stem, {})[city] = city
        _COUNTY_EXACT = {
            name: next(iter(spot)) for name, spot in spots.items() if len(spot) == 1
        }
    return _COUNTY_EXACT


def _exact_county_city(t: str) -> str | None:
    """整串等于县级单位名/stem 时上卷（`太仓`→苏州、`孟连县`→普洱）."""
    m = _county_exact_map()
    if t in m:
        return m[t]
    stem = _strip_admin_suffixes(t)
    if stem != t:
        return m.get(stem)
    return None


def _county_full_sorted() -> list[tuple[str, str]]:
    """带显式行划后缀的县级全名（长名优先，跨省冲突丢），供名称前缀
    识别（`滕州市汉画像石馆`→枣庄）."""
    global _COUNTY_FULL_SORTED
    if _COUNTY_FULL_SORTED is None:
        spots: dict[str, dict[str, str]] = {}
        for _prov, entry in _index().items():
            for county, city in entry["counties"].items():
                if county.endswith(_COUNTY_SUFFIXES):
                    spots.setdefault(county, {})[city] = city
        _COUNTY_FULL_SORTED = sorted(
            (
                (name, next(iter(spot)))
                for name, spot in spots.items()
                if len(spot) == 1
            ),
            key=lambda kv: len(kv[0]),
            reverse=True,
        )
    return _COUNTY_FULL_SORTED


_NAME_ADMIN_TAIL = ("市", "区", "县", "州", "旗", "盟")

# 「城市名 + 大学/学院」：校名多为历史命名（中山大学在广州、同济在上海），
# 相邻出现时不能当属地证据，直接跳过（`武汉大学万林艺术博物馆` 因此留在
# 未解析池，宁可漏判不可错判）.
_NAME_SCHOOL_HEADS = ("大学", "学院", "中学", "小学")

# 与常用词同形的县/区名 stem（`郑州市中原区`、`桂林市资源县`），出现在馆名
# 里是构词而非地名（`中原军区…旧址陈列馆`、`广西自然资源档案博物馆`）。
# 口径同 `_NAME_SCHOOL_HEADS`：宁可漏判不可错判.
_GENERIC_COUNTY_STEMS = frozenset({"中原", "资源"})

# 汉字（用于「地名前只允许数字/标点前缀」判定：`5·12汶川…`）
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

# 「县级 stem + 乡村级通名」整名（`赤坎镇`/`芙蓉镇`/`大通镇`/`三门源村`）：
# 这类 POI 本身就是乡镇村名，与「县名打头的馆名」不同，stem 撞上同名的区县
# 会指到隔壁地级市（`赤坎镇` 在江门开平，却被 `赤坎区`→湛江 吃掉）。
_SUBCOUNTY_TAILS = ("镇", "乡", "街道", "村")

_COUNTY_STEM_SORTED: dict[str, list[tuple[str, str]]] = {}


def _county_stem_sorted(prov: str) -> list[tuple[str, str]]:
    """本省县级名 stem（长名优先、同 stem 冲突丢），供名称内任意位置识别.

    与 `_county_hit`（要求带行划后缀的县级全名，如 `青州市`）互补：馆名常只
    写 stem（`青州未央红丝砚博物馆`→潍坊、`番禺博物馆`→广州）。stem 与本省
    或全局注册城市/地级名同形时让位（`朝阳` 是地级市，不能当北京朝阳区的
    证据），常用词 stem 见 `_GENERIC_COUNTY_STEMS`.
    """
    items = _COUNTY_STEM_SORTED.get(prov)
    if items is None:
        entry = _index().get(prov) or {}
        higher: set[str] = set(_index())
        higher.update(_known_sorted())
        prefs = entry.get("prefectures") or {}
        higher.update(prefs)
        higher.update(prefs.values())
        spots: dict[str, dict[str, str]] = {}
        for county, city in (entry.get("counties") or {}).items():
            stem = _strip_admin_suffixes(county)
            if len(stem) < 2 or stem in higher or stem in _GENERIC_COUNTY_STEMS:
                continue
            spots.setdefault(stem, {})[city] = city
        items = sorted(
            ((stem, next(iter(c))) for stem, c in spots.items() if len(c) == 1),
            key=lambda kv: (-len(kv[0]), kv[0]),
        )
        _COUNTY_STEM_SORTED[prov] = items
    return items


_CITY_PROVINCE: dict[str, str] | None = None


_MUNICIPALITIES = frozenset({"北京", "上海", "天津", "重庆"})

# 特别行政区：不在区划索引里，但注册表收作 canonical 城市（按城查池可用）.
_SARS = frozenset({"香港", "澳门"})


def _city_province() -> dict[str, str]:
    """canonical 城市 → 省级短名（直辖市/特别行政区映射到自身）.

    县级市/县级区名本身是注册城市时（曲阜/桐乡/东阳/青州…）必须能取到省，
    否则 `city_from_name` 的省份闸（`_ok`）会把这些城市在**任何**省语境下
    拒掉——历史上 42 家旅游县级市因此永远解析不到（`曲阜汉画艺术博物馆`
    →None）。索引里它们挂在某个地级市下，但注册表把它们当独立「按城查池」
    键，故这里按县级 stem 补映射；只接受跨省唯一 stem（`朝阳` 这类同名
    既可能是辽宁地级市又可能是北京朝阳区，冲突即丢）.
    """
    global _CITY_PROVINCE
    if _CITY_PROVINCE is None:
        known = known_cities()
        m: dict[str, str] = {}
        for prov, entry in _index().items():
            if prov in _MUNICIPALITIES:
                m.setdefault(prov, prov)
            for city in entry["prefectures"].values():
                m.setdefault(city, prov)
            for city in entry["counties"].values():
                m.setdefault(city, prov)
        stems: dict[str, set[str]] = {}
        for prov, entry in _index().items():
            for county in entry["counties"]:
                stem = _strip_admin_suffixes(county)
                if len(stem) >= 2 and stem in known:
                    stems.setdefault(stem, set()).add(prov)
        for stem, provs in sorted(stems.items()):
            # 跨省同名县级 stem（`朝阳`：辽宁地级市 / 北京朝阳区）不猜
            if len(provs) == 1:
                m.setdefault(stem, next(iter(provs)))
        for sar in sorted(_SARS & known):
            m.setdefault(sar, sar)
        _CITY_PROVINCE = m
    return _CITY_PROVINCE


def city_from_name(name: str, province: str | None = None) -> str | None:
    """POI 名称 → canonical 城市（保守：只认可证前缀）.

    默认（无 province）仅认两种形态：
    1) 「已知城市 + 市/区/县/州/旗/盟」开头：`宁波市天一阁博物院`→宁波、
       `重庆市江北区观音桥…`→重庆；
    2) 「索引县级全名（带后缀）」开头：`滕州市汉画像石馆`→枣庄。
    名称首段没有行政后缀时一律 None——`中山舰博物馆`（武汉）、`北海公园`
    （北京）、`东方明珠`（上海）不因含同名城市被误判.

    传入 province 时追加第 3 条：`已知城市 + 任意通名`（`桂林博物馆`→
    桂林、`南京中国科举博物馆`→南京），但要求解析城市**属于该省**；跨省
    同名（`北海公园` 记为北京）、校名相邻（`中山大学博物馆` 在广东）直接
    拒绝。省名未知（如 `江北区`）时该规则不启用.
    """
    s = (name or "").strip()
    if not s:
        return None
    known = known_cities()
    prov = _province_short(province.strip()) if province else None
    if prov is not None and prov not in _index():
        prov = None  # 传进来的不是省名（区县/园区名），不启用第 3 条

    # 「X省 + 后续地名」体例（街区名录常见：`吉林省长春市朝阳区…`）：
    # 省名本身不是城市归属，剥掉后按省份语境继续解析.
    for _p, fulls in _province_short_map().items():
        for cand in fulls:
            if len(cand) >= 2 and s.startswith(cand + "省"):
                rest = s[len(cand) + 1 :]
                if rest:
                    return resolve_city(_p, rest) or city_from_name(rest, _p)

    def _ok(canon: str) -> str | None:
        if canon not in known:
            return None
        if prov is not None and _city_province().get(canon) != prov:
            return None
        return canon

    for city_name in _known_sorted():
        for tail in _NAME_ADMIN_TAIL:
            if s.startswith(city_name + tail):
                hit = _ok(canonical_city(city_name))
                if hit:
                    return hit
    for county, city in _county_full_sorted():
        if s.startswith(county):
            hit = _ok(city)
            if hit:
                return hit
    if prov is not None:
        for city_name in _known_sorted():
            if not s.startswith(city_name):
                continue
            rest = s[len(city_name) :]
            if not rest or rest.startswith(_NAME_SCHOOL_HEADS):
                continue
            hit = _ok(canonical_city(city_name))
            if hit:
                return hit
        # 「省短名/全名 + 后续地名」体例（`内蒙古乌海博物馆`、`新疆喀什地区
        # 博物馆`）：省名不是城市归属，剥掉后按省级语境重解析；余段以行划后缀
        # 开头时不动——`吉林市博物馆`/`海南州…` 里的 吉林/海南 是城市名.
        for cand in _province_short_map().get(prov, ()):
            if len(cand) < 2 or not s.startswith(cand):
                continue
            rest = s[len(cand) :]
            if not rest or rest.startswith(_NAME_ADMIN_TAIL):
                continue
            return resolve_city(prov, rest) or city_from_name(rest, prov)
        # 本省县级 stem 打头（`番禺博物馆`→广州、`汶川特大地震纪念馆`→阿坝）
        # 或仅被数字/标点前缀隔开（`5·12汶川特大地震纪念馆`）。**不放行任意
        # 位置**：句中 2 字 stem 会跨词误拼（`某馆|南山|路` 之类）；句中带
        # 行划后缀的县级全名由 `resolve_city`/`_county_hit` 负责。
        for stem, city in _county_stem_sorted(prov):
            pos = s.find(stem)
            if pos < 0:
                continue
            if pos and _CJK_RE.search(s[:pos]):
                continue
            rest = s[pos + len(stem) :]
            # 裸区县名（`鼓楼`/`南山`：多城共有的地名，不是归属证据）
            if not rest:
                continue
            if rest.startswith(_NAME_SCHOOL_HEADS):
                continue
            # 整名就是「stem + 乡镇村通名」（`赤坎镇`）→ 不是馆名/景区名，
            # 县级同名不足为凭，宁可漏判
            if rest in _SUBCOUNTY_TAILS:
                continue
            hit = _ok(city)
            if hit:
                return hit
    return None


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

    步骤：1 旧书写别名（高新区/管委会/直辖县级市短写——特定串优先于
    泛化注册表子串，否则「长白山管委会池北区」会被新注册的「白山」
    子串抢中，扩表批次 3 回归）；2 注册表名全文命中（最长优先，
    `景德镇市`→景德镇）；3 直辖市；4-8 见 `_resolve`；最后跨省县名兜底.
    """
    t = (text or "").strip()
    if not t:
        return None
    # ≤2 字别名只做全等（「陵」子串会命中一切），≥3 字用包含.
    for old, city in _CITY_ALIASES_EXTRA.items():
        if t == old or (len(old) > 2 and old in t):
            return city
    # 名称子串：取**出现位置最靠前**的（同位置取更长），否则
    # 「长春市朝阳区…」会被 2 字的「朝阳」（朝阳市/辽宁）抢中.
    best_pos = -1
    best_len = 0
    best_city: str | None = None
    for name in _known_sorted():
        pos = t.find(name)
        if pos < 0:
            continue
        if (
            best_city is None
            or pos < best_pos
            or (pos == best_pos and len(name) > best_len)
        ):
            best_pos, best_len = pos, len(name)
            best_city = canonical_city(name)
    if best_city is not None:
        return best_city
    hit = _resolve(_province_of(province, t), t)
    if hit:
        return hit
    # 6b) 整串县级单位（city 列遗留值 `太仓`→苏州、`孟连县`→普洱）
    hit = _exact_county_city(t)
    if hit:
        return hit
    hit = _global_county_fallback(t)
    if hit:
        return hit
    # 7) 省外裸地级串（normalize 第二遍的「烟台市 / 迪庆州」）：canonical
    # 层认识就直接给；不认识（原样返回）则按 None 保守处理.
    canon = canonical_city(t)
    return canon if canon != t else None
