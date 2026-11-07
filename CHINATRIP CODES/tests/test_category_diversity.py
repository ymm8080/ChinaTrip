"""品类多样性闸（2026-11-03 拍板「尽量不要重复同一类型」+「为什么安排
那么多博物馆」）。

西安实录（session 5cbf9073 等 4 会话）形态：museum 品类 3-4 家扎堆 +
大雁塔/小雁塔双卡。两路收口：
①兄弟对复合行名缺口——池行「大雁塔大唐芙蓉园景区」剥景区尾巴只掉
  尾巴，「大雁塔+大唐芙蓉园」配套词在中间剥不掉，核心词「雁塔大唐
  芙蓉园」≠「雁塔」，28533fc 的 _sibling_dup 相等判定漏判；短核心词
  是长核心词前缀（≥2 字）视同兄弟。
②选点/回填同类封顶——非 attraction 观光品类同城全程 max(2, span//3)
  家（attraction 是粗粒度垃圾桶类不设限；偏好命中豁免＝2026-10-31
  拍板「偏好可以是同一类型多个景点」；回填不豁免防池外返渗）。
另：_edit_system_prompt 透传 session.preferences（用户自由对话约束
12 条窗口滚出即蒸发事故）。
"""

from __future__ import annotations

from app.services.agent.plan import (
    PlanningAgent,
    PlanSession,
    _same_category_full,
    _sibling_dup,
)


def _cand(name, *, cat="attraction", tags=None, loc=(108.94, 34.26), suggested=90):
    c: dict = {
        "name": name,
        "city": "西安",
        "category": cat,
        "suggested_duration_min": suggested,
        "location": {"lon": loc[0], "lat": loc[1]},
    }
    if tags is not None:
        c["tags"] = tags
    return c


# --- 兄弟对复合行名 ---------------------------------------------------------


def test_sibling_dup_compound_pool_name():
    """池行复合挂牌名剥中间配套词不动，前缀核心词补位受理。"""
    assert _sibling_dup("大雁塔大唐芙蓉园景区", "小雁塔") is True
    assert _sibling_dup("大雁塔大唐芙蓉园", "小雁塔") is True
    # 既有防线回归：裸名对/景区尾巴/别名行照旧
    assert _sibling_dup("大雁塔", "小雁塔") is True
    assert _sibling_dup("大雁塔景区", "小雁塔") is True
    # 配套园区本体/无关大字号点不是兄弟
    assert _sibling_dup("大唐芙蓉园", "小雁塔") is False
    assert _sibling_dup("大明宫国家考古遗址公园", "小雁塔") is False


# --- 选点层同类封顶 ---------------------------------------------------------


def test_selection_caps_same_category():
    """2026-11-07 拍板收紧：博物馆类每行程 1 个（跨城共享），其余裁掉
    并披露；非桶品类（historic 等）仍走旧闸 max(2, span//3)。"""
    cands = [
        _cand("青铜博物馆", cat="museum", tags=["5a"]),
        _cand("织锦博物馆", cat="museum", tags=["5a"]),
        _cand("皮影博物馆", cat="museum"),
        _cand("陶艺博物馆", cat="museum"),
        _cand("钟楼", cat="attraction"),
        _cand("城隍庙", cat="attraction"),
        _cand("老街", cat="attraction"),
        _cand("环城公园", cat="attraction"),
        _cand("书院门", cat="historic"),
        _cand("北院门", cat="historic"),
        _cand("德福巷", cat="historic"),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 5, {"西安": (1, 5)}, notes=notes
    )
    museums = [it["name"] for it in items if it["category"] == "museum"]
    assert museums == ["青铜博物馆"]  # 行程桶 1 上限（原 2 家口径作废）
    assert any("行程内博物馆" in n for n in notes)
    historic = [it["name"] for it in items if it["category"] == "historic"]
    assert len(historic) == 2  # 非桶品类仍按 max(2, span//3)=2 封顶


