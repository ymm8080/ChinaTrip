"""计划级查全率（§8.2.6）+ 天气感知建议（§8.1.4）纯函数。

查全率：候选池里带 5A/UNESCO 标签的顶级景点没被选进行程 → 假设区
告警（「北京 3 天没排故宫」级事故）。口径 v0 = 候选池代理（本次
top_pois_in_city 已取的标签行），零额外查询。
天气：预报含雨 × 当天露天点 → 「对调室内」建议（只提示不全自动，
gap #5 既定口径）。
"""

from __future__ import annotations

from typing import Iterable

_PREMIUM_TAGS = {"5a", "unesco"}
_RAIN_WORDS = ("雨", "阵雨", "雷阵雨", "小雨", "中雨", "大雨", "暴雨")


def premium_coverage_gaps(
    picked_names: Iterable[str],
    candidates: list[dict],
    *,
    same_site=None,
    max_missing: int = 3,
) -> list[dict]:
    """候选池顶级标签点未被选 → [{name, tags}]（cap max_missing）。

    same_site 注入 plan._same_site（避免循环导入）；缺省用集合包含
    粗判（名字变体兜底交给调用方口径）。
    """
    picked = [n for n in picked_names if n]
    missing: list[dict] = []
    for cand in candidates:
        tags = {str(t).lower() for t in (cand.get("tags") or [])}
        if not tags & _PREMIUM_TAGS:
            continue
        name = cand.get("name") or ""
        if not name:
            continue
        if same_site is not None:
            hit = any(same_site(name, p) for p in picked)
        else:
            hit = name in picked
        if not hit:
            missing.append({"name": name, "tags": sorted(tags & _PREMIUM_TAGS)})
        if len(missing) >= max_missing:
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
        f"预报有雨：{'、'.join(outdoor[:3])} 为露天点位{swap_hint}——"
        "回复「雨天调整」可帮你重排"
    )
