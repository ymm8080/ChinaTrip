"""C-17 分城天数（R8-S2，2026-11-18 拍板「全量切引擎」口径 A）。

H5 逐城点定的停留天数（city_days）= legacy `_city_day_ranges` 的模型镜像：
真实目的地按请求城市序切**连续日窗**，末位真实目的地吃满到 days
（闭合行程返程日白天归它——2026-10-31 返程日上午空排事故口径）；
出发城 / 闭合尾城（返程标记）不占活动窗（legacy 同款：不收候选）。
块边界全常数（预算用户给定）——连续性 / 顺序 / 天数等式由窗口构造
直接隐含，无需城市主导日布尔。缺省（city_days 为空）零约束零漂移
（g10 等多城语料的自由分配行为不变）。

2026-11-22 补（与 legacy 797f350 同拍板对齐）：
- 闭合尾城 city_days ≥2 = 真实停留：尾城吃掉最后 k_tail 天活动窗
  （回城日=days-k_tail+1），真实目的地在 1..days-k_tail 内切窗；
  k=1 仍是纯返程标记（旧口径不变）。
- origin_days ≥1 = 出发城真实首站：目的地窗按「虚拟总天数 days-k」
  切（闭合尾城/末位吃满等口径原样生效）再整体右移 k 天，出发城占
  (1, k) 活动窗（镜像 legacy shift 分支；闭合行程出发城=尾城同名键
  只留起始段，尾段候选不收——legacy 同口径，尾段由回城日端点语义
  承接）。
"""

from __future__ import annotations


def _norm(city) -> str:
    return (str(city or "")).strip().removesuffix("市")


def origin_shift(cities, days: int, origin_days) -> int:
    """出发城真实首站的天数钳位（legacy 同款）：多城行程 k=min(origin_days,
    days-1)，单城恒 0（单城无「出发城」语义）。"""
    city_list = [c for c in (cities or ()) if c]
    if len(city_list) <= 1:
        return 0
    return min(max(0, int(origin_days or 0)), max(0, int(days or 1) - 1))


def closed_return_day(cities, days: int, city_days) -> int | None:
    """闭合行程合成返程腿的落日（2026-11-22）。

    首尾同名（闭合）且闭合尾城**不是** ≥2 天真实停留（纯返程标记）时，
    装配层在末日补傍晚返程腿（17:00 口径）→ 返回末日（模型侧配套：
    C-05 返程顶盖 + C-09 晚餐槽抑制都在该日）。尾城 ≥2 天真实停留时
    返程腿由日标签翻转入腿（尾窗首日早上），返回 None——末日是完整
    游玩日，不加顶盖/不抑晚餐。非闭合行程 None（11-13 拍板：不回家）。"""
    city_list = [c for c in (cities or ()) if c]
    if len(city_list) < 2:
        return None
    if _norm(city_list[0]) != _norm(city_list[-1]):
        return None
    total = max(1, int(days or 1))
    if city_days:
        budget = {_norm(k): int(v) for k, v in dict(city_days or {}).items()}
        d = budget.get(_norm(city_list[-1]))
        if isinstance(d, int) and d >= 2:
            tail = min(d, max(0, total - max(1, len(city_list[1:]) - 1)))
            if tail >= 2:
                return None  # 尾城真实停留：末日是完整游玩日
    return total


def city_day_windows(
    cities, days: int, city_days, origin_days: int = 0
) -> dict[str, tuple[int, int]]:
    """请求城市序 + 分城预算 → 逐城日窗（legacy `_city_day_ranges` 同口径）。

    cities 形如 [出发城, 目的地...]（多城，与 H5/legacy 契约一致）；
    单城即目的地。闭合行程（末城==出发城）尾城天数 <2 是返程标记，不占
    活动窗；≥2 是真实停留，占最后 k_tail 天窗（2026-11-22 797f350 口径）。
    预算缺失按 1 天；溢出被钳到剩余天数；不足由末位真实目的地吃满到
    days 吸收。origin_days ≥1 时先按 days-k 虚拟天数切窗再整体右移，
    出发城占 (1, k)（闭合行程同名键覆盖尾段，legacy shift 分支同款）。
    返回 {规范城市名: (start_day, end_day)}。
    """
    budget = {_norm(k): int(v) for k, v in dict(city_days or {}).items()}
    city_list = [c for c in (cities or ()) if c]
    shift = origin_shift(city_list, days, origin_days)
    if shift >= 1:
        inner = city_day_windows(city_list, int(days or 1) - shift, city_days)
        windows = {_norm(k): (s + shift, e + shift) for k, (s, e) in inner.items()}
        windows[_norm(city_list[0])] = (1, shift)
        return windows
    dests = city_list[1:] if len(city_list) > 1 else city_list
    closed = (
        len(dests) > 1 and _norm(dests[-1]) == _norm(city_list[0])
        if city_list
        else False
    )
    tail_city = _norm(dests[-1]) if dests else None
    tail_stay = 0
    if closed and city_days:
        d = budget.get(tail_city)
        if isinstance(d, int) and d >= 2:
            # 真实目的地每家至少留 1 天，尾城停留上限=days-真实目的地数
            tail_stay = min(d, max(0, (int(days or 1)) - max(1, len(dests) - 1)))
            if tail_stay < 2:
                tail_stay = 0
    total = max(1, int(days or 1))
    cap = total - tail_stay if tail_stay else total
    real_dests = dests[:-1] if closed else dests
    windows: dict[str, tuple[int, int]] = {}
    start = 1
    for i, city in enumerate(real_dests):
        stay = budget.get(_norm(city), 1)
        if not isinstance(stay, int) or stay < 1:
            stay = 1
        if i == len(real_dests) - 1:
            end = cap  # 末位真实目的地吃满到 cap（尾城有真实停留时提前）
        else:
            end = min(start + stay - 1, cap)
        win = (start, max(start, end))
        windows[_norm(city)] = win
        start = win[1] + 1
    if closed and tail_city is not None and tail_stay:
        windows[tail_city] = (cap + 1, total)
    return windows


def add_c17_city_days(bundle, enriched) -> None:
    """把每城候选锁进它的日窗；窗外（含出发城/闭合尾城/无城市骨架）灭活。

    无城市信息的骨架必去候选会被灭活成 unplaced（F-26 证书诚实披露）；
    出发城候选按 origin_days 语义：k≥1 时占 (1, k) 活动窗（真实首站），
    k=0 时不收候选（legacy「出发城不收候选」口径）。闭合尾城 ≥2 天真实
    停留占尾窗（797f350 同口径）。
    """
    request = enriched.snapshot.request
    origin_days = getattr(request, "origin_days", 0) or 0
    # g10 零漂移守卫：city_days 与 origin_days 都缺省 = 零约束（自由
    # 分配，2026-11-18 口径 A 原样）；有任一才锁窗。
    if not request.city_days and origin_days < 1:
        return
    windows = city_day_windows(
        request.cities,
        request.days,
        dict(request.city_days or {}),
        origin_days=origin_days,
    )
    if not windows:
        return
    for cand in enriched.snapshot.candidates:
        win = windows.get(_norm(getattr(cand, "city", None)))
        for day in bundle.days:
            if win is None or not (win[0] <= day <= win[1]):
                bundle.model.Add(bundle.presence[(cand.cid, day)] == 0)
