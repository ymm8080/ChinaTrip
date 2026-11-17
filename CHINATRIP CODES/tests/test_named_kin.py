"""拍板强簇：2026-11-13 用户「以后东方明珠和外滩是一族」。

黄浦江两岸直线 0.9km，却被江面隔开；城心簇按直线距离分日会把它们拆到
两天（过江折返）。名字钉族=与地理原子族同一套机制（同日连排、整族
原子位移），且不把「外滩源/外滩观光隧道/外滩万国建筑博览群」等衍生行
误并进来。
"""

from __future__ import annotations

from app.services.agent.plan import PlanningAgent, _named_kin


def _cand(name, cat, lon, lat, minutes, rating=None):
    c = {
        "name": name,
        "city": "上海",
        "category": cat,
        "suggested_duration_min": minutes,
        "location": {"lon": lon, "lat": lat},
    }
    if rating is not None:
        c["rating"] = rating
    return c


def test_named_kin_detects_bund_pearl_pair():
    assert _named_kin({"name": "东方明珠"}, {"name": "外滩"}) is True
    assert _named_kin({"name": "外滩"}, {"name": "东方明珠广播电视塔"}) is True


def test_named_kin_ignores_derivative_names():
    assert _named_kin({"name": "外滩源"}, {"name": "东方明珠"}) is False
    assert _named_kin({"name": "外滩观光隧道"}, {"name": "东方明珠"}) is False
    assert _named_kin({"name": "外滩万国建筑博览群"}, {"name": "东方明珠"}) is False
    # 观测廊是子票行，精确名不认（池层由伞名/孪生并卡承接，不进来撑族）
    deck = {"name": "东方明珠259米全透明悬空观光廊"}
    assert _named_kin(deck, {"name": "外滩"}) is False


def test_pearl_and_bund_land_on_same_day():
    """跨江近点照旧分日的话会拆开；钉族后必须同日。"""
    cands = [
        _cand("东方明珠", "viewpoint", 121.4998, 31.2397, 165, rating=4.7),
        _cand("外滩", "nature", 121.4903, 31.2398, 120, rating=4.8),
        _cand("上海科技馆", "museum", 121.5414, 31.2181, 240, rating=4.7),
        _cand("豫园", "park", 121.4922, 31.2270, 90),
        _cand("静安寺", "attraction", 121.4453, 31.2237, 90),
    ]
    items = PlanningAgent._deterministic_selection(cands, 3, {"上海": (1, 3)})
    day = {it["name"]: it["day"] for it in items}
    assert day.get("东方明珠") is not None and day.get("外滩") is not None
    assert day["东方明珠"] == day["外滩"]
