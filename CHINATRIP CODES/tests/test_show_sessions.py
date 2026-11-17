"""演出场次扩列（2026-10-31）：_show_night_only 按场次标记分桶的回归。

04 源 50 行核完场次后，opening_hours 承载「仅夜场/傍晚场 vs 多场/全天/日场」
标记；仅夜场走晚档收尾桶（原行为），含下午场/全天滚动的演出落回常规景点池
任意时段排。无场次数据兜底 True（沿用旧行为）。
"""

from datetime import time

from app.services.agent.plan import _show_night_only
from app.services.itinerary.solver import show_session_starts


def _cand(hours: str | None) -> dict:
    return {"name": "测试演出", "source": "show", "opening_hours": hours}


def test_night_only_markers():
    assert _show_night_only(
        _cand("仅夜场（约20:10/21:35两场；演出季4-10月，冬季停演）")
    )
    assert _show_night_only(_cand("傍晚/晚间场（约17:30/19:30）"))
    assert _show_night_only(_cand("夜场为主（约20:00）"))
    assert _show_night_only(_cand("夜间街区演艺（约16:30-22:00）"))
    assert _show_night_only(_cand("场次随排期（驻场/巡演）"))


def test_multi_session_markers_not_night_only():
    assert not _show_night_only(_cand("多场（约14:00-21:00，含下午场）"))
    assert not _show_night_only(_cand("全天多剧场滚动（约9:00-21:00）"))
    assert not _show_night_only(_cand("多场（云之上日场+夜场）"))
    assert not _show_night_only(_cand("多场（梵宫内白天滚动）"))
    assert not _show_night_only(_cand("多场（白天场约11:00/13:30）"))


def test_missing_hours_defaults_to_night_only():
    # 数据缺失兜底：沿用 2026-10-29 起的晚场收尾行为
    assert _show_night_only(_cand(None))
    assert _show_night_only(_cand(""))
    assert _show_night_only({"name": "无hours键"})


def test_field_suffix_session_marks():
    # 2026-11-12 补口「声明场次的宴秀按场次落」：时刻+「场」字即场次
    # 声明——宴秀卡「午宴12:30场；晚宴18:30场」无「约」前缀，列表/单场
    # 两式皆漏 → 空表 → 落无场次餐槽任意时刻（12:00 半小时午餐），声明
    # 场次形同虚设（「19:30 开始的演出放到 9:30 场」同族病灶）。
    assert show_session_starts("午宴12:30场；晚宴18:30场（预订制）") == [
        12 * 60 + 30,
        18 * 60 + 30,
    ]
    assert show_session_starts("演出季约20:00，旺季加16:00场") == [16 * 60, 20 * 60]
    # 既有形状不回退；区间/滚动窗/「约19:30一场」（隔「一」字）不误伤
    assert show_session_starts("仅夜场（晚宴秀，约19:30一场）") == [19 * 60 + 30]
    assert show_session_starts("傍晚/晚间场（约17:30/19:30两场）") == [
        17 * 60 + 30,
        19 * 60 + 30,
    ]
    assert show_session_starts("全天滚动演艺（10:00-22:00）") == []
    assert show_session_starts("10月8日-10月31日:10:30-19:00") == []


def test_banquet_declared_sessions_open_solver_point_windows():
    # 2026-11-12「声明场次的宴秀按场次落」：solver _visit_spec 此前只给
    # _is_show 开场次点窗，宴秀卡（food 类 curated 宴）声明的午宴/晚宴场次
    # 被无视 → v0 按普通餐卡塞游标任意时刻（12:15 午餐），声明场次形同虚设
    # （「19:30 开始的演出放到 9:30 场」同族病灶）。现宴秀与演出同权。
    from app.services.itinerary.models import VisitItem
    from app.services.itinerary.solver import _visit_spec

    item = VisitItem(
        item_id="v1",
        name="某主题宴",
        poi_id="curated:某城:某主题宴",
        category="food",
        city="某城",
        day=1,
        duration_minutes=120,
        opening_hours="午宴12:30场；晚宴18:30场（预订制）",
    )
    spec = _visit_spec(item, {})
    assert spec is not None
    assert spec.windows == [
        (12 * 60 + 30, 12 * 60 + 30),
        (18 * 60 + 30, 18 * 60 + 30),
    ]
    # 无场次语素的宴秀行为不变（无点窗，走普通餐槽链）
    plain = item.model_copy(update={"opening_hours": "11:00-14:00；17:00-21:00"})
    spec_plain = _visit_spec(plain, {})
    assert spec_plain is not None and spec_plain.windows is None
    # 铁律 19 不回退：用户钉住的时刻优先于场次表（pinned 不开点窗）
    pinned = item.model_copy(
        update={"pinned": True, "start_time": time(18, 0), "end_time": time(20, 0)}
    )
    spec_pin = _visit_spec(pinned, {})
    assert spec_pin is not None and spec_pin.windows is None
    # 系统软钉（soft_pin）的宴秀：构造期钉的通用餐窗让位声明场次
    # （2026-11-12 用户拍板「一族里有一项有了制约，移动是整个组合
    # 邻排一起移动的，不是中间随便插入时间」）——钉点 18:00 不在
    # 场次段内也不判不可行，场次表驱动落位。
    soft = item.model_copy(
        update={
            "pinned": True,
            "soft_pin": True,
            "start_time": time(18, 0),
            "end_time": time(19, 0),
        }
    )
    spec_soft = _visit_spec(soft, {}, meal_flex=True)
    assert spec_soft is not None
    assert spec_soft.windows == [
        (12 * 60 + 30, 12 * 60 + 30),
        (18 * 60 + 30, 18 * 60 + 30),
    ]
