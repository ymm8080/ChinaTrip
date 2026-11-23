"""F-23 lexicographic objectives (P1-D).

The four expressions are deliberately kept separate. ``solve`` optimizes them
in order and fixes each proven optimum before moving to the next tier; a large
fill/quality reward can therefore never purchase requested-coverage loss.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..inputs.hours_caps import EVENING_OK_BEST
from ..inputs.weather import RAIN_INDOOR_PENALTY, is_rainy
from .c01_c04 import day_date
from .slack import SlackFlags

if TYPE_CHECKING:  # pragma: no cover
    from ..inputs.enrich import EnrichedSnapshot
    from .vars import VarBundle

FILL_REWARD = 100
# R1 设计镜像（打分器软罚一一对应、仅影响放置不涉时刻）：
# venue_strand 拆簇 −60（近簇跨日无伴）→ 同日共处 +60；
# no_entertainment −40/程（2026-11-03 拍板）→ 娱乐在场 +40
NEAR_PAIR_COLOCATE_REWARD = 100  # R4r2: 压过 −60 拆簇罚的携带成本
# R4r2: C-12c 上午单点闸的伴随激励——没有它求解器会整体避开上午
# （0 个上午点不违反 ≤1 闸）导致 blank_morning −80/天
MORNING_OCCUPIED_REWARD = 40
CITYWALK_AFTERNOON_REWARD = 12  # 2026-11-06 拍板镜像：CITYWALK 倾向下午场
BIG_FIRST_REWARD = 12  # 2026-11-04 拍板镜像：大点先排（池 ≤20 才建对）
AFTERNOON_BIG_SINGLE_REWARD = 12  # 同拍板软面：下午大点 ≤1/日（镜像 scorer −12）
# R8 偏好镜像（2026-11-18 拍板「偏好重排也要换 CP-SAT」）：偏好同类
# 候选在场 +40/日——与 legacy「偏好位在 tier 之前」同向；同类可多个
# （奖励逐张叠加无衰减=拍板「偏好可以是同一类型多个景点」）
PREFERENCE_CATEGORY_REWARD = 40
# R12-C3（2026-11-19 拍板「餐厅放在午餐/晚餐卡上」）：绑定槽按时段
# 对齐——午段（<15:00）落午餐卡、晚段（≥15:00）落晚餐卡。软奖励：
# 流式时刻仍优先，槽标签跟时刻走（杀「09:00 的晚餐卡」倒挂）。
MEAL_SLOT_BAND_SPLIT = 15 * 60
# R12-H3（2026-11-20 用户拍板「同样的PRIORITY 并且天气允许，先安排
# 远郊。远郊优先安排早晨 & 单天只有空闲才插入其它」）：远郊日序/
# 开场软拉引——词法最末层=纯平手破除，不扰动覆盖/质量层；雨天硬
# 闸限可行面，拉引只在可行面内生效；出程下限 08:30 在 C-08（
# R12-H4）；「单天只有空闲才插其它」=F4b 日预算（远郊日同款）。
REMOTE_DAY_WEIGHT = 60  # ×请求卡数=族级选天主张（R12-H6b）
# R12-H8（2026-11-20 用户纠正「不是远郊受保护，而是高优先级的 MUST
# VISIT 受保护；长城是优先级最高的」）：删点序=优先级=清单位序
# （_coverage 列表位序权重），无远郊专项盾。
REMOTE_EARLY_WEIGHT = 1
# R12-H6（2026-11-20 用户拍板「按景点优先级和天气选天。如果景
# 点间优先级一致，远郊优先好天」）：重要性加权天序拉引——优先级
# 高的先挑天；同优先级下远郊额外面 +REMOTE_DAY_WEIGHT 胜出
# （好天=雨天硬闸限可行面，拉引只在可行面内生效）。
PRIORITY_DAY_WEIGHT = 30
MEAL_SLOT_BAND_REWARD = 25
# R12-D（2026-11-19 拍板「尽量不要同样的菜肴——两家烤鸭店同日
# 不合适」）：同菜系餐馆同日分占午晚双槽=重罚；跨天重复=轻罚
# （「尽量」=软罚：池内无替代时不阻断）。
MEAL_SAME_CUISINE_DAY_PENALTY = 150
MEAL_SAME_CUISINE_TRIP_PENALTY = 60
# R12-F（2026-11-19 用户拍板「尽量把重要的时间长的大景点放一天比较
# 早的时间」）：必去大点（requested 且时长>80）每分钟提早拉力——
# 天安门后故宫先于天坛（距离相近时优先级+时长破平局），填充大点
# （景山）不吃此拉力、只进剩余时段。0.25/min≈半天差 100+，足够翻
# 平局、不压走行地理。
BIG_MUST_MIN_DURATION = 80
# R12-F2：晚开分段罚（CP-SAT 线性表达式只吃整系数——0.25/min 浮点直
# 接炸 40 测）。镜像打分器 late_entries 口径：≥12:30 罚 40、≥14:00 再
# 罚 80——必去大点让出下午/傍晚给填充，天安门后故宫先于天坛。
BIG_MUST_LATE_BANDS = ((12 * 60 + 30, 40), (14 * 60, 80), (15 * 60, 120))
# R20（2026-11-23 用户令「大唐不夜城步行街 BEST VISIT TIME IS EVENING, WHY IT IS
# ARRANGED IN THE MORNING」）：库内 evening/sunset 卡（83+2 行：夜街/夜游船/夜市/
# 灯光秀/主题街区）此前在引擎里只换入场帽豁免（hours_caps.entry_cap_minutes），
# 偏好层唯一的强晚排力只认 show——「夜里才好看」这个语义在引擎零消费，夜街被
# 必去大点晚开罚带＋大点先排＋晨间占用＋紧凑压早合力推进上午/正午（探针实锤
# 10:00/12:01）。镜像反向晚排带（逐档叠加）：17:00→+120、18:00→+180、19:00→
# +240——90 分钟夜街（如 大唐不夜城步行街 dur=90）压到 19:30-21:00 灯火最盛
# 段；时长长的夜点最晚开场受限（日窗 21:00 收口）时仍稳拿低档。峰值 ≥2×
# FILL_REWARD：稠密日里「夜街落晚上」强过保一张填充卡，也压过 QUALITY 上限
# 200 与晚餐收缩罚。晚间不可行（远郊日回程班等）时带值拿不到 → 自然回落
# 白天，fail-open 不加硬约束。
EVENING_LATE_BANDS = ((17 * 60, 120), (18 * 60, 60), (19 * 60, 60))
MORNING_MINUTE = 12 * 60
ENTERTAINMENT_PRESENT_REWARD = 40
CATEGORY_DIVERSITY_REWARD = 20
QUALITY_SCALE = 100
# RATE 层（2026-11-22 用户令「选点按 PRIORITY RANK, WEATHER, rate 而非
# amap rate」）：填充候选的库内数据分奖励上限——有界，让 rate 生效于
# 填充选择但压不住天气层罚项/同菜系罚项。
FILL_QUALITY_REWARD_CAP = 200
# P2-B3 evidence: at 4/min a dense day's typ-shrinkage outbids
# FILL_REWARD (g01 both-fills net -10 at tier ①) and days starve; 1/min
# fixes density but trips the P0 audit (8-min transfer gaps, 17km walk
# days) until the taxi-call buffer / meal-gap / afternoon-big caps land.
# Kept 4/min through iter2 (constraints landed); iter3 blockers: walk-cap
# 15km/day + audit counts the materialised return card as a big visit.
DURATION_DEVIATION_PENALTY = 4
MEAL_DURATION_DEVIATION_PENALTY = 1
INDOOR_DINNER_REWARD = 80  # 2026-11-18 用户拍板：晚饭通常优先室内
WEEKEND_PENALTY = 90  # legacy _MUST_WEEKEND_PENALTY
RAIN_WEEKEND_EXTRA = 120  # legacy _MUST_RAIN_WEEKEND_EXTRA
REMOTE_RAIN_EXTRA = 60  # legacy _MUST_REMOTE_RAIN_EXTRA
SHOW_EARLY_PENALTY = 10_000  # legacy SHOW_EARLY_SESSION_PENALTY
SHOW_LATE_SESSION_MINUTES = 15 * 60


@dataclass
class ObjectiveTier:
    name: str
    expression: object
    sense: str  # min | max


def _coverage(bundle: "VarBundle", enriched: "EnrichedSnapshot") -> ObjectiveTier:
    request = enriched.snapshot.request
    # R12-H10（2026-11-20 用户拍板「是你应该按照库里的数据来排。。
    # 不是我给的」）：删点序=库内数据分（live 绑定落 quality：名录
    # tags/来源+真值评分[名录缺评 4.8 地板]+时长档）；语料/旧快照
    # quality 空=零漂移，importance 仍为乘子。
    weights = {r.rid: max(1, r.importance) for r in request.musts}
    weights.update({r.rid: 1 for r in request.wishes})
    _q_by_rid: dict[str, int] = {}
    for c in enriched.snapshot.candidates:
        if c.rid and c.kind == "requested" and getattr(c, "quality", None):
            try:
                _q_by_rid[c.rid] = max(_q_by_rid.get(c.rid, 0), int(float(c.quality)))
            except Exception:
                pass
    for rid, q in _q_by_rid.items():
        if rid in weights:
            weights[rid] *= max(1, q)
    # R12-H10b：先排长城（用户算法第一步先排的远郊=锚）——锚不参与
    # 删点序（权重抬到城内最高之上）；真排不下仍诚实弃排+披露。
    _remote_rids = {
        c.rid
        for c in enriched.snapshot.candidates
        if c.rid and (c.poi_id or c.cid) in enriched.access_by_poi
    }
    if _remote_rids:
        _city_ws = [w for rid, w in weights.items() if rid not in _remote_rids]
        if _city_ws:
            _top = max(_city_ws)
            for rid in _remote_rids:
                if rid in weights:
                    weights[rid] = max(weights[rid], _top + 1)
    expression = sum(
        bundle.unplaced[rid] * weights.get(rid, 1) for rid in bundle.unplaced
    )
    return ObjectiveTier("coverage", expression, "min")


def _binding_lit(bundle, cand, day: int, slot: str):
    """餐馆候选在 (day, slot) 的绑定真值：锁定槽=在场；any-槽=
    meal_bound 自由布尔；非餐类/他槽=None。"""
    if (cand.category or "") != "food":
        return None
    ms = getattr(cand, "meal_slot", None)
    if ms == slot:
        return bundle.presence[(cand.cid, day)]
    if ms == "any":
        return bundle.meal_bound.get((cand.cid, day, slot))
    return None


def _same_cuisine_penalty(bundle, enriched) -> list:
    """R12-D：同菜系餐馆不重样——同日午晚双槽重罚/跨天轻罚。"""
    model = bundle.model
    foods = [
        c
        for c in enriched.snapshot.candidates
        if (c.category or "") == "food"
        and getattr(c, "meal_slot", None)
        and getattr(c, "cuisine", None)
    ]
    negative: list = []
    for i, c1 in enumerate(foods):
        for c2 in foods[i + 1 :]:
            if c1.cuisine != c2.cuisine:
                continue
            for day in bundle.days:
                for d2 in bundle.days:
                    weight = (
                        MEAL_SAME_CUISINE_DAY_PENALTY
                        if day == d2
                        else MEAL_SAME_CUISINE_TRIP_PENALTY
                    )
                    # 4 种槽组合全枚举：同日同槽天然不可行（同时刻重叠），
                    # 跨日同槽（两天都吃烤鸭午餐）必须吃到罚项。
                    for a_slot in ("lunch", "dinner"):
                        for b_slot in ("lunch", "dinner"):
                            la = _binding_lit(bundle, c1, day, a_slot)
                            lb = _binding_lit(bundle, c2, d2, b_slot)
                            if la is None or lb is None:
                                continue
                            both = model.NewBoolVar(
                                "sc_%s_%s_%d_%d" % (c1.cid, c2.cid, day, d2)
                                + a_slot[0]
                                + b_slot[0]
                            )
                            model.AddBoolAnd([la, lb]).OnlyEnforceIf(both)
                            model.AddBoolOr([la.Not(), lb.Not()]).OnlyEnforceIf(
                                both.Not()
                            )
                            negative.append(weight * both)
    return negative


def _preference(
    bundle: "VarBundle",
    enriched: "EnrichedSnapshot",
    slack: SlackFlags | None = None,
) -> ObjectiveTier:
    snapshot = enriched.snapshot
    model = bundle.model
    relax_tod = bool(slack and slack.relax_time_of_day)
    relax_wx = bool(slack and slack.relax_weather)
    positive: list = []
    negative: list = []
    weather_by_key = {(poi, day): cond for poi, day, cond in snapshot.weather}
    # R12-D 同菜系不重样（软罚，见 _same_cuisine_penalty）
    negative += _same_cuisine_penalty(bundle, enriched)

    # R8：偏好解析一次（同源 legacy _preference_tokens）
    pref_tokens: tuple = ()
    pref_show = False
    _pref_text = (getattr(snapshot.request, "preferences", "") or "").strip()
    if _pref_text:
        try:
            from app.services.trip_orchestrator.nlu import _preference_tokens as _ptoks

            pref_tokens, pref_show = _ptoks(_pref_text)
        except Exception:
            pref_tokens = ()

    for cand in snapshot.candidates:
        tier = enriched.tiers[cand.cid]
        deviation = model.NewIntVar(0, tier[2], "obj_dd_%s" % cand.cid)
        model.AddAbsEquality(deviation, bundle.dur[cand.cid] - tier[1])
        negative.append(DURATION_DEVIATION_PENALTY * deviation)
        # R12-F4（2026-11-19 用户拍板「填充弹性只在傍晚入选闸适用；
        # 故宫要收缩则景山就不该插入」）：必去压缩×填充互斥走 c09
        # 硬闸（_r12f_fill_yields_gate）——软罚已撤（×2 曾漂移 g01
        # canon：remote 班次 570→450 实锤）。
        pref_bonus = 0
        if pref_tokens:
            try:
                from app.services.trip_orchestrator.nlu import (
                    _pref_category_hit as _phit,
                )

                if _phit(
                    {"name": cand.name, "category": cand.category},
                    pref_tokens,
                    pref_show,
                ):
                    pref_bonus = PREFERENCE_CATEGORY_REWARD
            except Exception:
                pref_bonus = 0

        # R12-H10c：quality 双域——live 库行是 int 数据分（_data_priority_
        # score，1-100+）；快照/语料行是 float 0-1。必去两域同语义 ×100
        # （live 77→7700，语料 0.9→90）；填充按域分支：live 域吃原始分
        # ×2 有界（4.0→80、4.5→90、5A 4.7→154、4.8 名录→cap 200，保
        # 分辨率）；语料 float 域维持 ×100 旧语义（shadow 对照零漂移）。
        _q = float(cand.quality or 0)
        if cand.rid:
            quality = int(round(_q * QUALITY_SCALE))
        elif _q > 2:  # live 库内数据分域
            quality = min(int(_q) * 2, FILL_QUALITY_REWARD_CAP)
        else:  # 快照/语料 float 域
            quality = int(round(_q * QUALITY_SCALE))
        # R20：夜属性卡不吃必去晚开罚带（口径同 is_big_site 的 EVENING_OK_BEST
        # 豁免）——否则晚开罚(−120)与晚排带(+240)同层精确对消，夜街照旧上午。
        big_must = bool(
            cand.rid
            and int(cand.suggested_duration_min or 0) > BIG_MUST_MIN_DURATION
            and (cand.best_visit_time or "").lower() not in EVENING_OK_BEST
        )
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            if quality:
                positive.append(quality * lit)
            if big_must:
                # R12-F2：必去大点晚开分段罚（不在场 start=0 天然不触发）。
                for _threshold, _weight in BIG_MUST_LATE_BANDS:
                    _late = model.NewBoolVar(
                        "bml_%s_%d_%d" % (cand.cid, day, _threshold)
                    )
                    model.Add(
                        bundle.start[(cand.cid, day)] >= _threshold
                    ).OnlyEnforceIf(_late)
                    model.Add(bundle.start[(cand.cid, day)] < _threshold).OnlyEnforceIf(
                        _late.Not()
                    )
                    negative.append(_weight * _late)
            if pref_bonus:
                positive.append(pref_bonus * lit)
            if not cand.rid:
                positive.append(FILL_REWARD * lit)
            if (
                cand.category == "food"
                and getattr(cand, "meal_slot", None) == "dinner"
                and str(cand.indoor or "").lower() in {"yes", "true", "1", "indoor"}
            ):
                positive.append(INDOOR_DINNER_REWARD * lit)
            if cand.category == "food" and getattr(cand, "meal_slot", None) == "any":
                # R12-C3：any-槽绑定按时段对齐（meal_bound 里的自由
                # 绑定布尔——lunch↔午段 / dinner↔晚段）。
                for slot in ("lunch", "dinner"):
                    blit = bundle.meal_bound.get((cand.cid, day, slot))
                    if blit is None:
                        continue
                    band = model.NewBoolVar("msb_%s_%d_%s" % (cand.cid, day, slot))
                    if slot == "lunch":
                        model.Add(
                            bundle.start[(cand.cid, day)] < MEAL_SLOT_BAND_SPLIT
                        ).OnlyEnforceIf(band)
                        model.Add(
                            bundle.start[(cand.cid, day)] >= MEAL_SLOT_BAND_SPLIT
                        ).OnlyEnforceIf(band.Not())
                    else:
                        model.Add(
                            bundle.start[(cand.cid, day)] >= MEAL_SLOT_BAND_SPLIT
                        ).OnlyEnforceIf(band)
                        model.Add(
                            bundle.start[(cand.cid, day)] < MEAL_SLOT_BAND_SPLIT
                        ).OnlyEnforceIf(band.Not())
                    both = model.NewBoolVar("msbb_%s_%d_%s" % (cand.cid, day, slot))
                    model.AddBoolAnd([blit, band]).OnlyEnforceIf(both)
                    model.AddBoolOr([blit.Not(), band.Not()]).OnlyEnforceIf(both.Not())
                    positive.append(MEAL_SLOT_BAND_REWARD * both)

            day_dt = day_date(snapshot.request.start_date, day)
            iso = day_dt.isoformat() if day_dt is not None else None
            condition = weather_by_key.get((cand.poi_id, iso))
            rainy = is_rainy(condition)
            if (
                cand.rid
                and day_dt is not None
                and day_dt.weekday() >= 5
                and not (relax_tod or relax_wx)
            ):
                negative.append(WEEKEND_PENALTY * lit)
                if rainy:
                    negative.append(RAIN_WEEKEND_EXTRA * lit)
            if rainy and not relax_wx:
                weather = enriched.weather.get((cand.cid, iso))
                if weather:
                    negative.append(int(weather["penalty"]) * lit)
                else:
                    # Indoor requested/fill items retain the legacy lighter
                    # rainy-day cost instead of the outdoor 240-minute cost.
                    negative.append(RAIN_INDOOR_PENALTY * lit)
                if cand.rid and cand.remote:
                    negative.append(REMOTE_RAIN_EXTRA * lit)

            if (cand.best_visit_time or "").lower() == "show" and not relax_tod:
                early = model.NewBoolVar("obj_se_%s_%d" % (cand.cid, day))
                model.Add(early <= lit)
                start = bundle.start[(cand.cid, day)]
                model.Add(start < SHOW_LATE_SESSION_MINUTES).OnlyEnforceIf([lit, early])
                model.Add(start >= SHOW_LATE_SESSION_MINUTES).OnlyEnforceIf(
                    [lit, early.Not()]
                )
                negative.append(SHOW_EARLY_PENALTY * early)
            bvt = (cand.best_visit_time or "").lower()
            if bvt in ("evening", "sunset") and not relax_tod:
                # R20 晚排带（见 EVENING_LATE_BANDS 注）：evening/sunset 卡偏好
                # 晚间开场；带值只在场时计（late<=lit），不在场不白送。
                start = bundle.start[(cand.cid, day)]
                for _threshold, _weight in EVENING_LATE_BANDS:
                    late = model.NewBoolVar(
                        "obj_evl_%s_%d_%d" % (cand.cid, day, _threshold)
                    )
                    model.Add(late <= lit)
                    model.Add(start >= _threshold).OnlyEnforceIf([lit, late])
                    model.Add(start < _threshold).OnlyEnforceIf([lit, late.Not()])
                    positive.append(_weight * late)

    # R1 拆簇镜像：近距对（打分器 _near_mate_km 同源口径，取
    # solver.NEAR_SAMEDAY_KM）同日共处奖励——O(对数) 公式：dayVar
    # 相等 ⇔ 同日（双方都已排），不按 天×对 展开防爆项
    from app.services.itinerary.solver import NEAR_SAMEDAY_KM as _near_km

    from ..inputs.travel import haversine_km as _hk

    cands = list(snapshot.candidates)
    if len(cands) > 20:
        cands = []  # R5: trip 规模跳过 colocate（dayVar 对是 tier② 主成本）
    for i, a in enumerate(cands):
        for b in cands[i + 1 :]:
            # requested-involved pruning (R3a): fill×fill colocate is
            # secondary — keeps the pair count provable at trip scale
            # (g11 tier② timed out at 0.4 dtime with all-pairs)
            if not (a.rid or b.rid):
                continue
            if a.lon is None or a.lat is None or b.lon is None or b.lat is None:
                continue
            if a.city and b.city and a.city != b.city:
                continue  # C-07 已禁跨城同日，不必奖励
            if _hk(a.lon, a.lat, b.lon, b.lat) > _near_km:
                continue
            day_a = sum(day * bundle.presence[(a.cid, day)] for day in bundle.days)
            day_b = sum(day * bundle.presence[(b.cid, day)] for day in bundle.days)
            bp = model.NewBoolVar("obj_bp_%s_%s" % (a.cid, b.cid))
            pa = model.NewBoolVar("obj_pa_%s" % a.cid)
            pb = model.NewBoolVar("obj_pb_%s" % b.cid)
            model.AddMaxEquality(pa, [bundle.presence[(a.cid, d)] for d in bundle.days])
            model.AddMaxEquality(pb, [bundle.presence[(b.cid, d)] for d in bundle.days])
            model.AddBoolAnd([pa, pb]).OnlyEnforceIf(bp)
            model.AddBoolOr([pa.Not(), pb.Not()]).OnlyEnforceIf(bp.Not())
            rb = model.NewBoolVar("obj_near_%s_%s" % (a.cid, b.cid))
            # 只锁等向+双排守卫：最大化驱动 rb=1（等日且双排）；
            # 双未排（0==0）拿不到——bp=0 挡住。无 ≠ 分支（会双未排矛盾）
            model.Add(day_a == day_b).OnlyEnforceIf(rb)
            model.AddImplication(rb, bp)
            positive.append(NEAR_PAIR_COLOCATE_REWARD * rb)

    # R1 娱乐镜像：全程 ≥1 娱乐/演出类在场
    ent_lits = [
        bundle.presence[(cand.cid, day)]
        for cand in snapshot.candidates
        if (cand.category or "") == "entertainment"
        or (cand.best_visit_time or "").lower() == "show"
        for day in bundle.days
    ]
    if ent_lits:
        ent_any = model.NewBoolVar("obj_ent_any")
        model.AddMaxEquality(ent_any, ent_lits)
        positive.append(ENTERTAINMENT_PRESENT_REWARD * ent_any)

    # R4r2 晨占用：每活动日 <12:00 有已排点 +80（与 C-12c ≤1 闸配套
    for day in bundle.days:
        occ = model.NewBoolVar("obj_mocc_%d" % day)
        earlies = []
        for cand in snapshot.candidates:
            if (cand.category or "") in ("food", "hotel", "transport"):
                continue
            lit = bundle.presence[(cand.cid, day)]
            early = model.NewBoolVar("obj_early_%s_%d" % (cand.cid, day))
            model.Add(early == 0).OnlyEnforceIf(lit.Not())
            model.Add(bundle.start[(cand.cid, day)] < MORNING_MINUTE).OnlyEnforceIf(
                [lit, early]
            )
            model.Add(bundle.start[(cand.cid, day)] >= MORNING_MINUTE).OnlyEnforceIf(
                [lit, early.Not()]
            )
            earlies.append(early)
        if earlies:
            model.AddMaxEquality(occ, earlies)
            positive.append(MORNING_OCCUPIED_REWARD * occ)

    # R4r3 CITYWALK 下午场镜像（2026-11-06 拍板）：≥13:00 开场 +12
    for cand in snapshot.candidates:
        if (cand.category or "") != "citywalk":
            continue
        for day in bundle.days:
            lit = bundle.presence[(cand.cid, day)]
            pm = model.NewBoolVar("obj_cwpm_%s_%d" % (cand.cid, day))
            model.Add(pm == 0).OnlyEnforceIf(lit.Not())
            model.Add(bundle.start[(cand.cid, day)] >= 13 * 60).OnlyEnforceIf([lit, pm])
            model.Add(bundle.start[(cand.cid, day)] < 13 * 60).OnlyEnforceIf(
                [lit, pm.Not()]
            )
            positive.append(CITYWALK_AFTERNOON_REWARD * pm)

    # R4r4 大点先排镜像（2026-11-04 拍板）：同日 big 开场不晚于 light
    # ——池 ≤20 才建对（trip 规模跳过，防 tier① 变慢）
    if len(snapshot.candidates) <= 20:
        from ..inputs.hours_caps import is_big_site

        bigs, lights = [], []
        for cand in snapshot.candidates:
            if (cand.category or "") in ("food", "hotel", "transport", "entertainment"):
                continue
            tier_ = enriched.tiers[cand.cid]
            if is_big_site(
                duration_min=tier_[1],
                category=cand.category,
                best_visit_time=cand.best_visit_time,
                tier=cand.tier,
            ):
                bigs.append(cand)
            else:
                lights.append(cand)
        for big in bigs:
            for light in lights:
                if big.city and light.city and big.city != light.city:
                    continue
                for day in bundle.days:
                    both = model.NewBoolVar(
                        "obj_bf_%s_%s_%d" % (big.cid, light.cid, day)
                    )
                    model.AddBoolAnd(
                        [
                            bundle.presence[(big.cid, day)],
                            bundle.presence[(light.cid, day)],
                        ]
                    ).OnlyEnforceIf(both)
                    model.AddBoolOr(
                        [
                            bundle.presence[(big.cid, day)].Not(),
                            bundle.presence[(light.cid, day)].Not(),
                        ]
                    ).OnlyEnforceIf(both.Not())
                    first = model.NewBoolVar(
                        "obj_bf1_%s_%s_%d" % (big.cid, light.cid, day)
                    )
                    model.Add(
                        bundle.start[(big.cid, day)] <= bundle.start[(light.cid, day)]
                    ).OnlyEnforceIf([both, first])
                    model.Add(
                        bundle.start[(big.cid, day)] > bundle.start[(light.cid, day)]
                    ).OnlyEnforceIf([both, first.Not()])
                    positive.append(BIG_FIRST_REWARD * first)

    # R5 下午大点 ≤1 镜像（拍板「一般」软面）：计下午大点数，≤1 奖 +12
    if len(snapshot.candidates) <= 20:
        from ..inputs.hours_caps import is_big_site as _ibs

        for day in bundle.days:
            pm_bigs = []
            for cand in snapshot.candidates:
                if (cand.category or "") in (
                    "food",
                    "hotel",
                    "transport",
                    "entertainment",
                ):
                    continue
                tier_ = enriched.tiers[cand.cid]
                if not _ibs(
                    duration_min=tier_[1],
                    category=cand.category,
                    best_visit_time=cand.best_visit_time,
                    tier=cand.tier,
                ):
                    continue
                lit = bundle.presence[(cand.cid, day)]
                pm = model.NewBoolVar("obj_apm_%s_%d" % (cand.cid, day))
                model.Add(pm == 0).OnlyEnforceIf(lit.Not())
                model.Add(bundle.start[(cand.cid, day)] >= 13 * 60).OnlyEnforceIf(
                    [lit, pm]
                )
                model.Add(bundle.start[(cand.cid, day)] < 13 * 60).OnlyEnforceIf(
                    [lit, pm.Not()]
                )
                pm_bigs.append(pm)
            if len(pm_bigs) > 1:
                single = model.NewBoolVar("obj_apm1_%d" % day)
                model.Add(sum(pm_bigs) <= 1).OnlyEnforceIf(single)
                model.Add(sum(pm_bigs) >= 2).OnlyEnforceIf(single.Not())
                positive.append(AFTERNOON_BIG_SINGLE_REWARD * single)

    categories = sorted({c.category or "other" for c in snapshot.candidates})
    for category in categories:
        members = [
            c for c in snapshot.candidates if (c.category or "other") == category
        ]
        for day in bundle.days:
            active = model.NewBoolVar("obj_cat_%s_%d" % (category, day))
            model.AddMaxEquality(
                active, [bundle.presence[(c.cid, day)] for c in members]
            )
            positive.append(CATEGORY_DIVERSITY_REWARD * active)

    for (slot, _day), meal in bundle.meal_vars.items():
        default = 60 if slot == "lunch" else 90
        deviation = model.NewIntVar(0, 90, "obj_md_%s_%d" % (slot, _day))
        model.AddAbsEquality(deviation, meal["dur"] - default)
        negative.append(MEAL_DURATION_DEVIATION_PENALTY * deviation)

    expression = sum(positive) - sum(negative)
    return ObjectiveTier("preference", expression, "max")


def _travel(bundle: "VarBundle", enriched: "EnrichedSnapshot") -> ObjectiveTier:
    return ObjectiveTier("travel", sum(bundle.travel_terms), "min")


def _makespan(bundle: "VarBundle", enriched: "EnrichedSnapshot") -> ObjectiveTier:
    model = bundle.model
    terms: list = []
    for day in bundle.days:
        end = model.NewIntVar(0, 24 * 60 + 300, "obj_day_end_%d" % day)
        ends = [bundle.active_end[(c.cid, day)] for c in enriched.snapshot.candidates]
        ends.extend(
            meal["active_end"]
            for (slot, d), meal in bundle.meal_vars.items()
            if d == day
        )
        model.AddMaxEquality(end, ends or [0])
        bundle.day_end_vars[day] = end
        terms.append(end)

    # C-08's chosen outbound/return departures are zero when absent. Including
    # them here implements the early-bus preference without disturbing any
    # higher tier or allowing lunch to choose the outbound departure.
    terms.extend(bundle.active_dep_vars.values())
    terms.extend(bundle.active_ret_vars.values())
    return ObjectiveTier("makespan_early_access", sum(terms), "min")


def _remote_first(bundle: "VarBundle", enriched: "EnrichedSnapshot") -> ObjectiveTier:
    """R12-H3/H6 选天与远郊优先（词法最末层=纯平手破除，不扰动覆
    盖/质量层）：①按景点优先级选天=重要性加权天序拉引（优先级高
    的先挑天；地理聚族同 rid 同拉=族整体选天）；②优先级一致时远郊
    优先好天=远郊额外日拉引（雨天硬闸限可行面，拉引只在可行面内
    生效）；③远郊优先早晨=开场软拉引（出程下限 08:30 在 C-08）；
    ④单天只有空闲才插其它=F4b 日预算 + C-06 返程后至多一卡。
    远郊游览卡与必去同优先级=覆盖权重/晚开分段罚已通用（记档）。
    """
    request = enriched.snapshot.request
    imp = {
        r.rid: max(1, int(getattr(r, "importance", 3) or 3))
        for r in list(getattr(request, "musts", ()) or ())
    }
    remote = {
        c.cid
        for c in enriched.snapshot.candidates
        if (c.poi_id or c.cid) in enriched.access_by_poi
    }
    model = bundle.model
    terms: list = []
    for c in enriched.snapshot.candidates:
        if not c.rid:
            continue  # 拉引只对请求卡（fills 无选天权，F4b 管入场）
        for day in bundle.days:
            present = bundle.presence[(c.cid, day)]
            w = PRIORITY_DAY_WEIGHT * imp.get(c.rid, 3)
            if c.cid in remote:
                # R12-H6b：远郊的选天主张是族级——按请求卡总数缩放，
                # 压过任意数量同优先级城内卡的合计拉引（2026-11-20
                # 用户拍板「优先级一致，远郊优先好天」；词法最末层，
                # 只在覆盖/质量/行程等前层平手时生效）。
                w += REMOTE_DAY_WEIGHT * max(1, len(imp))
            terms.append(w * day * present)
            if c.cid in remote:
                a = model.NewIntVar(0, 1440, "rf_%s_%d" % (c.cid, day))
                model.Add(a == bundle.start[(c.cid, day)]).OnlyEnforceIf(present)
                model.Add(a == 0).OnlyEnforceIf(present.Not())
                terms.append(REMOTE_EARLY_WEIGHT * a)
                # R12-H15（2026-11-20 用户拍板「慕田峪 13:28 结束应该搭
                # 乘 14:30 的 SHUTTLE BUS」）：返程同样拉最早可行班——早
                # 回城才有当天余量（远郊日的「时间有多余就插一个」由此
                # 活化；absent 时 active_ret=0 无贡献）。
                _ret = bundle.active_ret_vars.get((c.cid, day))
                if _ret is not None:
                    terms.append(REMOTE_EARLY_WEIGHT * _ret)
    if not terms:
        return ObjectiveTier("remote_first", 0, "min")
    return ObjectiveTier("remote_first", sum(terms), "min")


def build_objectives(
    bundle: "VarBundle",
    enriched: "EnrichedSnapshot",
    slack: SlackFlags | None = None,
) -> list[ObjectiveTier]:
    return [
        _coverage(bundle, enriched),
        _preference(bundle, enriched, slack),
        _travel(bundle, enriched),
        _makespan(bundle, enriched),
        _remote_first(bundle, enriched),
    ]
