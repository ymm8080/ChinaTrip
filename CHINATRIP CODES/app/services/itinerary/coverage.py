"""计划级查全率（§8.2.6）+ 天气感知建议（§8.1.4）纯函数。

查全率：候选池里带 5A/UNESCO 标签的顶级景点没被选进行程 → 假设区
告警（「北京 3 天没排故宫」级事故）。口径 v0 = 候选池代理（本次
top_pois_in_city 已取的标签行），零额外查询。
天气：预报含雨 × 当天露天点 → 「对调室内」建议（只提示不全自动，
gap #5 既定口径）。
"""

from __future__ import annotations

from typing import Iterable

# 世界遗产族标签统一按 unesco 前缀识别（全量世遗 unesco/丝路点段
# unesco_silk_road/明清陵寝 unesco_ming_tombs 等）：点段代表行来源
# 多样，只认字面量则没排也不披露（2026-11-02 大雁塔事故）。
_PREMIUM_TAGS = {"5a", "unesco"}
_PREMIUM_PREFIX = "unesco"
_RAIN_WORDS = ("雨", "阵雨", "雷阵雨", "小雨", "中雨", "大雨", "暴雨")


def premium_coverage_gaps(
    picked_names: Iterable[str],
    candidates: list[dict],
    *,
    same_site=None,
    max_missing: int | None = None,
) -> list[dict]:
    """候选池顶级标签点未被选 → [{name, tags}]。

    默认全量（2026-10-31 用户拍板：白名单只显示前 3 条被质疑，
    截断放开——披露不设坑位上限）；max_missing 仅供测试收窄。

    same_site 注入 plan._same_site（避免循环导入）；缺省用集合包含
    粗判（名字变体兜底交给调用方口径）。
    """
    picked = [n for n in picked_names if n]
    missing: list[dict] = []
    for cand in candidates:
        tags = {str(t).lower() for t in (cand.get("tags") or [])}
        premium = sorted(
            t for t in tags if t in _PREMIUM_TAGS or t.startswith(_PREMIUM_PREFIX)
        )
        if not premium:
            continue
        name = cand.get("name") or ""
        if not name:
            continue
        if same_site is not None:
            hit = any(same_site(name, p) for p in picked)
        else:
            hit = name in picked
        if not hit:
            missing.append({"name": name, "tags": premium})
        if max_missing is not None and len(missing) >= max_missing:
            break
    return missing


def rain_swap_advice(
    forecast_text: str | None,
    day_visits: list[dict],
) -> str | None:
    """预报含雨且当天存在露天（rain_ok=no）点 → 对调建议句；否则 None。

    day_visits = [{name, rain_ok}]（来自候选/行程条目）。
    """
    text = forecast_text or ""
    if not any(w in text for w in _RAIN_WORDS):
        return None
    outdoor = [v["name"] for v in day_visits if v.get("rain_ok") == "no"]
    if not outdoor:
        return None
    indoor_like = [v["name"] for v in day_visits if v.get("rain_ok") == "yes"]
    swap_hint = f"（可与 {'、'.join(indoor_like[:2])} 对调）" if indoor_like else ""
    return (
        f"预报有雨：{'、'.join(outdoor[:3])} 为露天点位{swap_hint}，"
        "雨天行程已自动优先室内，建议备伞"
    )
