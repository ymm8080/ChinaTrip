"""R20⑤（2026-11-23）：同 POI 多行 access profile 的择优/合并。

enrich 的 access_by_poi 此前盲目后写覆盖——同 POI 多行时选哪行取决于
DB 返回顺序：「有返程」的行若排在「无返程」的行之前，会被后者盖掉，
回程卡 / 回城三段 / 班次 chips 全部丢失。这里锁定确定性择优：

- 不同服务（乘车点/车程不同）：择优，有返程班次者优先，绝不跨服务拼接；
- 同一服务被拆两行（同乘车点/同车程）：合并去程/返程班次。
"""

from app.services.trip_solver.inputs.enrich import (
    _access_profile_rank,
    _better_access_profile,
)
from app.services.trip_solver.types import AccessProfile


def _prof(gateway="前门站", ride=91, departures=(), returns=(), **kw):
    return AccessProfile(
        gateway=gateway,
        to_poi="ct_北京_8",
        ride_minutes=ride,
        departures=tuple(departures),
        returns=tuple(returns),
        **kw,
    )


def test_prefers_row_with_returns_regardless_of_order():
    has_returns = _prof(departures=("08:30",), returns=("13:45",))
    only_out = _prof(gateway="德胜门", ride=60, departures=("08:00",))
    assert _better_access_profile(only_out, has_returns) is has_returns
    assert _better_access_profile(has_returns, only_out) is has_returns


def test_choice_is_order_independent():
    a = _prof(gateway="德胜门", ride=60, departures=("08:00",))
    b = _prof(gateway="前门站", ride=91, departures=("06:30",), returns=("13:45",))
    assert _better_access_profile(a, b) is b
    assert _better_access_profile(b, a) is b


def test_merges_split_same_service():
    # 同一服务拆两行（同乘车点/同车程）：去程与返程合并，不得互相覆盖。
    out = _prof(departures=("06:30", "07:30"), returns=())
    ret = _prof(departures=(), returns=("13:45", "14:45"))
    merged = _better_access_profile(out, ret)
    assert merged is not out and merged is not ret
    assert merged.departures == ("06:30", "07:30")
    assert merged.returns == ("13:45", "14:45")
    assert merged.gateway == "前门站" and merged.ride_minutes == 91


def test_does_not_merge_across_services():
    # 不同服务（乘车点/车程不同）绝不拼接——去程 A 乘车点 + 返程 B 时刻
    # 是不可执行的组合。
    front = _prof(gateway="前门站", ride=91, departures=("06:30",), returns=())
    desheng = _prof(
        gateway="德胜门", ride=60, departures=("08:00",), returns=("13:45",)
    )
    chosen = _better_access_profile(front, desheng)
    assert chosen is desheng
    assert chosen.returns == ("13:45",)
    assert chosen.departures == ("08:00",)  # 不混入前门线的 06:30


def test_rank_returns_dominates_departure_count():
    many_out = _prof(departures=("06:00", "07:00", "08:00"), returns=())
    one_each = _prof(
        gateway="德胜门", ride=60, departures=("09:00",), returns=("15:00",)
    )
    assert _access_profile_rank(one_each) > _access_profile_rank(many_out)