def test_selection_cap_pref_exempt():
    """偏好命中豁免（2026-10-31 拍板：偏好可以是同一类型多个景点）。"""
    cands = [
        _cand("青铜博物馆", cat="museum", tags=["5a"]),
        _cand("织锦博物馆", cat="museum", tags=["5a"]),
        _cand("皮影博物馆", cat="museum"),
        _cand("陶艺博物馆", cat="museum"),
        _cand("钟楼", cat="attraction"),
    ]
    items = PlanningAgent._deterministic_selection(
        cands, 5, {"西安": (1, 5)}, preferences="博物馆人文"
    )
    museums = [it["name"] for it in items if it["category"] == "museum"]
    assert len(museums) == 4


def test_selection_attraction_not_capped():
    """attraction 是粗粒度垃圾桶类（回民街/城墙/兵马俑同档）不设限。"""
    cands = [
        _cand(f"地标{w}", cat="attraction", tags=["5a"])
        for w in ("甲", "乙", "丙", "丁", "戊")
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"西安": (1, 1)})
    assert len(items) == 4  # 4 个/日闸照收，品类闸不裁


# --- 回填层同口径闸 ---------------------------------------------------------


def test_same_category_full_unit():
    picked = [{"category": "museum"}, {"category": "museum"}]
    assert _same_category_full({"category": "museum"}, picked, 5) is True
    assert _same_category_full({"category": "attraction"}, picked, 5) is False
    # 长行程放宽：span 9 → cap 3，2 家未满
    assert _same_category_full({"category": "museum"}, picked, 9) is False


def test_rebalance_backfill_respects_category_cap():
    """空天回填不选第 3 家博物馆——tier 更高的博物馆让位同池 attraction。"""
    picked = [
        {
            "name": "青铜博物馆",
            "city": "西安",
            "category": "museum",
            "day": 1,
            "duration_minutes": 120,
            "location": {"lon": 108.94, "lat": 34.26},
        },
        {
            "name": "织锦博物馆",
            "city": "西安",
            "category": "museum",
            "day": 1,
            "duration_minutes": 120,
            "location": {"lon": 108.94, "lat": 34.25},
        },
        {
            "name": "钟楼",
            "city": "西安",
            "category": "attraction",
            "day": 1,
            "duration_minutes": 90,
            "location": {"lon": 108.94, "lat": 34.27},
        },
    ]
    candidates = [
        {
            "name": "皮影博物馆",
            "city": "西安",
            "category": "museum",
            "suggested_duration_min": 90,
            "tags": ["5a"],
            "location": {"lon": 108.95, "lat": 34.24},
        },
        {
            "name": "城隍庙",
            "city": "西安",
            "category": "attraction",
            "suggested_duration_min": 90,
            "location": {"lon": 108.95, "lat": 34.28},
        },
    ]
    out, _notes = PlanningAgent._rebalance_days(picked, candidates, 2, {"西安": (1, 2)})
    names = [s["name"] for s in out]
    assert "城隍庙" in names
    assert "皮影博物馆" not in names


# --- 编辑 prompt 偏好透传 ---------------------------------------------------


def test_edit_system_prompt_carries_preferences():
    session = PlanSession(
        session_id="s", device_id="dev-1", preferences="尽量不要重复同一类型"
    )
    prompt = PlanningAgent._edit_system_prompt(session)
    assert "用户偏好" in prompt
    assert "尽量不要重复同一类型" in prompt


def test_edit_system_prompt_no_preferences_no_line():
    session = PlanSession(session_id="s", device_id="dev-1", preferences="")
    prompt = PlanningAgent._edit_system_prompt(session)
    assert "用户偏好" not in prompt


# --- 偏好优先于默认封顶（2026-11-03 拍板「喜欢某个类型则可以有很多」）---


