"""C-17 分城天数（R8-S2，2026-11-18 拍板「全量切引擎」口径 A）。

H5 逐城点定的停留天数（city_days）= legacy `_split_days` 的模型镜像：
真实目的地按请求城市序切**连续日窗**，末位真实目的地吃满到 days
（闭合行程返程日白天归它——2026-10-31 返程日上午空排事故口径）；
出发城 / 闭合尾城（返程标记）不占活动窗（legacy 同款：不收候选）。
块边界全常数（预算用户给定）——连续性 / 顺序 / 天数等式由窗口构造
直接隐含，无需城市主导日布尔。缺省（city_days 为空）零约束零漂移
（g10 等多城语料的自由分配行为不变）。
"""

from __future__ import annotations


def _norm(city) -> str:
    return (str(city or "")).strip().removesuffix("市")


def city_day_windows(cities, days: int, city_days) -> dict[str, tuple[int, int]]:
    """请求城市序 + 分城预算 → 逐城日窗（legacy `_split_days` 同口径）。

    cities 形如 [出发城, 目的地...]（多城，与 H5/legacy 契约一致）；
    单城即目的地。闭合行程（末城==出发城）尾城是返程标记，不占活动
    窗。预算缺失按 1 天；溢出被钳到剩余天数；不足由末位真实目的地
    吃满到 days 吸收。返回 {规范城市名: (start_day, end_day)}。
    """
    budget = {_norm(k): int(v) for k, v in dict(city_days or {}).items()}
    city_list = [c for c in (cities or ()) if c]
    dests = city_list[1:] if len(city_list) > 1 else city_list
    if len(dests) > 1 and _norm(dests[-1]) == _norm(city_list[0]):
        dests = dests[:-1]
    total = max(1, int(days or 1))
    windows: dict[str, tuple[int, int]] = {}
    start = 1
    for i, city in enumerate(dests):
        stay = budget.get(_norm(city), 1)
        if not isinstance(stay, int) or stay < 1:
            stay = 1
        if i == len(dests) - 1:
            end = total  # 末位真实目的地吃满到 days
        else:
            end = min(start + stay - 1, total)
        win = (start, max(start, end))
        windows[_norm(city)] = win
        start = win[1] + 1
    return windows


def add_c17_city_days(bundle, enriched) -> None:
    """把每城候选锁进它的日窗；窗外（含出发城/闭合尾城/无城市骨架）灭活。

    无城市信息的骨架必去候选会被灭活成 unplaced（F-26 证书诚实披露）；
    出发城/尾城候选与 legacy「不收候选」口径一致。
    """
    request = enriched.snapshot.request
    if not request.city_days:
        return
    windows = city_day_windows(request.cities, request.days, dict(request.city_days))
    for cand in enriched.snapshot.candidates:
        win = windows.get(_norm(getattr(cand, "city", None)))
        for day in bundle.days:
            if win is None or not (win[0] <= day <= win[1]):
                bundle.model.Add(bundle.presence[(cand.cid, day)] == 0)
