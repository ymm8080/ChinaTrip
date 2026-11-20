# -*- coding: utf-8 -*-
"""Same-visit twin detection for the CP-SAT engine (R13h).

Legacy ``agent/plan.py`` 携带一套同站孪生判定（_same_visit 通道族：用户
拍板链 2026-10-31 石窟双卡 → 11-01 兵马俑同票 → 11-03 大小兄弟 →
11-04 联票/遗址公园 → 11-07 博物馆×伞形组合豁免 → 11-16 朱家角同地名
→ 11-17 万国建筑包含对）。引擎此前一个通道都没移植——多源同行
（朱家角古镇/朱家角镇、都江堰景区/青城山都江堰旅游景区）会在池里
并存、跨天双卡（live 实锤：武侯祠·锦里 与 成都武侯祠博物馆 同日两卡；
朱家角类同地名行是引擎独有暴露面）。本模块把判定按当日口径原样
移植成纯函数（名字/坐标谓词，零 legacy 依赖），供模型层互斥约束
（c09_c16._r13h_twin_exclusivity）消费。

通道→地理闸分档（与 legacy _same_visit 同表）：
    poi_id 相等            → 无条件
    同内容配套 _content_dup → 30km
    同票家族 _heritage_dup /
    遗址公园 _relic_park_dup → 10km
    大小兄弟 _sibling_dup   → 30km（餐饮/演出/酒店/交通豁免）
    「·」联票 _composite_dup → 2.5km（单侧博物馆对豁免——11-07 终裁
                              「博物馆×伞形景区对还原多卡连排成组」）
    包含 containment /
    同地名 _town_dup /
    演出桶 _show_dup        → 2km

双方有坐标且相距 > 闸 = 名字撞衫的不同场馆不并；缺坐标维持名字判定
（legacy 同口径）。餐饮/演出×街区身份劈叉不并（11-08 街区拍板）。
"""

from __future__ import annotations

import re

from app.services.poi_names import place_core
from app.services.trip_orchestrator.nlu import (
    _SITE_NAME_JUNK,
    _SITE_TAILS,
    _STREET_DISTRICT_RE,
    _norm_site_name,
)

# ---- legacy 常量（当日口径原样移植；来源注释见 agent/plan.py） ----
_DISTRICT_PREFIX_RE = re.compile(r"^[\u4e00-\u9fa5]{1,3}[区县]")

_FACILITY_TAILS: tuple[str, ...] = (
    "数字影院",
    "电影院",
    "影院",
    "博物馆",
    "纪念馆",
    "陈列馆",
    "美术馆",
    "游客中心",
)

_MUSEUM_NAME_TAILS = ("博物馆", "博物院", "纪念馆")

_UMBRELLA_SCENIC_EXEMPT_CATEGORIES = {
    "food",
    "entertainment",
    "hotel",
    "transport",
}

_SIBLING_SIZE_PREFIX = ("大", "小")

_SHOW_DUP_KEYS: tuple[str, ...] = ("变脸", "川剧", "蜀风雅韵")
_SHOW_DUP_GUARD = ("博物馆", "纪念馆", "陈列馆", "美术馆", "故居", "书院")

_HERITAGE_DUP_FAMILIES: tuple[tuple[str, ...], ...] = (
    ("兵马俑", "秦始皇陵", "秦始皇帝陵"),
    ("华清宫", "华清池"),
)

_RELIC_PARK_MARK = "考古遗址公园"

_COMPOSITE_SPLIT_RE = re.compile(r"[·•・‧]")
_COMPOSITE_SEG_STOP = {"文化", "历史", "旅游", "生态", "休闲", "度假", "公园"}

GATE_CONTENT_KM = 30.0
GATE_HERITAGE_KM = 10.0
GATE_SIBLING_KM = 30.0
GATE_COMPOSITE_KM = 2.5
GATE_TIGHT_KM = 2.0


# ---- 名字谓词（legacy 纯函数当日原样） ----
def _same_site(a: str, b: str) -> bool:
    na, nb = _norm_site_name(a), _norm_site_name(b)
    if not na or not nb:
        return na == nb
    return na == nb or ((na in nb or nb in na) and min(len(na), len(nb)) >= 2)


def _content_core(name: str) -> tuple[str, bool]:
    junk_only = re.sub(_SITE_NAME_JUNK, "", name or "")
    core = _norm_site_name(name)
    stripped = False
    m = _DISTRICT_PREFIX_RE.match(core)
    if m and len(core) - m.end() >= 4:
        core = core[m.end() :]
        stripped = True
    changed = True
    while changed:
        changed = False
        for tail in (*_FACILITY_TAILS, *_SITE_TAILS):
            if core.endswith(tail) and len(core) - len(tail) >= 3:
                core = core[: -len(tail)]
                changed = True
    if core != junk_only:
        stripped = True
    return core, stripped


def _content_dup(a: str, b: str) -> bool:
    """同内容配套场馆：至少一侧剥出设施词（双侧裸名交给 containment），
    核心词相等（≥3 字）即同内容。"""
    ca, sa = _content_core(a)
    cb, sb = _content_core(b)
    if not (sa or sb):
        return False
    return len(ca) >= 3 and ca == cb


def _show_bucket(name: str) -> bool:
    s = name or ""
    if any(g in s for g in _SHOW_DUP_GUARD):
        return False
    return any(k in s for k in _SHOW_DUP_KEYS)


