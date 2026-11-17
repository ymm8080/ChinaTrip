"""price_level 价位档（DESIGN user_tag_two_level_2026-11-10 §四）。

用户选择器的价位标签：人均（元/人）→ 5 档。区间语义半开——左开右闭
（50 元整归 budget），档名与 DESIGN 档位一一对应：

    budget  ≤50
    value   (50, 100]
    mid     (100, 200]
    upper   (200, 500]
    premium (500, 9999]
    越界（≤0 / >9999）返回 None（回填侧当未命中，不猜）。
"""

from __future__ import annotations

_COST_CEILING = 9999

# 档名有序表：(上界, 档名)；None 上界 = premium 兜底
_BANDS: tuple[tuple[float, str], ...] = (
    (50.0, "budget"),
    (100.0, "value"),
    (200.0, "mid"),
    (500.0, "upper"),
)


def band_for_cost(cost: object) -> str | None:
    """人均消费 → 价位档名；非法/越界 None。"""
    try:
        c = float(cost)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if c <= 0 or c > _COST_CEILING:
        return None
    for upper, name in _BANDS:
        if c <= upper:
            return name
    return "premium"