def test_selection_type_ask_collects_premium():
    """封顶裁掉的世界遗产/5A 同类进待问名单；4A/普通档裁掉只披露不待问
    （2026-11-03 拍板「4a is not preferred sites」）。"""
    cands = [
        _cand("青铜博物馆", cat="museum", tags=["5a"]),
        _cand("织锦博物馆", cat="museum", tags=["5a"]),
        _cand("皮影博物馆", cat="museum", tags=["5a"]),
        _cand("陶艺博物馆", cat="museum", tags=["4a"]),
        _cand("面人博物馆", cat="museum"),
        _cand("钟楼", cat="attraction"),
        _cand("城隍庙", cat="attraction"),
        _cand("老街", cat="attraction"),
        _cand("环城公园", cat="attraction"),
    ]
    asks: list[dict] = []
    items = PlanningAgent._deterministic_selection(
        cands, 5, {"西安": (1, 5)}, type_asks=asks
    )
    museums = [it["name"] for it in items if it["category"] == "museum"]
    assert museums == ["青铜博物馆"]  # 行程桶 1 上限：仅榜首入池
    # 织锦/皮影（5a）被行程桶裁掉 → 待问；陶艺（4a）/面面（无标签）只裁不问
    assert [(a["name"], a["tags"]) for a in asks] == [
        ("织锦博物馆", ["5a"]),
        ("皮影博物馆", ["5a"]),
    ]


def test_selection_type_ask_empty_when_pref_hits():
    """偏好命中时封顶豁免、无待问（偏好优先于默认封顶）。"""
    cands = [
        _cand("青铜博物馆", cat="museum", tags=["5a"]),
        _cand("织锦博物馆", cat="museum", tags=["5a"]),
        _cand("皮影博物馆", cat="museum", tags=["5a"]),
        _cand("陶艺博物馆", cat="museum"),
        _cand("钟楼", cat="attraction"),
    ]
    asks: list[dict] = []
    items = PlanningAgent._deterministic_selection(
        cands, 5, {"西安": (1, 5)}, preferences="博物馆人文", type_asks=asks
    )
    museums = [it["name"] for it in items if it["category"] == "museum"]
    assert len(museums) == 4
    assert asks == []


def test_backfill_pref_exempt():
    """偏好命中时回填不受品类封顶拦（「喜欢某个类型则可以有很多」）。"""
    picked = [
        {
            "name": "青铜博物馆",
            "city": "西安",
            "category": "museum",
            "day": 1,
            "duration_minutes": 120,
            "location": {"lon": 108.94, "lat": 34.26},
        },
        {
            "name": "织锦博物馆",
            "city": "西安",
            "category": "museum",
            "day": 1,
            "duration_minutes": 120,
            "location": {"lon": 108.94, "lat": 34.25},
        },
        {
            "name": "钟楼",
            "city": "西安",
            "category": "attraction",
            "day": 1,
            "duration_minutes": 90,
            "location": {"lon": 108.94, "lat": 34.27},
        },
    ]
    candidates = [
        {
            "name": "皮影博物馆",
            "city": "西安",
            "category": "museum",
            "suggested_duration_min": 90,
            "tags": ["5a"],
            "location": {"lon": 108.95, "lat": 34.24},
        },
        {
            "name": "城隍庙",
            "city": "西安",
            "category": "attraction",
            "suggested_duration_min": 90,
            "location": {"lon": 108.95, "lat": 34.28},
        },
    ]
    out, _notes = PlanningAgent._rebalance_days(
        picked, candidates, 2, {"西安": (1, 2)}, preferences="博物馆人文"
    )
    names = [s["name"] for s in out]
    assert "皮影博物馆" in names


