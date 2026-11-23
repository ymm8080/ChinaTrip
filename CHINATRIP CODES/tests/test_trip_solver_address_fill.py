"""引擎卡读库补地址（2026-11-23 用户实报「表里有地址，卡片不显示」）。

根因回归锁：trip-solver 装配出的 VisitItem 不带 address（CandidateItem 无
地址字段），生成首屏的观光卡全无「📍 地址」行；legacy 的 `_hours_db_pass`
只在 GET/enrich 上跑，所以「刚规划完那一屏」永远没地址。

本测试锁 `_fill_detail_from_store` 的口径：
- 只填空，不覆盖已有值；
- 腿/中转卡（有 from_city/to_city）不查库；
- 库行缺失时静默跳过，不抛错；
- poi_id 未命中按 (city, name) 兜底。
"""

from __future__ import annotations

from types import SimpleNamespace

from app.services.trip_solver.live import _fill_detail_from_store


class FakeStore:
    """只实现补链用到的两个读口。"""

    def __init__(self, by_id=None, by_name=None):
        self._by_id = by_id or {}
        self._by_name = by_name or {}
        self.get_calls = []
        self.name_calls = []

    def get(self, source_poi_id):
        self.get_calls.append(source_poi_id)
        return self._by_id.get(source_poi_id)

    def get_by_name(self, city, name):
        self.name_calls.append((city, name))
        return self._by_name.get((city, name))


def _item(**kw):
    base = dict(
        item_id="v1",
        name="天坛",
        poi_id="unesco_Q125445",
        city="北京",
        address=None,
        address_en=None,
        opening_hours=None,
        opening_hours_en=None,
        from_city=None,
        to_city=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _plan(*items):
    return SimpleNamespace(days=[SimpleNamespace(items=list(items))])


def test_fills_address_and_hours_from_store():
    item = _item()
    store = FakeStore(
        by_id={
            "unesco_Q125445": {
                "address": "北京市东城区天坛街道天坛天坛公园-祈年殿",
                "address_en": "Temple of Heaven, Dongcheng, Beijing",
                "opening_hours": "06:30-22:00",
            }
        }
    )

    filled = _fill_detail_from_store(_plan(item), store)

    assert filled == 1
    assert item.address == "北京市东城区天坛街道天坛天坛公园-祈年殿"
    assert item.address_en == "Temple of Heaven, Dongcheng, Beijing"
    assert item.opening_hours == "06:30-22:00"


def test_never_overwrites_existing_values():
    item = _item(address="模型给的地址", opening_hours="08:00-18:00")
    store = FakeStore(
        by_id={"unesco_Q125445": {"address": "库里的地址", "opening_hours": "06:30-22:00"}}
    )

    filled = _fill_detail_from_store(_plan(item), store)

    assert filled == 0
    assert item.address == "模型给的地址"
    assert item.opening_hours == "08:00-18:00"


def test_skips_legs_without_poi_lookup():
    leg = _item(name="🚕 乘车前往下一站·约20分钟", poi_id=None, from_city="北京", to_city="北京")
    store = FakeStore()

    filled = _fill_detail_from_store(_plan(leg), store)

    assert filled == 0
    assert store.get_calls == []
    assert store.name_calls == []


def test_falls_back_to_name_lookup_when_poi_id_misses():
    item = _item(poi_id=None, name="景山公园", city="北京")
    store = FakeStore(by_name={("北京", "景山公园"): {"address": "北京市西城区景山西街44号"}})

    filled = _fill_detail_from_store(_plan(item), store)

    assert filled == 1
    assert item.address == "北京市西城区景山西街44号"


def test_missing_detail_is_silent():
    item = _item(name="不存在的地方", city="北京", poi_id=None)
    store = FakeStore()

    assert _fill_detail_from_store(_plan(item), store) == 0
    assert item.address is None


def test_none_plan_or_store_is_noop():
    assert _fill_detail_from_store(None, FakeStore()) == 0
    assert _fill_detail_from_store(_plan(_item()), None) == 0


# --- 接线回归锁（2026-11-23 用户质问「你说测过其实没修好」后补） -----------
# 上面 6 项测的是 helper 语义：把 helper 从调用点删掉，它们照样全绿。
# 地址不显示的真因正是「helper 不存在 / 没接上」，所以必须单独锁接线本身。


def test_generate_path_is_wired_to_fill():
    """首生成出口必须调用补链——删掉调用即失败。"""
    import inspect

    from app.services.trip_solver import live

    src = inspect.getsource(live.generate_session_via_trip_solver)
    assert "_fill_detail_from_store(session.plan, store)" in src


def test_replan_path_is_wired_to_fill():
    """重排出口必须调用补链——删掉调用即失败。"""
    import inspect

    from app.services.trip_solver import live

    src = inspect.getsource(live.replan_session_via_trip_solver)
    assert "_fill_detail_from_store(session.plan, store)" in src
