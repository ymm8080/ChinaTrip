"""演出场次扩列（2026-10-31）：_show_night_only 按场次标记分桶的回归。

04 源 50 行核完场次后，opening_hours 承载「仅夜场/傍晚场 vs 多场/全天/日场」
标记；仅夜场走晚档收尾桶（原行为），含下午场/全天滚动的演出落回常规景点池
任意时段排。无场次数据兜底 True（沿用旧行为）。
"""

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