def test_type_ask_hit():
    """同档同类让位问答：偏好词命中让位行才触发，无关回复/无待问不触发。"""
    session = PlanSession(
        session_id="s",
        device_id="dev-1",
        pending_type_ask=[
            {
                "city": "西安",
                "name": "皮影博物馆",
                "category": "museum",
                "tags": ["5a"],
            }
        ],
    )
    assert PlanningAgent._type_ask_hit(session, "喜欢博物馆，多排几家") is True
    assert PlanningAgent._type_ask_hit(session, "帮我换个酒店位置") is False
    empty = PlanSession(session_id="s2", device_id="dev-1")
    assert PlanningAgent._type_ask_hit(empty, "喜欢博物馆") is False


# --- 2026-11-07 三拍板：体验型 ≥2 / 博物馆·风景区·CityWalk 每行程 1 个 -------


def _bucket_cand(name, city, cat, *, rating=4.5, source=None, loc=(108.94, 34.26)):
    c = _cand(name, cat=cat, loc=loc)
    c["city"] = city
    c["rating"] = rating
    if source:
        c["source"] = source
    return c


def test_itinerary_cap_museum_one_per_itinerary():
    """博物馆类（museum/gallery/memorial/art）每行程 1 个、跨城共享：
    成渝线成都先占，重庆的博物馆不再入池（2026-11-07 拍板）。"""
    cands = [
        _bucket_cand("博物馆A", "成都", "museum", rating=4.5),
        _bucket_cand("博物馆B", "成都", "museum", rating=4.4),
        _bucket_cand("市点1", "成都", "attraction", rating=4.6),
        _bucket_cand("市点2", "成都", "attraction", rating=4.6),
        _bucket_cand("博物馆C", "重庆", "museum", rating=4.5),
        _bucket_cand("渝点1", "重庆", "attraction", rating=4.6),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 4, {"成都": (1, 2), "重庆": (3, 4)}, notes=notes
    )
    names = {it["name"] for it in items}
    assert "博物馆A" in names
    assert "博物馆B" not in names  # 成都池内第 2 家被行程桶裁
    assert "博物馆C" not in names  # 重庆再进博物馆：行程账本已满
    assert {"市点1", "市点2", "渝点1"} <= names
    assert any("行程内博物馆" in n for n in notes)


def test_itinerary_cap_scenic_source_counts_and_citywalk():
    """风景区桶 = nature 品类 + scenic 源行（品类不对也计数）；
    CITYWALK 每行程 1 个。"""
    cands = [
        _bucket_cand("骊山", "西安", "nature", rating=4.5),
        _bucket_cand("华山", "西安", "attraction", rating=4.5, source="scenic"),
        _bucket_cand("永兴坊", "西安", "citywalk", rating=4.5),
        _bucket_cand("回民街", "西安", "attraction", rating=4.6),
        _bucket_cand("城墙", "西安", "attraction", rating=4.6),
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"西安": (1, 1)})
    names = {it["name"] for it in items}
    assert "华山" in names  # scenic 源行梯位高（tier9）先占风景区桶
    assert "骊山" not in names  # nature 第 2 个：桶满被裁
    assert "永兴坊" in names  # citywalk 唯一一个
    assert {"回民街", "城墙"} <= names  # attraction 不设限


def test_experience_types_rank_right_after_premium():
    """体验型中国特色活动（tea_experience 等）梯子紧跟王牌：1 天 4 席
    满池时 4.0 分茶馆压过 4.6 分图商点入选（2026-11-07 拍板「多放」）。"""
    cands = [
        _bucket_cand(f"图商点{i}", "成都", "attraction", rating=4.6) for i in range(3)
    ]
    cands += [
        _bucket_cand("茶馆甲", "成都", "tea_experience", rating=4.0),
        _bucket_cand("茶馆乙", "成都", "tea_experience", rating=4.0),
    ]
    items = PlanningAgent._deterministic_selection(cands, 1, {"成都": (1, 1)})
    names = {it["name"] for it in items}
    assert {"茶馆甲", "茶馆乙"} <= names  # 体验型 ≥2 保底（梯子 boost）
    assert len(names) == 4
    assert sum(1 for n in names if n.startswith("图商点")) == 2
