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
    """4 家博物馆同城 5 天只入 2 家（span//3=1→cap 2），裁掉并披露。"""
    cands = [
        _cand("青铜博物馆", cat="museum", tags=["5a"]),
        _cand("织锦博物馆", cat="museum", tags=["5a"]),
        _cand("皮影博物馆", cat="museum"),
        _cand("陶艺博物馆", cat="museum"),
        _cand("钟楼", cat="attraction"),
        _cand("城隍庙", cat="attraction"),
        _cand("老街", cat="attraction"),
        _cand("环城公园", cat="attraction"),
    ]
    notes: list[str] = []
    items = PlanningAgent._deterministic_selection(
        cands, 5, {"西安": (1, 5)}, notes=notes
    )
    museums = [it["name"] for it in items if it["category"] == "museum"]
    assert museums == ["青铜博物馆", "织锦博物馆"]
    assert any("已满2家" in n for n in notes)


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
