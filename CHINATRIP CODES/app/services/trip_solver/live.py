"""F-03/F-10 live snapshot (P3 seam): request fields + live stores →
FactSnapshot schema v2, plus the flag-gated session generator the api seam
calls via ``asyncio.to_thread`` (F-42).

The builder is READ-ONLY over the stores: musts bind through the POI store
exact-name → text-match fallback (an unbindable must keeps a skeleton
requested candidate — coverage surfaces honestly, never a silent drop);
the pool reuses ``top_pois_in_city`` (legacy hygiene: no food/hotel, active
status, coordinates first); remote rows get F-14 access profiles converted
from the AccessServiceStore timetable rows; weather rows are bilingualised
so both the legacy 雨 scan and F-13 ``rain`` matching work.
"""

from __future__ import annotations

import datetime
import logging
from dataclasses import replace
from typing import Any, Callable, Optional

from .types import (
    AccessProfile,
    CandidateItem,
    FactSnapshot,
    FixedPin,
    RequestedItem,
    TripRequest,
)

logger = logging.getLogger(__name__)

POOL_LIMIT_PER_CITY = 30
WEATHER_MARKS_RAIN = "雨"
WEATHER_MARK_HEAVY = ("大", "暴")


def bilingual_weather(text: Optional[str]) -> Optional[str]:
    """legacy zh weather text → bilingual so F-13 ``rain`` also matches."""
    if not text:
        return None
    if WEATHER_MARKS_RAIN not in text and "rain" not in text.lower():
        return text
    heavy = any(mark in text for mark in WEATHER_MARK_HEAVY) or "heavy" in text.lower()
    tag = " (heavy rain)" if heavy else " (rain)"
    return text + tag


def _row_location(row: dict[str, Any]):
    loc = row.get("location")
    if isinstance(loc, (tuple, list)) and len(loc) == 2:
        try:
            return float(loc[0]), float(loc[1])
        except (TypeError, ValueError):
            return None, None
    return None, None


_HERITAGE_TAGS = frozenset({"5a", "unesco", "国家一级博物馆"})
_HERITAGE_SOURCES = frozenset({"museum1", "unesco"})


def _data_priority_score(row) -> int:
    """R12-H10b 库内数据优先级分（重要性真值：名录+评分）。
    时长不进删点序（2026-11-20 用户纠正「天坛 4.7/150 < 颐和园 4.7/240
    为什么」——时长是排程属性不是重要性；同名录同评分=平级，
    删谁交给地理聚族/行程质量层裁决）。时长留在排位侧
    （BIG_MUST_LATE_BANDS/大点先排等既有时序机制）。"""
    tags = set(row.get("tags") or [])
    heritage = (
        bool(tags & _HERITAGE_TAGS) or (row.get("source") or "") in _HERITAGE_SOURCES
    )
    try:
        rating = float(row.get("rating") or 0)
    except Exception:
        rating = 0.0
    if rating <= 0 and heritage:
        rating = 4.8  # 无评分名录行≈裸 4.8（top_pois 同哲学）
    return max(1, int((30 if heritage else 0) + rating * 10))


def _row_to_candidate(
    cid: str,
    row: dict[str, Any],
    *,
    kind: str = "fill",
    rid: Optional[str] = None,
    remote: bool = False,
) -> CandidateItem:
    lon, lat = _row_location(row)
    # R28 止污：候选名剥餐槽展示后缀（库行/图商行脏不脏都不外露；
    # 虹鳟鱼案污名「…农家菜（午餐）」已固化进 pois.name_zh）。
    from app.services.poi_names import clean_meal_slot_suffix

    from .inputs.cuisine import cuisine_key  # R12-D 菜系键

    # R41（2026-11-25 用户令「附近餐厅都没有被推荐插入到餐卡。除了 RATE,
    # GEOGRAPHIC. 还考虑一下 RATING NUMBER.」）：餐候选质量分吃「评分 ×
    # 评分数」的可信度评分（meal_geo.quality_score）——小样本满分不再压过
    # 高评论数高分店；无评分餐厅 = 0（旧 _data_priority_score 的 max(1,…)
    # 地板会让它落进 float 域 ×100 拿满质量奖励，实盘无评分店质量 +100）。
    # 其余类别与语料 float 域行为不变。
    if kind == "requested":
        quality = _data_priority_score(row)
    elif (row.get("category") or "") == "food" and (
        row.get("rating") or row.get("tags")
    ):
        from app.services.meal_geo import quality_score as _food_quality_score

        quality = _food_quality_score(row)
    elif row.get("rating") or row.get("tags"):
        quality = _data_priority_score(row)
    else:
        quality = row.get("quality")

    return CandidateItem(
        cid=cid,
        name=clean_meal_slot_suffix(str(row.get("name") or "")),
        # R13（#4 修复）：真库 PoiDetailStore 行的 id 键=source_poi_id
        # （SnapshotStore 假库才叫 id）——两个键都认，ts- 会话卡片自 R8
        # 起无 poi_id 的根因（pin/换点/详情对餐馆卡受限一并解除）
        poi_id=(
            str(row["id"])
            if row.get("id")
            else (str(row["source_poi_id"]) if row.get("source_poi_id") else None)
        ),
        kind=kind,  # type: ignore[arg-type]
        rid=rid,
        category=row.get("category"),
        tier=row.get("_tier") or row.get("tier"),
        # R12-H10（2026-11-20 用户拍板「按库里的数据来排」）：必去
        # 绑定把库内数据分（名录 tags/来源 + 真值评分[名录缺评按
        # 4.8 地板——池排序同哲学] + 时长档）落到 quality——覆盖
        # 层据此定删点序。
        # R12-H10c（2026-11-22 用户令「legacy 与 cp-sat 同一套选点
        # 排序逻辑」）：填充候选此前 quality 恒 0（库行无 quality
        # 键）——引擎填充选择只有 flat FILL_REWARD，完全不吃评分/
        # 名录档，与 legacy 确定性选点「①选点=tier 梯子序、同档
        # 评分降序 tie-break」脱钩。填充同吃库内数据分（有界奖励
        # 见 objectives.FILL_QUALITY_REWARD_CAP），选点序与 legacy
        # 同源；无评分/无标签行保持 0（旧快照行为不变）。
        quality=quality,
        lon=lon,
        lat=lat,
        opening_hours=row.get("opening_hours"),
        best_visit_time=row.get("best_visit_time"),
        indoor=row.get("indoor"),
        rain_ok=row.get("rain_ok"),
        suggested_duration_min=row.get("suggested_duration_min"),
        remote=remote,
        city=row.get("city"),
        # R12-D 菜系键（同菜系不重样罚项的信号；识别不出=None）
        cuisine=(cuisine_key(row) if (row.get("category") or "") == "food" else None),
        # R13o④：预约/购票显示链字段随候选（legacy _reservation_hint 同源，
        # poi 行 reservation_required/advance + 名单/09 表守卫匹配）。
        booking_url=(str(row["booking_url"]) if row.get("booking_url") else None),
        website=(str(row["website"]) if row.get("website") else None),
        reservation_hint=_reservation_hint_for_row(row),
        # R28：地址随候选（卡面 📍 行的数据源；不进 snapshot_hash）。
        address=row.get("address"),
        address_en=row.get("address_en"),
    )


def _reservation_hint_for_row(row: dict[str, Any]) -> Optional[str]:
    """R13o④：poi 行 → 预约提示串（legacy agent._reservation_hint 同源：
    行列优先，名单 v0 兜底，再退 09 号表守卫匹配）。餐/住类按 legacy
    口径返回 None（订座走餐位道）。懒 import：agent.plan 是重模块。"""
    try:
        from app.services.agent.plan import _reservation_hint

        return _reservation_hint(str(row.get("name") or ""), row)
    except Exception:  # noqa: BLE001 - 提示是显示糖：链路任何失败退 None
        return None


def _name_hits(name: str, other: str) -> bool:
    """Exact or containment both ways (the legacy _name_dup family spirit)."""
    if not name or not other:
        return False
    return name == other or name in other or other in name


#: 流水发车但只给首末班时的默认发车间隔——与
#: app.services.access_services.DEFAULT_HEADWAY_MINUTES 同口径（景区专线常见 15 分档）。
DEFAULT_HEADWAY_MINUTES = 15

#: 2026-11-23 用户拍板「any bus should be replaced by taxi」：常规公交
#: （mode=bus）不进引擎档案——该点若无其它方式，C-08 无班可排，接驳卡不
#: 物化，腿链自然回落打车（hotel → 景点整段出租车）。shuttle（景区直通车/
#: 旅游专线）、train（城际铁路）、ferry（轮渡）照旧保留。
#: 与 app.services.access_services.BUS_MODES 保持同步（规则层同一口径）。
BUS_MODES = frozenset({"bus", "city_bus", "public_bus"})