def _show_dup(a: str, b: str) -> bool:
    return _show_bucket(a) and _show_bucket(b)


def _heritage_dup(a: str, b: str) -> bool:
    for fam in _HERITAGE_DUP_FAMILIES:
        if any(k in (a or "") for k in fam) and any(k in (b or "") for k in fam):
            return True
    return False


def _relic_park_dup(a: str, b: str) -> bool:
    for x, y in ((a, b), (b, a)):
        i = (x or "").find(_RELIC_PARK_MARK)
        if i < 2:
            continue
        site = _norm_site_name(x[:i])
        if site.endswith("国家") and len(site) - 2 >= 2:
            site = site[:-2]
        ny = _norm_site_name(y or "")
        for cand in (site, site.removesuffix("村"), site.removesuffix("遗址")):
            if len(cand) >= 2 and cand in ny:
                return True
    return False


def _composite_dup(a: str, b: str) -> bool:
    for x, y in ((a, b), (b, a)):
        for seg in _COMPOSITE_SPLIT_RE.split(x or ""):
            s = _norm_site_name(seg)
            if len(s) < 2 or s in _COMPOSITE_SEG_STOP:
                continue
            if s in _norm_site_name(y or ""):
                return True
    return False


def _sibling_core(name: str) -> tuple[str, bool]:
    s = _norm_site_name(name)
    if len(s) >= 3 and s[0] in _SIBLING_SIZE_PREFIX:
        return s[1:], True
    return s, False


def _sibling_dup(a: str, b: str) -> bool:
    ca, sa = _sibling_core(a)
    cb, sb = _sibling_core(b)
    if not (sa or sb):
        return False
    if len(ca) < 2 or len(cb) < 2:
        return False
    return ca == cb or ca.startswith(cb) or cb.startswith(ca)


def _town_dup(a: str, b: str) -> bool:
    """同地名（朱家角类）：削通用尾缀后内核相同，且至少一侧真的削掉。"""
    ca, cb = place_core(a), place_core(b)
    if not ca or ca != cb:
        return False
    return ca != str(a or "").strip() or cb != str(b or "").strip()


def _museum_cand(cand) -> bool:
    name = str(getattr(cand, "name", "") or "").strip()
    return str(getattr(cand, "category", "") or "") == "museum" or name.endswith(
        _MUSEUM_NAME_TAILS
    )


def _street_cand(cand) -> bool:
    return str(getattr(cand, "category", "") or "") == "citywalk" or bool(
        _STREET_DISTRICT_RE.search(str(getattr(cand, "name", "") or ""))
    )


def combo_same_day(a, b) -> bool:
    """11-07 终裁的组合对（博物馆×伞形挂牌）：复合通道命中但单侧博物馆
    → 不互斥（两卡并存），但**若双在场必须同日**（「连排成组」）——
    引擎侧由 c09 加「双在场⇒同日」约束（a 在 d、b 只能在 d）。仅在
    无其他孪生通道命中时成立（content/heritage 命中=真孪生走互斥）。
    """
    name_a = str(getattr(a, "name", "") or "")
    name_b = str(getattr(b, "name", "") or "")
    if not _composite_dup(name_a, name_b):
        return False
    if _museum_cand(a) == _museum_cand(b):
        return False  # 同为博物馆（总馆·分馆）走孪生互斥
    return twin_gate_km(a, b) is None


def twin_gate_km(a, b) -> float | None:
    """候选对 → 同站孪生地理闸（km）；None = 不同站（不互斥）。

    与 legacy ``_same_visit`` 当日口径一致：通道命中取对应闸；复合通道
    的单侧博物馆对豁免（11-07 终裁「博物馆×伞形景区还原多卡连排成组」）；
    酒店卡不参与；街区身份与餐饮/演出劈叉不并（11-08 拍板）。
    """
    cat_a = str(getattr(a, "category", "") or "")
    cat_b = str(getattr(b, "category", "") or "")
    # 酒店卡是独立停留点：绝不互并
    if cat_a == "hotel" or cat_b == "hotel":
        return None
    # 街区体验 vs 宴/演：两个体验不并
    if _street_cand(a) != _street_cand(b) and (
        {"food", "entertainment"} & {cat_a, cat_b}
    ):
        return None

    poi_a = getattr(a, "poi_id", None)
    poi_b = getattr(b, "poi_id", None)
    if poi_a and poi_b and poi_a == poi_b:
        return 0.0  # 同一行：无条件互斥

    name_a = str(getattr(a, "name", "") or "")
    name_b = str(getattr(b, "name", "") or "")

    if _content_dup(name_a, name_b):
        return GATE_CONTENT_KM

    if _heritage_dup(name_a, name_b) or _relic_park_dup(name_a, name_b):
        return GATE_HERITAGE_KM

    if _sibling_dup(name_a, name_b) and not (
        {cat_a, cat_b} & _UMBRELLA_SCENIC_EXEMPT_CATEGORIES
    ):
        return GATE_SIBLING_KM

    composite = _composite_dup(name_a, name_b)
    if composite and (_museum_cand(a) != _museum_cand(b)):
        composite = False  # 11-07 终裁：博物馆×伞形挂牌并存连排
    if composite:
        return GATE_COMPOSITE_KM

    if (
        _same_site(name_a, name_b)
        or _town_dup(name_a, name_b)
        or _show_dup(name_a, name_b)
    ):
        return GATE_TIGHT_KM

    return None