def _row_hhmm(v) -> Optional[str]:
    """班次值归一成 HH:MM（两种真库形态：int 分钟 / '07:30' 字符串）。

    R13c2（2026-11-19）：AccessServiceStore 真库行班次是 '07:30' 字符串；
    此前 live 只认 int 分钟，档案恒空。两种形态都归一。
    """
    if isinstance(v, int):
        return "%02d:%02d" % (v // 60, v % 60)
    s = str(v or "").strip()
    return s if ":" in s else None


def _hhmm_to_min(text) -> Optional[int]:
    try:
        hh, mm = str(text).split(":", 1)
        h, m = int(hh), int(mm)
    except (TypeError, ValueError):
        return None
    if not (0 <= h <= 24 and 0 <= m < 60):
        return None
    return h * 60 + m


def _expand_hhmm_window(times, first, last, freq) -> list[str]:
    """去程/返程班次派生（引擎侧单一真源）。

    R20④（2026-11-23 八达岭去程卡不物化）：与 legacy
    ``app.services.access_services.AccessService.departures()/returns()``
    同口径——显式时刻列表优先；缺则按首末班窗 + 间隔展开成 HH:MM 序列。
    此前引擎只读 ``outbound_times`` 数组、不展开首末班窗，导致
    「只给 06:30–11:00 窗、times 为 null」的档案行被判无班次整行丢弃
    （``_access_profiles_for`` 的 ``if not departures: continue``），
    去程卡不物化、回退打车直连（晨卡 → 景区三十分钟直连，而 legacy
    同数据有班次块）。这里补齐窗展开，让引擎与 legacy 吃同一份班次真值。
    """
    explicit = [d for d in (_row_hhmm(v) for v in (times or [])) if d]
    if explicit:
        return explicit
    f = _row_hhmm(first)
    lst = _row_hhmm(last)
    if not f or not lst:
        return []
    fm, lm = _hhmm_to_min(f), _hhmm_to_min(lst)
    if fm is None or lm is None or lm < fm:
        return []
    step = max(5, int(freq or DEFAULT_HEADWAY_MINUTES))
    out: list[str] = []
    cur = fm
    while cur <= lm:
        out.append("%02d:%02d" % (cur // 60, cur % 60))
        cur += step
    return out


def _access_profiles_for(
    pool: list[dict], service_rows: list[dict]
) -> list[AccessProfile]:
    """F-14: AccessServiceStore rows → AccessProfile bound to pool poi ids."""
    by_name = {str(r.get("name") or ""): r for r in pool}
    out: list[AccessProfile] = []
    for row in service_rows:
        # 2026-11-23 用户拍板「any bus should be replaced by taxi」：常规公交
        # 不进引擎档案——该点若无 shuttle/train/ferry，本函数返回空列表，
        # 接驳卡不物化，腿链回落打车直连（绝不把公交当备选）。
        if str(row.get("mode") or "").strip().lower() in BUS_MODES:
            continue
        poi_name = str(row.get("poi_name") or "")
        if poi_name and poi_name in by_name:
            # R28：班次行优先绑精确同名池行——互含命中会让「慕田峪长城」
            # 班次错绑「八达岭慕田峪长城旅游区」（坐标相距 50km 的错档档案，
            # 绑定结果随池序漂移）；池里没有精确行时才允许互含回退
            # （别名/简称行）。
            target = by_name[poi_name]
        else:
            target = next(
                (r for n, r in by_name.items() if n and _name_hits(poi_name, n)), None
            )
        # R13c（2026-11-19）：真库 PoiDetailStore 行的 id 键=source_poi_id
        # （同 R13 #4 根因的另一处）——此前 live 全链接驳档案恒空（C-08
        # 班次约束空转、引擎去程/回城卡永不渲染，live 回城卡全靠响应层）。
        if target is None or not (target.get("id") or target.get("source_poi_id")):
            continue

        try:
            # R20④（2026-11-23）：班次派生改用窗展开——显式 outbound_times/
            # return_times 优先，缺则按首末班 + 间隔展开（与 legacy
            # app.services.access_services.AccessService.departures() 同口径，
            # 见模块级 _expand_hhmm_window）。此前只读显式数组、不展开窗：
            # 八达岭前门线这类「只给 06:30–11:00、outbound_times 为 null」
            # 的行被判无班次整行丢弃（下方 not departures: continue），引擎
            # 去程卡不物化、回退打车直连。
            departures = _expand_hhmm_window(
                row.get("outbound_times"),
                row.get("outbound_first"),
                row.get("outbound_last"),
                row.get("outbound_frequency_minutes"),
            )
            returns = _expand_hhmm_window(
                row.get("return_times"),
                row.get("return_first"),
                row.get("return_last"),
                row.get("return_frequency_minutes"),
            )
            ride = int(row.get("ride_minutes") or 0)
            if ride <= 0 or not departures:
                continue
            fare = row.get("fare_cny")

            def _lonlat(key):
                raw = row.get(key)
                try:
                    return float(raw) if raw not in (None, "") else None
                except (TypeError, ValueError):
                    return None

            # R13m：显示链字段随档案进快照——mode/乘车点坐标/线路名/
            # 购票官网（此前 live 只给求解器吃区间数学，materialize 无从
            # 给卡盖真实 mode，引擎计划班次显示全盲）。
            out.append(
                AccessProfile(
                    gateway=str(row.get("boarding_stop") or "乘车点"),
                    to_poi=str(target.get("id") or target["source_poi_id"]),
                    ride_minutes=ride,
                    wait_minutes=int(row.get("outbound_frequency_minutes") or 0),
                    last_mile_minutes=int(row.get("last_mile_minutes") or 0),
                    departures=tuple(departures),
                    returns=tuple(returns),
                    fare_text=(
                        ("¥%s" % fare)
                        if fare not in (None, "")
                        else row.get("fare_note")
                    ),
                    operator=row.get("operator"),
                    mode=str(row.get("mode") or "shuttle"),
                    service_name=str(row.get("service_name") or "") or None,
                    boarding_lon=_lonlat("boarding_lon"),
                    boarding_lat=_lonlat("boarding_lat"),
                    ticket_url=row.get("ticket_url") or None,
                    official_url=row.get("official_url") or None,
                )
            )
        except (TypeError, ValueError):
            continue  # malformed timetable row: skip, never crash the seam
    return out


def _mode_from_no(no: Optional[str]) -> Optional[str]:
    """车次/航班号 → 交通模式（G/D/C/K/T/Z+数字=火车；航司码+数字=飞机）。"""
    import re

    text = (no or "").strip().upper()
    if not text:
        return None
    if re.match(r"^[GDKTCZYL]\d", text):
        return "train"
    if re.match(r"^[A-Z]{2}\d{3,4}$", text) or re.match(r"^\d{4,5}$", text):
        return "flight"
    return None


def _explicit_mode(intercity_mode):
    """用户指定城际方式（train/flight）→ 全程模式口径；auto/None=legacy
    距离闸语义，引擎侧不强制（缺省）。班次号推出的模式更具体，优先于
    全程口径（同 legacy：特定班次胜过笼统方式）。"""
    return intercity_mode if intercity_mode in ("train", "flight") else None


def snapshot_from_request(
    *,
    cities: list[str],
    must_days: dict[str, int] | None = None,
    days: int,
    start_date: Optional[str],
    musts: list[str],
    store,
    arrival_time: Optional[str] = None,
    departure_time: Optional[str] = None,
    arrival_no: Optional[str] = None,
    departure_no: Optional[str] = None,
    intercity_mode: Optional[str] = None,
    avoid: Optional[list[str]] = None,
    weather_lookup: Optional[Callable[[str, str], Any]] = None,
    service_rows: Optional[list[dict]] = None,
    preferences: str = "",
    city_days: Optional[dict] = None,
    origin_days: int = 0,
    day1_start: Optional[str] = None,
    arrival_day: Optional[int] = None,
    departure_day: Optional[int] = None,
    pool_limit: int = POOL_LIMIT_PER_CITY,
    food_rows: Optional[list[dict]] = None,
) -> FactSnapshot:
    """Build a schema-v2 FactSnapshot from request fields + live stores."""
    avoid = [a for a in (avoid or []) if a]
    request_musts: list[RequestedItem] = []
    candidates: list[CandidateItem] = []
    must_names_bound: set[str] = set()
    # R25：keep 选边的文字日程天钉（site_days）→ RequestedItem.day_hint；C-25 消费
    _day_of: dict[str, int] = {
        str(k): int(v)
        for k, v in (must_days or {}).items()
        if isinstance(v, int) and v > 0
    }
    must_rows: list[dict] = []
    # R13h：同 POI 必去去重——裂词/别名会让同一地点以两个名字进
    # musts（重启缝按「和」裂词、R13f 短语收 + LLM 抽名各异），绑定
    # 到同一行即两张 requested 候选（C-03 只给零车程不禁双在场→
    # 同点双卡）。后到名字并进先到 rid（用户语义=同一地点）。
    bound_poi_keys: set[str] = set()

    for i, name in enumerate(musts, start=1):
        rid = "r%d" % i
        row = None
        for city in cities:
            row = store.candidate_by_name(city, name)
            if row:
                break
        if row is None:
            # text-match fallback (exact-name miss: 别名/简称)
            for city in cities:
                hits = store.match_text_names(city, name, limit=1)
                if hits:
                    row = hits[0]
                    break
        if row is not None:
            _poi_key = str(
                row.get("id") or row.get("source_poi_id") or row.get("name") or ""
            )
            if _poi_key and _poi_key in bound_poi_keys:
                # 同点异名：并进先到 rid，不再造第二张候选
                continue
            if _poi_key:
                bound_poi_keys.add(_poi_key)
            request_musts.append(
                RequestedItem(
                    rid=rid,
                    name=str(row.get("name") or name),
                    # R13o⑦a：双键口径（同 R13-#4/_row_to_candidate）
                    # ——真库行键=source_poi_id；此前只认 id，别名兜底命中
                    # 的必去 poi 恒空（长安十二时辰主题街区案：卡有名无
                    # poi，pin/换点/详情全断）。
                    poi_id=(
                        str(row["id"])
                        if row.get("id")
                        else (
                            str(row["source_poi_id"])
                            if row.get("source_poi_id")
                            else None
                        )
                    ),
                    kind="must",
                    importance=3,
                    day_hint=(
                        _day_of.get(str(name))
                        or _day_of.get(str(row.get("name") or ""))
                        or None
                    ),
                )
            )
            must_rows.append(row)
            bound_cand = _row_to_candidate("c%d" % i, row, kind="requested", rid=rid)
            if bound_cand.category == "food":
                # R8-S2b 餐类必去：真餐厅 any-槽（模型自选午/晚、顶餐卡）
                bound_cand = replace(bound_cand, meal_slot="any")
            candidates.append(bound_cand)
            must_names_bound.add(str(row.get("name") or ""))
        else:
            # unbindable must: skeleton requested candidate — the coverage
            # tier surfaces it honestly (timed anywhere legal or unplaced),
            # never a silent drop (B-01).
            request_musts.append(
                RequestedItem(
                    rid=rid,
                    name=name,
                    kind="must",
                    importance=3,
                    day_hint=_day_of.get(str(name)) or None,
                )
            )
            candidates.append(
                CandidateItem(cid="c%d" % i, name=name, kind="requested", rid=rid)
            )
            must_names_bound.add(name)

    # R8 偏好池 boost（同源 _preference_tokens/_pref_category_hit）：偏好
    # 非空时取 2×池再按「偏好命中在前、组内保库序（tier 梯子）」稳定
    # 重排后截回 pool_limit——legacy「偏好位在 tier 之前」的池侧同款；
    # 偏好为空时行为与旧版完全一致（单倍取数、不重排）。
    pref_tokens: tuple = ()
    pref_show = False
    if (preferences or "").strip():
        try:
            from app.services.trip_orchestrator.nlu import (
                _preference_tokens as _ptoks,
            )

            pref_tokens, pref_show = _ptoks(preferences)
        except Exception:
            pref_tokens = ()
    pool: list[dict] = []
    seen_names = set(must_names_bound)
    # R8-S4 池按行程形状配额（修多城 all-fill 空排）：总量 ≈ days×7，
    # 按城市窗天数（有 city_days/origin_days：C-17 同口径——出发城
    # origin_days≥1 占 (1,k) 窗取数、闭合尾城 ≥2 真实停留取数；
    # k=0 出发城/闭合返程标记不取数——C-17 已灭活，纯模型负重）或
    # 城市均分分配；单城下限 6、上限 pool_limit。此前 3 城×30=90
    # 候选的模型在 tier② 0.4 dtime 下 UNKNOWN，阶梯保 tier① 空前缀
    # =空计划（live 实锤）。
    from .model.c17_city_days import _norm as _city_norm
    from .model.c17_city_days import city_day_windows

    city_list = [c for c in cities if c]
    total_target = max(12, int(days or 1) * 7)
    if city_days or (int(origin_days or 0) >= 1 and len(city_list) > 1):
        windows = city_day_windows(
            city_list, days, dict(city_days or {}), origin_days=origin_days
        )
        share = {
            c: windows[_city_norm(c)][1] - windows[_city_norm(c)][0] + 1
            for c in city_list
            if _city_norm(c) in windows
        }
    else:
        n_cities = max(1, len(city_list))
        share = {c: (int(days or 1) / n_cities) for c in city_list}
    total_w = sum(share.values()) or 1.0
    limits = {
        c: min(int(pool_limit), max(6, int(round(total_target * w / total_w))))
        for c, w in share.items()
    }
    for city, limit_city in limits.items():
        rows = list(
            store.top_pois_in_city(
                city, limit=limit_city * 2 if pref_tokens else limit_city
            )
        )
        if pref_tokens and rows:
            try:
                from app.services.trip_orchestrator.nlu import (
                    _pref_category_hit as _phit,
                )

                rows.sort(key=lambda r: 0 if _phit(r, pref_tokens, pref_show) else 1)
            except Exception:
                pass
        for row in rows[:limit_city]:
            name = str(row.get("name") or "")
            if not name or name in seen_names:
                continue
            if any(_name_hits(name, a) for a in avoid):
                continue
            if any(_name_hits(name, m) for m in must_names_bound):
                continue
            seen_names.add(name)
            pool.append(row)

    # R29（2026-11-24 用户令「WHY RESTAURANTS ARE NOT PROPOSED BY RATING AND
    # GEO INFORMATION」+「WE HV RESTRANTS IN BOTH POIS AND RESTRANT TABLES」）：
    # 餐候选按「评分 × 地理」补池——独立餐厅库 restaurants（北京 550 行、
    # 267 行有 TA 评分）此前从不进候选，引擎只看得见 pois 里带荐点标的 4 条。
    # 锚=本池已选景点（当天动线在哪就在哪吃）；纯库读零外呼；任何失败
    # 降级空池（旧行为零变化；影子语料/假 store 无此方法自动跳过）。
    geo_food_rows: list[dict] = []
    try:
        from app.services.meal_geo import select_geo_rated

        _rows_fn = getattr(store, "restaurant_rows_in_city", None)
        if callable(_rows_fn):
            _raw: list[dict] = []
            for _city in city_list:
                _raw.extend(_rows_fn(_city) or [])
            geo_food_rows = select_geo_rated(
                _raw,
                [
                    (row["location"][0], row["location"][1])
                    for row in (must_rows + pool)
                    if isinstance(row.get("location"), (tuple, list))
                    and len(row["location"]) >= 2
                    # R41：锚=景点。池里的餐厅行不当锚——否则「餐厅旁边的
                    # 餐厅」白白吃掉一整个簇的配额（实测御仙都/白家大院两条
                    # 池内餐行各占 2 个名额，而它们当天并不在盘面上）。
                    and (row.get("category") or "") != "food"
                ],
                # R41：名额随行程天数（午/晚双槽），不再全程 4 家按锚点下标
                # 截断——旧口径下名额全被市中心簇吃光，后面的天零候选。
                limit=max(4, min(10, 2 * int(days or 1))),
            )
    except Exception:  # noqa: BLE001 - 加料失败零影响（旧池原样）
        logger.warning("trip_solver: geo rated food pool failed", exc_info=True)
        geo_food_rows = []
    # R13q（gap #1）：餐饮候选搜索入池。async 调用方预取的 DB 荐点 + amap
    # 检索行在此并池（legacy _rec_food/recommend_restaurants 同源），与
    # top_pois  food 行同一 seen_names 去重 + 同一 any-槽标注。无 food_rows
    # 时零行为变化（影子语料/旧测试形状完全不动）。
    # R41：餐候选与必去的去重只对「必去本身是餐馆」做包含匹配——分店名里
    # 含景点名（南门涮肉(天坛店) vs 必去「天坛」）不是同一个地方，旧双向子串
    # 包含把离景点最近的店当重复项丢掉（真实库实测天坛店因此没进快照）。
    # 用户 avoid 仍保持包含语义（avoid「麦当劳」应挡掉所有分店）。
    must_food_names = {
        str(r.get("name") or "")
        for r in must_rows
        if (r.get("category") or "") == "food"
    }
    for row in list(food_rows or []) + geo_food_rows:
        name = str(row.get("name") or "")
        if not name or name in seen_names:
            continue
        if any(_name_hits(name, a) for a in avoid):
            continue
        if any(_name_hits(name, m) for m in must_food_names):
            continue
        seen_names.add(name)
        pool.append(row)

    profiles = _access_profiles_for(must_rows + pool, service_rows or [])
    profiled_ids = {p.to_poi for p in profiles}
    for k, cand in enumerate(candidates):
        if cand.kind == "requested" and cand.poi_id in profiled_ids:
            candidates[k] = replace(cand, remote=True)
    for j, row in enumerate(pool, start=1):
        poi_id = str(row["id"]) if row.get("id") else None
        pool_cand = _row_to_candidate(
            "f%d" % j, row, remote=bool(poi_id and poi_id in profiled_ids)
        )
        if pool_cand.category == "food":
            # R12-M 餐厅进餐卡（2026-11-19 用户拍板「烤鸭店进餐卡」重修）：
            # top_pois 荐点豁免入池的知名餐厅（2026-11-07 指令）此前无
            # meal_slot——模型当普通观光排 + 照贴午/晚占位卡（live 实锤
            # 北京四季民福 19:02/提督 09:00：观光卡与占位餐卡并列）。
            # 与餐类必去（R8-S2b）同口径 any-槽：被选中即顶替占位卡成
            # 命名餐卡（C-09 绑定/meals.py 命名卡/materialize.py 访视
            # 去重全链已备），另一槽照常出占位。
            pool_cand = replace(pool_cand, meal_slot="any")
        candidates.append(pool_cand)

    weather: list[tuple] = []
    if weather_lookup is not None and start_date:
        base = datetime.date.fromisoformat(start_date)
        poi_city = {c.poi_id: c.city for c in candidates if c.poi_id and c.city}
        for day in range(1, max(1, days) + 1):
            iso = (base + datetime.timedelta(days=day - 1)).isoformat()
            for city in cities:
                try:
                    windows = weather_lookup(city, iso)
                except Exception:
                    windows = None
                text = bilingual_weather(
                    windows[0] if isinstance(windows, tuple) else windows
                )
                if not text:
                    continue
                for poi_id, pc in poi_city.items():
                    if pc == city:
                        weather.append((poi_id, iso, text))

    # 起始城真实首站（2026-11-22）：到达端点随去程腿右移——origin_days≥1
    # 时去程腿落 k+1 早上（legacy 同口径），C-05 到达地板也要跟着落 k+1；
    # 显式传了 arrival_day（中途转移日）则用户权威优先。
    from .model.c17_city_days import origin_shift

    _shift = origin_shift(city_list, days, origin_days)
    if arrival_day is None and _shift >= 1:
        arrival_day = _shift + 1

    return FactSnapshot(
        schema_version=2,
        request=TripRequest(
            days=max(1, days),
            cities=tuple(cities),
            start_date=start_date,
            musts=tuple(request_musts),
            arrival_time=arrival_time,
            departure_time=departure_time,
            arrival_no=arrival_no,
            departure_no=departure_no,
            arrival_mode=_mode_from_no(arrival_no) or _explicit_mode(intercity_mode),
            departure_mode=_mode_from_no(departure_no)
            or _explicit_mode(intercity_mode),
            preferences=preferences or "",
            city_days=tuple(
                sorted((str(k), int(v)) for k, v in dict(city_days or {}).items())
            ),
            origin_days=int(origin_days or 0),
            day1_start=day1_start,
            arrival_day=arrival_day,
            departure_day=departure_day,
        ),
        candidates=tuple(candidates),
        access_profiles=tuple(profiles),
        weather=tuple(weather),
        library_version="live",
        source="live-request",
    )


def _degenerate_plan(plan) -> bool:
    """退化计划判定（R8b-2，2026-11-18 成都空天事故）：任何一天的卡片
    全空、或全程观光卡为零 = 引擎在本请求上不可信（瞬态坏池/求解退化）
    ——按 F-35 语义回落 legacy + 披露，绝不交付空行程。

    归因背景：bisect 实证非代码回归——并行会话批写库期间池行字段瞬态
    损坏（同代码同请求 [0,6]/[6,6]/[4,6] 翻覆）；此闸是交付前最后一道
    兜底，与写入侧修复互不替代。"""
    if plan is None:
        return True
    days = list(getattr(plan, "days", None) or [])
    if not days:
        return True
    if any(not list(getattr(day, "items", None) or []) for day in days):
        return True
    from app.services.itinerary.models import VisitItem

    sights = sum(
        1
        for day in days
        for item in day.items
        if isinstance(item, VisitItem)
        and (item.category or "") not in ("food", "hotel", "transport", "transfer")
    )
    return sights == 0


def _musts_all_placed(outcome, snapshot) -> bool:
    """R24：引擎盘全部必去在场（rid 键；无候选的必去不参与判定）。

    空池/未绑定的必去引擎同样排不了，不能据此把盘判死（legacy 也排不了）。
    """
    solution = getattr(outcome, "solution", None)
    placed = {i.cid for i in (getattr(solution, "items", None) or ())}
    by_rid: dict[str, set[str]] = {}
    for cand in getattr(snapshot, "candidates", ()) or ():
        rid = getattr(cand, "rid", None)
        if rid:
            by_rid.setdefault(str(rid), set()).add(cand.cid)
    resolved = 0
    for req in getattr(getattr(snapshot, "request", None), "musts", ()) or ():
        cids = by_rid.get(str(getattr(req, "rid", "") or ""))
        if not cids:
            continue
        resolved += 1
        if not (cids & placed):
            return False
    return resolved > 0


def _uncovered_must_count(outcome, snapshot) -> int:
    """R32: bound must-visits missing from the solved plan (rid-keyed).

    Mirrors ``_musts_all_placed`` but returns a count so callers can compare
    two candidate outcomes. ``-1`` means the outcome carries no solution and
    coverage cannot be judged — callers must keep the previous behaviour.
    """
    solution = getattr(outcome, "solution", None)
    if solution is None:
        return -1
    placed = {i.cid for i in (getattr(solution, "items", None) or ())}
    by_rid: dict[str, set[str]] = {}
    for cand in getattr(snapshot, "candidates", ()) or ():
        rid = getattr(cand, "rid", None)
        if rid:
            by_rid.setdefault(str(rid), set()).add(cand.cid)
    missing = 0
    for req in getattr(getattr(snapshot, "request", None), "musts", ()) or ():
        cids = by_rid.get(str(getattr(req, "rid", "") or ""))
        if not cids:
            continue
        if not (cids & placed):
            missing += 1
    return missing


def _expected_days(snapshot) -> int:
    """R25：请求天数（0/缺失时跳过缩天体检）。"""
    return int(getattr(getattr(snapshot, "request", None), "days", 0) or 0)


def _plan_shrunk(plan, snapshot) -> bool:
    """R25：缩天盘判定（请求 N 天只回 <N 天=残缺不可交付）。"""
    expected = _expected_days(snapshot)
    if not expected or plan is None:
        return False
    return len(getattr(plan, "days", None) or []) < expected


#: R40（2026-11-25 用户「鸟巢排到 20:30 FIX / 最早班次是 8:30」）：当天末尾
#: 必去开场晚于该点即视为「过晚」——真正病根是远郊日 CP-SAT 在 3s 墙帽下
#: 只跑到 coverage 层，班次的早发偏好（makespan tier）没参与，首班车被停在
#: 非最早班（慕田峪 09:30）→ 回城 18:08 → 末尾必去 20:30+ 晚于停止入园。
#: 阈值取 20:00：19:30 这样的合理晚场不触发，只有明确过晚才回推首班车。
TAIL_LATE_START_MINUTES = 20 * 60


def _latest_must_start(outcome, snapshot) -> tuple[int, int] | None:
    """(day, latest must start_min) of any must-visit in the delivered plan.

    Reads the FINAL plan cards, not the raw solution: post-processing
    (``_open_meal_leg_gaps`` / meal retime) can push a must card past its raw
    solver start (R40 live: raw 19:30 → delivered 20:45), and the tail check
    must see the time the user actually gets. Musts match by name (plan cards
    carry ``item_id`` not the candidate ``cid``); structural cards excluded.
    Falls back to raw solution items when the plan has no timed must card
    (keeps R24/R32 fake-solution tests working).
    """
    plan = getattr(outcome, "plan", None)
    must_names = {
        str(getattr(m, "name", "") or "")
        for m in (getattr(getattr(snapshot, "request", None), "musts", ()) or ())
    }
    latest: tuple[int, int] | None = None
    for day in getattr(plan, "days", ()) or ():
        for item in getattr(day, "items", ()) or ():
            if (getattr(item, "category", None) or "") in (
                "food",
                "hotel",
                "transport",
                "transfer",
            ):
                continue
            if str(getattr(item, "name", "") or "") not in must_names:
                continue
            st = getattr(item, "start_time", None)
            if st is None:
                continue
            minute = int(st.hour) * 60 + int(st.minute)
            if latest is None or minute > latest[1]:
                latest = (int(getattr(day, "day", 1)), minute)
    if latest is not None:
        return latest
    # fallback: raw solution items (fake fixtures / plan without timed cards)
    solution = getattr(outcome, "solution", None)
    if solution is None:
        return None
    by_rid: dict[str, set[str]] = {}
    for cand in getattr(snapshot, "candidates", ()) or ():
        if getattr(cand, "rid", None):
            by_rid.setdefault(str(cand.rid), set()).add(cand.cid)
    must_cids: set[str] = set()
    for req in getattr(getattr(snapshot, "request", None), "musts", ()) or ():
        must_cids |= by_rid.get(str(getattr(req, "rid", "") or ""), set())
    for item in getattr(solution, "items", ()) or ():
        if item.cid not in must_cids:
            continue
        cand = next((c for c in snapshot.candidates if c.cid == item.cid), None)
        if cand is not None and (getattr(cand, "category", None) or "") in (
            "food",
            "hotel",
            "transport",
            "transfer",
        ):
            continue
        start_min = getattr(item, "start_min", None)
        if start_min is None:
            continue
        if latest is None or start_min > latest[1]:
            latest = (int(getattr(item, "day", 1)), int(start_min))
    return latest


def _earliest_shuttle_snapshot(snapshot, day: int, plan) -> tuple | None:
    """R40: re-cast snapshot with the day's remote first shuttle pinned to its
    earliest departable bus (08:30-class), when that remote is actually placed
    on ``day`` and currently left on a later bus. Returns None if nothing to
    change (no profile / user already pinned / already earliest).

    Uses only ``snapshot.access_profiles`` + the final plan's access cards —
    no enrich, no I/O. ``chosen_depart`` narrowing is the existing R19 path and
    does NOT flip ``pinned_with_time`` (that reads request.pins only), so no
    entry-cap exemption leaks in.
    """
    from .model.c05_c08 import DEFAULT_FIRST_SHUTTLE_MIN

    profiles_by_poi: dict[str, object] = {}
    for prof in getattr(snapshot, "access_profiles", ()) or ():
        profiles_by_poi[str(getattr(prof, "to_poi", "") or "")] = prof
    if not profiles_by_poi:
        return None
    day_plan = next((d for d in getattr(plan, "days", ()) or () if d.day == day), None)
    if day_plan is None:
        return None
    from app.services.itinerary.models import VisitItem

    out = []
    changed = False
    for cand in snapshot.candidates:
        dep = getattr(cand, "chosen_depart", None)
        if dep:  # user-picked shuttle is explicit authority — never override
            out.append(cand)
            continue
        key = str(getattr(cand, "poi_id", "") or getattr(cand, "cid", "") or "")
        prof = profiles_by_poi.get(key)
        if prof is None or not getattr(prof, "departures", ()):
            out.append(cand)
            continue
        # earliest bus at/after the R12-H4 default floor (07:30 excluded)
        earliest = next(
            (
                d
                for d in sorted(getattr(prof, "departures"))
                if int(d.split(":")[0]) * 60 + int(d.split(":")[1])
                >= DEFAULT_FIRST_SHUTTLE_MIN
            ),
            None,
        )
        if earliest is None:
            out.append(cand)
            continue
        # only pin remotes actually placed on the reported day
        placed = any(
            isinstance(it, VisitItem) and it.poi_id == getattr(cand, "poi_id", None)
            for it in day_plan.items
        )
        if not placed:
            out.append(cand)
            continue
        out.append(replace(cand, chosen_depart=earliest))
        changed = True
    return replace(snapshot, candidates=tuple(out)) if changed else None


def _recover_outcome(snapshot, outcome, budget_s):
    """R24/R25 引擎原生恢复：回落 legacy 前先给引擎一次翻盘机会。

    触发：解不出盘（INFEASIBLE/UNKNOWN/瞬时坏池）、缩天盘（残缺）、或引擎侧
    异常/not-ready 回落（瞬态基础设施错重解一次常可恢复；2026-11-23 用户令
    「NO MEANING TO RUN LEGACY. WE NEED TO RUN CP-SAT TO REPLACE LEGACY」）。
    R32 追加：盘形状健康但有时限内的覆盖损失（必去被丢）同样重解——
    tier① 的 FEASIBLE 值会被等式锁死，不重解就静默丢失必去。
    R40 追加：盘形状健康但当天末尾必去过晚（开场≥20:00，晚于停止入园）时，
    把当天远郊首班车 pin 到最早可排班次重解——3s 墙帽下早发偏好没参与所致。
    重试自身失败保持原 outcome 的回落语义，绝不把生成打死；重试反而更差
    （无盘且原盘非空、或覆盖未改善、或末尾没提前）时保留原盘。
    """
    from .entry import ENGINE_CPSAT, solve_trip

    plan = getattr(outcome, "plan", None)
    shrunk = _plan_shrunk(plan, snapshot)
    # R32：3s 墙帽下 tier① 可能只拿到 FEASIBLE 的次优覆盖值；solve.py 会把
    # 该值等式锁死，后续层再也无法补回必去。丢必去的盘即使形状健康也必须
    # 重解一次（更长墙钟），否则「有时间却把必去丢了」会静默交付。
    missing = _uncovered_must_count(outcome, snapshot)
    coverage_retry = (
        outcome.engine == ENGINE_CPSAT
        and plan is not None
        and not shrunk
        and missing > 0
    )
    # R40: healthy plan but the day's tail must starts too late → retry with
    # the remote's first shuttle pinned to the earliest departable bus.
    late = _latest_must_start(outcome, snapshot)
    tail_retry = (
        outcome.engine == ENGINE_CPSAT
        and plan is not None
        and not shrunk
        and not coverage_retry
        and missing == 0
        and late is not None
        and late[1] >= TAIL_LATE_START_MINUTES
    )
    if not tail_retry:
        early_snapshot = None
    else:
        early_snapshot = _earliest_shuttle_snapshot(snapshot, late[0], plan)
        if early_snapshot is None or early_snapshot is snapshot:
            tail_retry = False
    if late is not None and late[1] >= TAIL_LATE_START_MINUTES:
        logger.info(
            "R40 tail-late detected: day=%d start=%d trigger=%s early_snapshot=%s",
            late[0],
            late[1],
            tail_retry,
            early_snapshot is not None,
        )
    if (
        outcome.engine == ENGINE_CPSAT
        and plan is not None
        and not shrunk
        and not coverage_retry
        and not tail_retry
    ):
        return outcome
    retry_budget = (
        max(float(budget_s or 3.0) * 3.0, 12.0)
        if coverage_retry
        else max(float(budget_s or 20.0), 20.0) * 2.0
    )
    # R34: warm-start the coverage retry with the first (suboptimal) solution.
    # The incumbent already seats most musts, so CP-SAT refines from it instead
    # of rebuilding the search from scratch. Only for the coverage path: a
    # no-plan/shrunk outcome has no usable incumbent (and _apply_hint would hint
    # every presence to 0), so those retries keep the cold start.
    retry_hint = outcome.solution if coverage_retry else None
    # R40: the tail retry solves a snapshot whose day's first shuttle is pinned
    # to the earliest departable bus (R19 chosen_depart path, cold start — the
    # old solution's dep would fight the pin). Other paths keep the raw snapshot.
    solve_snapshot_in = early_snapshot if tail_retry else snapshot
    try:
        retry = solve_trip(
            solve_snapshot_in,
            flag=ENGINE_CPSAT,
            budget_s=retry_budget,
            hint=retry_hint,
        )
    except Exception:
        return outcome
    if getattr(retry, "plan", None) is None and plan is not None:
        return outcome
    if coverage_retry:
        retry_missing = _uncovered_must_count(retry, snapshot)
        # 重试没把覆盖率救回来（或更差）就保留原盘，绝不倒退。
        if retry_missing >= 0 and retry_missing >= missing:
            return outcome
    if tail_retry:
        retry_late = _latest_must_start(retry, solve_snapshot_in)
        retry_missing = _uncovered_must_count(retry, snapshot)
        # 只有当重解确实把末尾必去提前（更早开场）且没丢必去时才采用，
        # 否则保留原盘。两个条件缺一不可，绝不倒退。
        improved = (
            retry_late is not None and late is not None and retry_late[1] < late[1]
        )
        if (retry_missing >= 0 and retry_missing > 0) or not improved:
            return outcome
        retry.disclosures = list(getattr(retry, "disclosures", None) or []) + [
            {
                "zh": "当天末尾必去开场过晚，已将首个景点去程班次提前至最早可排班车，"
                "整段行程相应前移",
                "en": "The day's last must-visit started too late — moved the "
                "first site's outbound shuttle to the earliest available "
                "departure and pulled the whole day earlier.",
            }
        ]
    return retry


def _engine_declines(outcome, snapshot) -> bool:
    """R24/R25：是否仍需回落 legacy——非引擎/盘缺失/缩天盘/退化盘且必去不全在场。

    缩天盘先经 _recover_outcome 重试；重试仍缩天=真缺陷，回落安全网并披露
    （残缺盘绝不静默交付）。退化盘但「必去全在场」不回落（R19(1) 拍板：
    legacy 再丢必去，比空日引擎盘更差）；调用方放行引擎盘并补披露假设。
    """
    from .entry import ENGINE_CPSAT

    if outcome.engine != ENGINE_CPSAT:
        return True
    plan = getattr(outcome, "plan", None)
    if plan is None:
        return True
    if _plan_shrunk(plan, snapshot):
        return True
    return bool(_degenerate_plan(plan)) and not _musts_all_placed(outcome, snapshot)


def generate_session_via_trip_solver(
    *,
    device_id: str,
    cities: list[str],
    days: int,
    start_date: Optional[str],
    musts: list[str],
    store,
    arrival_no: Optional[str] = None,
    departure_no: Optional[str] = None,
    intercity_mode: Optional[str] = None,
    city_days: Optional[dict] = None,
    origin_days: int = 0,
    preferences: str = "",
    arrival_time: Optional[str] = None,
    departure_time: Optional[str] = None,
    lang: Optional[str] = None,
    arrival_day: Optional[int] = None,
    departure_day: Optional[int] = None,
    # R13p（2026-11-22 审计修复）：原始行前日期串——首屏只需日序
    # arrival_day/departure_day，但重排 _session_snapshot 是从会话的
    # arrival_date/departure_date 用 _intake_day_no 重算日序；不落地原始串，
    # 同会话重排时中途转移日静默丢失。
    arrival_date: Optional[str] = None,
    departure_date: Optional[str] = None,
    weather_lookup: Optional[Callable[[str, str], Any]] = None,
    budget_s: float = 3.0,
    food_rows: Optional[list[dict]] = None,
) -> tuple:
    """Flag-gated seam core (sync — the api wraps in ``asyncio.to_thread``).

    Returns ``(PlanSession | None, SolveOutcome)``: a ready session when the
    model engine served; ``(None, outcome)`` means the caller must run the
    legacy cascade — appending ``outcome.disclosures`` when it fell back.
    """
    from app.services.agent.plan import PlanSession

    from .entry import ENGINE_CPSAT, engine_flag, serving_ready, solve_trip
    from .types import validate_snapshot

    flag = engine_flag()
    if flag != ENGINE_CPSAT:
        return None, None  # legacy 模式：agent.start 是正常路径，无需披露
    if not serving_ready()[0]:
        return None, _disclosed_fallback()

    def _weather(city: str, iso: str):
        if weather_lookup is None:
            return None
        try:
            return weather_lookup(city, iso)
        except Exception:
            return None

    service_rows: list[dict] = []
    try:
        from app.services.access_service_store import AccessServiceStore

        # R13e：真会话工厂（store._factory，同 plan.py 显式注入口径）——
        # 此前传 None：access_services 里 self._factory() 直接 TypeError
        # 被吞成 0 行，live 引擎接驳档案恒空（C-08 空转、去程卡不渲染的
        # 最后一洞；键名/班次形态修复 R13c/c2 之上）。
        services = AccessServiceStore(getattr(store, "_factory", None)).access_services(
            list(cities)
        )
        service_rows = list(services or [])
    except Exception:
        service_rows = []

    # R13f（2026-11-19 用户令「fix all」收口实测）：start 缝的
    # preferences/brief 通道此前只把文本当软偏好（R8 boost）——「必去
    # 慕田峪长城」这类强意图点名词被吞成偏好信号，接驳档案生效后远郊
    # 成本变真，引擎合法不选 → 用户必去意图静默丢失。message 换局缝
    # （_restart_named_musts）有硬通道，start 缝同口径补齐：强意图短语
    # （必去/要去/必须去/务必去/打卡）收进 musts，「想去」仍留软偏好
    # （语义不对等，R8 链）；绑定走快照链（精确名→文本→骨架，缝不吞
    # 点、B-01）；与显式 musts 同名去重。
    try:
        from app.services.trip_orchestrator.nlu import _restart_named_musts

        _named = _restart_named_musts(preferences or "", store=store, cities=cities)
        if _named:
            _have = {str(m or "").strip() for m in (musts or [])}
            musts = list(musts or []) + [
                p for p in _named if str(p or "").strip() not in _have
            ]
    except Exception:
        pass  # 收取失败退回纯偏好语义（现状），绝不拦生成

    # R13p（2026-11-22 审计修复）：首日出发时刻（"LEAVE HOTEL ON 11AM"）。
    # legacy start_nlu.start 从 brief/preferences 正则解析 comment_day_start；
    # 走引擎缝时 brief 非空已被形状闸（seam_plain_shape）退回 legacy，进到这里
    # 的只有 preferences —— 此前不解析，引擎 C-04 地板读不到，静默失效。
    # 复用同一 nlu 函数（零 LLM），与 legacy 口径一致。
    day1_start: Optional[str] = None
    try:
        if (preferences or "").strip():
            from app.services.trip_orchestrator.nlu import _parse_text_day_start

            day1_start = _parse_text_day_start(preferences)
    except Exception:
        day1_start = None  # 解析失败退回无首日约束，绝不拦生成

    snapshot = snapshot_from_request(
        cities=cities,
        days=days,
        start_date=start_date,
        musts=musts,
        store=store,
        arrival_time=arrival_time,
        departure_time=departure_time,
        arrival_no=arrival_no,
        departure_no=departure_no,
        intercity_mode=intercity_mode,
        city_days=city_days,
        origin_days=origin_days,
        avoid=[],
        weather_lookup=_weather,
        service_rows=service_rows,
        preferences=preferences or "",
        day1_start=day1_start,
        arrival_day=arrival_day,
        departure_day=departure_day,
        food_rows=food_rows,
    )
    errors = validate_snapshot(snapshot)
    if errors:
        return None, _disclosed_fallback()

    outcome = solve_trip(snapshot, flag=ENGINE_CPSAT, budget_s=budget_s)
    outcome = _recover_outcome(snapshot, outcome, budget_s)
    if _engine_declines(outcome, snapshot):
        # R24：只有引擎真解不出/必去不全时才回落（安全网；F-35 披露语义不变）。
        from .entry import FALLBACK_DISCLOSURE

        outcome.fallback = True
        outcome.disclosures = [dict(FALLBACK_DISCLOSURE)]
        return None, outcome
    if _degenerate_plan(getattr(outcome, "plan", None)):
        # R24 放行形态（必去全在场）：空日引擎盘优于 legacy 丢必去（R19 (1)）。
        outcome.plan.assumptions = list(
            getattr(outcome.plan, "assumptions", []) or []
        ) + ["部分日期未排满（必去已全部排入，可继续补点）"]

    session = PlanSession(
        session_id="ts-%s" % datetime.datetime.now().strftime("%Y%m%d%H%M%S%f"),
        device_id=device_id,
        cities=list(cities),
        days=max(1, days),
        start_date=start_date,
        must_visits=list(musts),
        arrival_time=arrival_time,
        departure_time=departure_time,
        # R13p（2026-11-22 审计修复）：首屏约束落地——legacy start_nlu.start
        # 全会存，引擎缝此前只存到达/离开时刻。不落地则同会话「重排」时
        # _session_snapshot 读空，班次/分城/中途转移日/首日出发静默丢失。
        arrival_no=arrival_no,
        departure_no=departure_no,
        arrival_date=arrival_date,
        departure_date=departure_date,
        intercity_mode=intercity_mode or "auto",
        city_days=dict(city_days or {}),
        origin_days=int(origin_days or 0),
        comment_day_start=day1_start,
        preferences=preferences or "",
        lang=lang,
    )
    session.plan = outcome.plan
    session.assumptions = list(getattr(outcome.plan, "assumptions", []) or [])
    session.state = "ready"
    # 首屏就要带地址（2026-11-23）：装配出口补一次库，别等 GET 读闸
    _fill_detail_from_store(session.plan, store)
    return session, outcome


def replan_session_via_trip_solver(
    session,
    *,
    store,
    extra_assumptions=None,
    budget_s: float = 3.0,
    weather_lookup=None,
    food_rows: Optional[list[dict]] = None,
):
    """F-35 二期会话级重解（2026-11-18 拍板「偏好重排也要换 CP-SAT」）。

    就地换引擎：session_id/history/会话状态全保留（引擎连续性），plan
    换成模型引擎产物；用户钉住的卡折进必去（在场保证，槽位重解——
    F-50 FixedPin 全保位是后续升级位）。返回 SolveOutcome：
    - engine=cpsat 且 plan 落位 → 调用方直接收工；
    - fallback=True → 调用方走 legacy 并附 disclosures[0]；
    - None（旗未开/快照不可验证）→ 调用方走 legacy，行为零变化。
    """
    from .entry import (
        ENGINE_CPSAT,
        FALLBACK_DISCLOSURE,
        engine_flag,
        serving_ready,
        solve_trip,
    )
    from .types import validate_snapshot

    flag = engine_flag()
    if flag != ENGINE_CPSAT:
        return None  # legacy 模式：legacy 管线是正常路径
    if not serving_ready()[0]:
        return _disclosed_fallback()

    snapshot = _session_snapshot(
        session, store, weather_lookup=weather_lookup, food_rows=food_rows
    )
    if snapshot is None:
        return _disclosed_fallback()

    # R8b 钉位保全（铁律 19 全保位）：用户钉住的卡按 C-04 FixedPin 钉死
    # 日+时刻（NEVER_RELAX——钉冲突只会 INFEASIBLE 回落 legacy 原生保钉，
    # 绝不静默挪位）；绑定链=精确名→包含匹配；钉名同时留在 musts 里保证
    # 候选行存在（must+pin 双表示自洽：must 保存在，pin 保槽位）。
    pinned_cards = _pinned_cards(session)
    if pinned_cards:
        pins = list(getattr(snapshot.request, "pins", ()) or [])
        for card in pinned_cards:
            cand = next(
                (c for c in snapshot.candidates if c.name == card["name"]),
                None,
            )
            if cand is None:
                cand = next(
                    (
                        c
                        for c in snapshot.candidates
                        if _name_hits(card["name"], c.name)
                    ),
                    None,
                )
            if cand is not None:
                pins.append(
                    FixedPin(
                        rid="",
                        day=card["day"],
                        start_min=card["start_min"],
                        cid=cand.cid,
                    )
                )
        if pins:
            snapshot = replace(
                snapshot,
                request=replace(snapshot.request, pins=tuple(pins)),
            )

    if validate_snapshot(snapshot):
        return None

    outcome = solve_trip(snapshot, flag=ENGINE_CPSAT, budget_s=budget_s)
    outcome = _recover_outcome(snapshot, outcome, budget_s)
    if _engine_declines(outcome, snapshot):
        # R24：只有引擎真解不出/必去不全时才回落（安全网；F-35 披露语义不变）。
        from .entry import FALLBACK_DISCLOSURE

        outcome.fallback = True
        outcome.disclosures = [dict(FALLBACK_DISCLOSURE)]
        return outcome
    if _degenerate_plan(getattr(outcome, "plan", None)):
        # R24 放行形态（必去全在场）：空日引擎盘优于 legacy 丢必去（R19 (1)）。
        outcome.plan.assumptions = list(
            getattr(outcome.plan, "assumptions", []) or []
        ) + ["部分日期未排满（必去已全部排入，可继续补点）"]

    session.plan = outcome.plan
    session.assumptions = list(getattr(outcome.plan, "assumptions", []) or []) + list(
        extra_assumptions or []
    )
    session.state = "ready"
    session.brief_notes = []
    # 重排首屏同款：装配出口补一次库（地址/营业时间），不靠 GET 读闸兜底
    _fill_detail_from_store(session.plan, store)
    return outcome


def _fill_detail_from_store(plan, store) -> int:
    """引擎卡读库补地址/营业时间（2026-11-23 修「表里有地址，卡片不显示」）。

    根因：CandidateItem 没有地址字段，materialize 造 VisitItem 时也不带
    address/address_en/opening_hours —— ts- 会话生成首屏的观光卡全是
    「无地址」，前端 `it.address ? "📍 " + ...` 判空直接不画。GET 打开
    旧行程时 legacy 的 `_hours_db_pass` 会把地址补回来并落库，所以
    「库里明明有地址、刷新后还是看不到首屏」只出现在生成那一刻。

    这里在装配出口按库行就地补齐——与 legacy `_hours_db_pass` 同口径：
    只填空，绝不覆盖求解/库已给的非空值；占位卡（餐/酒店/腿）无 POI
    行，查不到自然跳过。返回补齐条数供日志。
    """
    if plan is None or store is None:
        return 0
    filled = 0
    for day in getattr(plan, "days", ()) or ():
        for item in getattr(day, "items", ()) or ():
            need_addr = not getattr(item, "address", None)
            need_hours = not getattr(item, "opening_hours", None)
            if not need_addr and not need_hours:
                continue
            # 腿/占位卡没有 poi_id，且名字是「🚕 乘车前往下一站」这类
            # 合成串——按名回查只会白跑一趟
            if getattr(item, "from_city", None) or getattr(item, "to_city", None):
                continue
            detail = None
            poi_id = getattr(item, "poi_id", None)
            if poi_id:
                try:
                    detail = store.get(str(poi_id))
                except Exception:  # noqa: BLE001 - 补链是显示糖，失败不挡交付
                    detail = None
            if detail is None:
                city = getattr(item, "city", None)
                name = getattr(item, "name", None)
                if city and name:
                    try:
                        detail = store.get_by_name(city, name)
                    except Exception:  # noqa: BLE001
                        detail = None
            if not detail:
                continue
            hit = False
            if need_addr and detail.get("address"):
                item.address = detail["address"]
                hit = True
            if not getattr(item, "address_en", None) and detail.get("address_en"):
                item.address_en = detail["address_en"]
            if need_hours and detail.get("opening_hours"):
                item.opening_hours = detail["opening_hours"]
                hit = True
            if not getattr(item, "opening_hours_en", None) and detail.get(
                "opening_hours_en"
            ):
                item.opening_hours_en = detail["opening_hours_en"]
            if hit:
                filled += 1
    return filled


def _pinned_names(session) -> list:
    """用户钉住的卡折进必去（在场保证；槽位由 _pinned_cards→C-04 钉死）。"""
    from app.services.itinerary.models import VisitItem

    plan = getattr(session, "plan", None)
    if plan is None:
        return []
    out = []
    for day in plan.days:
        for item in day.items:
            if isinstance(item, VisitItem) and getattr(item, "pinned", False):
                name = str(item.name or "").strip()
                if name:
                    out.append(name)
    return out


def _pinned_cards(session) -> list:
    """带时刻的钉卡 → [{name, day, start_min}]（C-04 全保位素材）。

    无时刻的钉卡不进 pin（只靠 musts 在场保证）——C-04 的钉是时刻级
    硬钉，无时刻可钉。"""
    from app.services.itinerary.models import VisitItem

    plan = getattr(session, "plan", None)
    if plan is None:
        return []
    out = []
    for day in plan.days:
        for item in day.items:
            if (
                isinstance(item, VisitItem)
                and getattr(item, "pinned", False)
                and item.start_time is not None
                and item.day
            ):
                name = str(item.name or "").strip()
                if name:
                    out.append(
                        {
                            "name": name,
                            "day": int(item.day),
                            "start_min": item.start_time.hour * 60
                            + item.start_time.minute,
                        }
                    )
    return out


def _intake_day_no(date_iso, start_date, days: int, default_day: int) -> Optional[int]:
    """行前日期 → 行程天序（legacy _intake_target_day 同口径）：读不出/
    越界回默认（1=首日/末日）；端点日返回 None（=引擎默认形状，不显式
    传日号，快照 hash 与旧形状兼容）。"""
    import datetime as _dt

    total = max(1, int(days or 1))
    is_arrival = int(default_day) == 1

    def _role_endpoint(d: int) -> Optional[int]:
        # 端点=角色特定（R9-2 修正）：到达的默认端点=首日（末日到达=中途
        # 形状）；离开的默认端点=末日（首日离开=中途形状）。此前
        # day in (1, total) 把「2 天行程 D2 到达」误判端点归 None（live
        # 实锤：day2 地板蒸发）。
        if is_arrival:
            return None if d == 1 else d
        return None if d == total else d

    if not date_iso or not start_date:
        return _role_endpoint(max(1, min(int(default_day), total)))
    try:
        target = _dt.date.fromisoformat(str(date_iso)[:10])
        base = _dt.date.fromisoformat(str(start_date)[:10])
    except ValueError:
        return _role_endpoint(max(1, min(int(default_day), total)))
    day = (target - base).days + 1
    day = max(1, min(day, total))
    return _role_endpoint(day)


def _overlay_chosen_departures(snapshot, session):
    """R19: carry user-selected shuttle times into the snapshot.

    access_chosen_depart/return live on the scenic cards (written
    by the departure-selection surgery). A full engine re-solve
    rebuilt candidates without reading them, silently reverting
    the user's pick to the default bus. Keyed by poi_id with a
    name fallback; frozen dataclasses are re-cast via replace().
    """
    from dataclasses import replace as _replace

    from app.services.itinerary.models import VisitItem

    plan = getattr(session, "plan", None)
    if plan is None:
        return snapshot
    by_poi: dict[str, dict[str, str]] = {}
    by_name: dict[str, dict[str, str]] = {}
    for day in plan.days:
        for item in day.items:
            if not isinstance(item, VisitItem):
                continue
            dep = getattr(item, "access_chosen_depart", None)
            ret = getattr(item, "access_chosen_return", None)
            if not dep and not ret:
                continue
            slot = {
                "depart": str(dep) if dep else "",
                "return": str(ret) if ret else "",
            }
            if item.poi_id:
                by_poi.setdefault(str(item.poi_id), slot)
            if item.name:
                by_name.setdefault(str(item.name), slot)
    if not by_poi and not by_name:
        return snapshot
    out = []
    changed = False
    for cand in snapshot.candidates:
        hit = by_poi.get(str(cand.poi_id)) if cand.poi_id else None
        if hit is None:
            hit = by_name.get(str(cand.name))
        if hit is None:
            out.append(cand)
            continue
        changed = True
        out.append(
            _replace(
                cand,
                chosen_depart=hit.get("depart") or None,
                chosen_return=hit.get("return") or None,
            )
        )
    if not changed:
        return snapshot
    return _replace(snapshot, candidates=tuple(out))


def _sequence_must_days(session) -> dict[str, int] | None:
    """R25：keep 选边时把文字日程的「第N天」带进快照（C-25 硬钉）。"""
    if str(getattr(session, "sequence_choice", "") or "") not in ("keep", "both"):
        return None
    out = {
        str(n): int(d)
        for n, d in (getattr(session, "site_days", None) or {}).items()
        if isinstance(d, int) and d > 0
    }
    return out or None


def _session_snapshot(
    session, store, extra_musts=None, weather_lookup=None, food_rows=None
):
    """R10：会话 → 快照重建（replan/edit 共用）——musts=必去+钉卡+自造点，
    班次/分城/中途日/偏好/首日出发全参数随缝；None=引擎不可载。
    R13-#2：extra_musts=编辑 add 注入的新必去名（尾插去重——重复名会
    造同名多候选，毒 by_name 的保形/映射），绑定链自然兜底。"""
    from .types import validate_snapshot

    musts = list(
        dict.fromkeys(
            [
                *(getattr(session, "must_visits", None) or []),
                *_pinned_names(session),
                *(getattr(session, "created_sites", None) or []),
            ]
        )
    )
    for _extra in extra_musts or []:
        _name = str(_extra or "").strip()
        if _name and _name not in musts:
            musts.append(_name)
    service_rows: list = []
    try:
        from app.services.access_service_store import AccessServiceStore

        services = AccessServiceStore(getattr(store, "_factory", None)).access_services(
            list(session.cities or [])
        )
        service_rows = list(services or [])
    except Exception:
        service_rows = []
    snapshot = snapshot_from_request(
        cities=list(session.cities or []),
        days=max(1, int(getattr(session, "days", 1) or 1)),
        start_date=getattr(session, "start_date", None),
        musts=musts,
        must_days=_sequence_must_days(session),
        store=store,
        weather_lookup=weather_lookup,
        arrival_time=getattr(session, "arrival_time", None),
        departure_time=getattr(session, "departure_time", None),
        arrival_no=getattr(session, "arrival_no", None),
        departure_no=getattr(session, "departure_no", None),
        # R13p（2026-11-22 审计修复）：会话的城际方式也要随缝——此前只传
        # 班次号，intercity_mode 存了也读不到（无班次号的 train/flight 选择丢）
        intercity_mode=getattr(session, "intercity_mode", None),
        avoid=list(getattr(session, "avoid_sites", None) or []),
        preferences=(getattr(session, "preferences", "") or ""),
        city_days=dict(getattr(session, "city_days", None) or {}),
        origin_days=int(getattr(session, "origin_days", 0) or 0),
        service_rows=service_rows,
        day1_start=getattr(session, "comment_day_start", None),
        arrival_day=_intake_day_no(
            getattr(session, "arrival_date", None),
            getattr(session, "start_date", None),
            int(getattr(session, "days", 1) or 1),
            1,
        ),
        departure_day=_intake_day_no(
            getattr(session, "departure_date", None),
            getattr(session, "start_date", None),
            int(getattr(session, "days", 1) or 1),
            int(getattr(session, "days", 1) or 1),
        ),
        food_rows=food_rows,
    )
    # R19: chosen-shuttle overlay before validation; a no-chosen
    # session is a pure passthrough.
    snapshot = _overlay_chosen_departures(snapshot, session)
    if validate_snapshot(snapshot):
        return None
    return snapshot


def edit_session_via_trip_solver(
    session,
    *,
    store,
    ops,
    extra_assumptions=None,
    budget_s: float = 3.0,
    weather_lookup=None,
):
    """R10（2026-11-19 拍板「anywhere legacy exists, switch to cp-sat」）：
    消息 diff 道的引擎编辑重解——F-50 edit_resolve；ops=agent 侧 dict op
    （{kind,name,poi_id,day}，move/delete）。保形=keep 钉（未被动到的
    已排观光卡钉住所在日、时刻自由）。返回 (plan|None, outcome|None)。
    R13-#2：add 类 op（{kind:"add", name, poi_id}，day 不传）走 musts
    注入道——名字尾插快照必去（绑定链兜底、覆盖层保放置），引擎自由
    择位；add 永远可映射（骨架兜底），move/delete 不可映射照旧回落。"""
    from .edit import DiffOp as _EditOp
    from .edit import edit_resolve
    from .entry import ENGINE_CPSAT, engine_flag, serving_ready

    flag = engine_flag()
    # R13h（2026-11-20 深挖）：与 generate/replan 同口径——cpsat 旗下
    # 引擎不可服务（未就绪/快照载入失败/求解失手/退化计划）返回披露型
    # fallback outcome，绝不裸 (None, None) 静默落 legacy 修复管线
    # （编辑缝是 R12 救援契约四缝之一，调用方原从不读 outcome）。
    if flag != ENGINE_CPSAT:
        return None, None  # legacy 模式：卡片修复是正常路径
    if not serving_ready()[0]:
        return None, _disclosed_fallback()
    # R13-#2：add 类 op（{kind:"add", name, poi_id}）不走 DiffOp——名字
    # 注入快照 musts（引擎绑定链精确名→文本匹配→骨架兜底自然处理，
    # 覆盖层保证放置或留痕不吞点）；move/delete 照旧走引擎 DiffOp。
    # 名字缺失的 add=不可映射，整批回落 legacy 原道（绝不静默丢改动）。
    ops = list(ops or [])
    if not ops:
        return None, None
    add_ops = [op for op in ops if (op.get("kind") or "") == "add"]
    edit_ops = [op for op in ops if (op.get("kind") or "") != "add"]
    add_names = []
    for op in add_ops:
        _name = str(op.get("name") or "").strip()
        if not _name:
            return None, None
        add_names.append(_name)
    snapshot = _session_snapshot(
        session,
        store,
        extra_musts=add_names or None,
        weather_lookup=weather_lookup,
    )
    if snapshot is None:
        return None, _disclosed_fallback()
    engine_ops = _dict_ops_to_diffops(snapshot, edit_ops) if edit_ops else []
    if engine_ops is None:
        return None, None

    # keep 钉（day 不动、时刻自由）：未被动到的已排观光卡——比
    # FixedPin（时刻也钉）弱一档，不与晨闸/餐锚/贴锚打架（live 实锤：
    # 时刻硬钉对 C-12c must 豁免面与 C-09 贴锚组合 INFEASIBLE）；
    # 餐/酒店/接驳系统卡不钉（C-09/C-13 模型自管）。
    by_poi = {c.poi_id: c.cid for c in snapshot.candidates if c.poi_id}
    by_name = {c.name: c.cid for c in snapshot.candidates if c.name}
    keep_ops = []
    for card in _seated_cards(session):
        cid = by_poi.get(card["poi_id"]) or by_name.get(card["name"])
        if not cid or cid in {op.cid for op in engine_ops}:
            continue
        keep_ops.append(_EditOp(kind="keep", cid=cid, day=card["day"]))

    # R10b keep 去重守卫：同一 cid 可命中多张已排卡（重名卡分布在不同
    # 天、或 poi/name 两道指到同池行）——day 不同的多个 keep 会让
    # presence 在两天同时为 1，模型矛盾 INFEASIBLE → 编辑道静默回落
    # legacy（用户无感知换引擎）。歧义=不钉：该 cid 的 keep 整组丢弃
    # （让引擎自由放）；同 day 重复只留一个。
    keep_days: dict = {}
    for op in keep_ops:
        keep_days.setdefault(op.cid, []).append(op.day)
    keep_ops = [
        _EditOp(kind="keep", cid=cid, day=day_list[0])
        for cid, day_list in keep_days.items()
        if len(set(day_list)) == 1
    ]

    # R10 修复（P4 遗留）：tier① fill-free 假设投影与「钉 fill presence」
    # 直接矛盾 → 编辑必 INFEASIBLE。被 move/delete/keep 点到的 fill
    # 候选全部升格 requested（用户点名语义，投影纯净）。
    # R13-#2：add 点名的 cid 也进升格面——add 名撞上池内存量 fill 行
    # （poi/名两道解析得到）时升格 requested，同用户点名语义；musts
    # 注入生出的候选本就是 requested，解析不到则此处自然空转。
    add_cids = set()
    for op in add_ops:
        _cid = by_poi.get(op.get("poi_id")) or by_name.get(op.get("name"))
        if _cid:
            add_cids.add(_cid)
    touched = {op.cid for op in engine_ops} | {op.cid for op in keep_ops} | add_cids
    if any(c.kind == "fill" for c in snapshot.candidates if c.cid in touched):
        snapshot = replace(
            snapshot,
            candidates=tuple(
                (
                    replace(
                        c,
                        kind="requested",
                        rid=(c.rid or "edit-%s" % c.cid),
                    )
                    if (c.cid in touched and c.kind == "fill")
                    else c
                )
                for c in snapshot.candidates
            ),
        )

    try:
        outcome = edit_resolve(
            snapshot, None, [*engine_ops, *keep_ops], budget_s=budget_s
        )
    except Exception:
        return None, _disclosed_fallback()
    solution = getattr(outcome, "solution", None)
    _status = str(getattr(outcome, "status", "") or "")
    if (_status == "INFEASIBLE" or solution is None) and keep_ops:
        # R12-H（2026-11-20 用户拍板「排不上按规则删」）：编辑重解不可行时
        # 填充先让位——非必去（不在 session.musts 名册）的 keep 降级重试
        # （必去 keep 硬保；编辑快照 kind/rid 不可靠——测试库全 fill，名
        # 册是唯一真源），让出的卡诚实披露；必去仍排不下才落披露型回落。
        _roster = {str(n).strip() for n in (getattr(session, "must_visits", ()) or ())}
        _roster |= {
            str(getattr(m, "name", "") or "").strip()
            for m in (getattr(snapshot.request, "musts", ()) or ())
        }
        _name_of = {c.cid: str(c.name or "").strip() for c in snapshot.candidates}
        # 只降级 op 触及日的非名册 keep（move=目标日；无日信息=全日）
        _op_days = {op.day for op in engine_ops if getattr(op, "day", None)}
        demoted = [
            op
            for op in keep_ops
            if (not _op_days or op.day in _op_days)
            and _name_of.get(op.cid, "") not in _roster
        ]
        demoted_cids = {op.cid for op in demoted}
        kept_ops = [op for op in keep_ops if op.cid not in demoted_cids]
        if demoted_cids:
            try:
                outcome2 = edit_resolve(
                    snapshot, None, [*engine_ops, *kept_ops], budget_s=budget_s
                )
            except Exception:
                return None, _disclosed_fallback()
            solution2 = getattr(outcome2, "solution", None)
            if solution2 is not None and getattr(outcome2, "ops_applied", None):
                from .assembly.materialize import compact_days, materialize_plan

                plan2 = materialize_plan(solution2, snapshot)
                # R21：编辑链与生成链（solve_trip→assemble）同口径——
                # materialize 产出的是裸求解排期，tier4 截断时可带内部
                # 空洞；compact_days 左压后才落会话。keep 只锁天不锁
                # 时刻（时刻本就自由重解），压缩不越 keep 语义。
                plan2 = compact_days(plan2, snapshot)
                if not _degenerate_plan(plan2):
                    placed2 = {i.cid for i in solution2.items}
                    dropped = sorted({op.cid for op in demoted} - placed2)
                    if dropped and hasattr(outcome2, "disclosures"):
                        _dropped_names = [
                            c.name for c in snapshot.candidates if c.cid in set(dropped)
                        ]
                        outcome2.disclosures = list(
                            getattr(outcome2, "disclosures", []) or []
                        ) + [
                            {
                                "zh": "目标日余量不足，已按规则让位："
                                + "、".join(_dropped_names),
                                "en": "Target day had no room; yielded per "
                                "the rules: " + ", ".join(_dropped_names),
                            }
                        ]
                    if extra_assumptions:
                        plan2.assumptions = list(
                            getattr(plan2, "assumptions", []) or []
                        ) + list(extra_assumptions)
                    return plan2, outcome2
    if solution is None or not getattr(outcome, "ops_applied", None):
        return None, _disclosed_fallback()
    from .assembly.materialize import compact_days, materialize_plan

    plan = materialize_plan(solution, snapshot)
    # R21：同上——编辑重解的裸排期过 compact 再落库。生成链自 11-18
    # 7c2300a 起一直如此（solve_trip→assemble→compact_days），编辑链
    # 漏接正是「天安门 08:46 收旗 → 故宫 10:58」洞的落库点。
    plan = compact_days(plan, snapshot)
    if _degenerate_plan(plan):
        return None, _disclosed_fallback()
    if extra_assumptions:
        plan.assumptions = list(getattr(plan, "assumptions", []) or []) + list(
            extra_assumptions
        )
    return plan, outcome


def _dict_ops_to_diffops(snapshot, ops):
    """R10：agent 侧 dict op（{kind,name,poi_id,day}）→ 引擎 DiffOp——
    cid 按 poi/name 匹配；同名多行=歧义不进 by_name（只信 poi_id；两道
    都无 → None 让调用方回落 legacy，绝不按「第一个同名」错钉别的卡）。"""
    from .edit import DiffOp as _Op

    name_cids: dict = {}
    for c in snapshot.candidates:
        if c.name:
            name_cids.setdefault(c.name, set()).add(c.cid)
    by_name = {
        name: next(iter(cids)) for name, cids in name_cids.items() if len(cids) == 1
    }
    by_poi = {}
    for c in snapshot.candidates:
        if c.poi_id:
            by_poi.setdefault(c.poi_id, c.cid)
    out = []
    for op in ops or []:
        cid = by_poi.get(op.get("poi_id")) or by_name.get(op.get("name"))
        if not cid:
            return None
        kind = op.get("kind")
        if kind == "move":
            day = op.get("day")
            if not day:
                return None
            out.append(_Op(kind="move", cid=cid, day=int(day)))
        elif kind == "delete":
            out.append(_Op(kind="delete", cid=cid))
        else:
            return None
    return out or None


def _seated_cards(session) -> list:
    """R10：已排卡的 (name, poi_id, day, start_min)——编辑保形素材
    （全部有时刻的观光/餐卡，不只 pinned）。"""
    from app.services.itinerary.models import VisitItem

    plan = getattr(session, "plan", None)
    if plan is None:
        return []
    out = []
    for day in plan.days:
        for item in day.items:
            if (
                isinstance(item, VisitItem)
                and item.start_time is not None
                # R10：只钉观光卡——餐/酒店/接驳是系统合成卡（C-09/C-13
                # 模型侧自管），钉它们会与餐槽/酒店锚约束冲突（live 实锤）
                and (item.category or "")
                not in ("food", "hotel", "transport", "transfer")
            ):
                name = str(item.name or "").strip()
                if name:
                    out.append(
                        {
                            "name": name,
                            "poi_id": getattr(item, "poi_id", None),
                            "day": int(getattr(item, "day", day.day) or day.day),
                            "start_min": item.start_time.hour * 60
                            + item.start_time.minute,
                        }
                    )
    return out


def _disclosed_fallback():
    """R13（#1 修复）：cpsat 旗下引擎不可服务（快照验证失败/未就绪）→
    返回披露型 fallback outcome——绝不裸 (None, None) 静默落 legacy
    （旧行为绕过了 api 缝的披露 append=违反「绝不静默」原则）。"""
    from .entry import (
        ENGINE_CPSAT,
        ENGINE_LEGACY,
        FALLBACK_DISCLOSURE,
        SolveOutcome,
    )

    return SolveOutcome(
        engine=ENGINE_LEGACY,
        requested=ENGINE_CPSAT,
        fallback=True,
        disclosures=[dict(FALLBACK_DISCLOSURE)],
    )
