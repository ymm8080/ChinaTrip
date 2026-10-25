"""商圈/坐标聚类分日（DESIGN §6.1 地理规划器·引擎半边，2026-10-25）。

「哪天去哪片」从 LLM 拍脑袋改为地理聚类给提示：确定性最远点种子
+ 就近分配（k-means 对几十个点过重且不稳定）；LLM 仍定分日，但
候选清单按片区标注 + prompt 规则要求同日尽量同片区——消灭「一天
横穿城三趟」。business_area 非空时优先作为片区标签（用户可读）。
"""

from __future__ import annotations

from math import hypot

from app.services.itinerary.models import GeoPoint


def _xy(loc) -> tuple[float, float] | None:
    try:
        if isinstance(loc, GeoPoint):
            return (loc.lon, loc.lat)
        if isinstance(loc, dict) and "lon" in loc and "lat" in loc:
            return (float(loc["lon"]), float(loc["lat"]))
        if isinstance(loc, (tuple, list)) and len(loc) == 2:
            return (float(loc[0]), float(loc[1]))
    except (TypeError, ValueError):
        return None
    return None


def cluster_days(
    candidates: list[dict],
    k: int,
    *,
    location_key: str = "location",
) -> list[int | None]:
    """把候选按坐标聚成 k 片（确定性）：返回每候选的片区号 0..k-1。

    无坐标候选 → None（不参与聚类，LLM 自行处置）；k<1 或全部无坐标
    → 全 None。最远点选种子，剩余点就近归组——顺序敏感 O(n·k)，几十
    个候选瞬时完成。
    """
    if k < 1:
        return [None] * len(candidates)
    pts: list[tuple[float, float] | None] = [
        _xy(c.get(location_key)) for c in candidates
    ]
    if not any(p is not None for p in pts):
        return [None] * len(candidates)

    # 种子：第一个有坐标点；后续每轮取「离已选种子最小距离最大」的点
    seeds: list[tuple[float, float]] = []
    first = next(p for p in pts if p is not None)
    seeds.append(first)
    while len(seeds) < k:
        best: tuple[float, float] | None = None
        best_dist = -1.0
        for p in pts:
            if p is None or p in seeds:
                continue
            dist = min(hypot(p[0] - s[0], p[1] - s[1]) for s in seeds)
            if dist > best_dist:
                best_dist, best = dist, p
        if best is None or best_dist <= 0:
            break
        seeds.append(best)

    out: list[int | None] = []
    for p in pts:
        if p is None:
            out.append(None)
            continue
        out.append(
            min(
                range(len(seeds)),
                key=lambda i: hypot(p[0] - seeds[i][0], p[1] - seeds[i][1]),
            )
        )
    return out


def area_labels(
    candidates: list[dict],
    clusters: list[int | None],
) -> dict[int, str]:
    """片区号 → 用户可读标签：取该片区最常见的 business_area，否则
    「片区N+1」。"""
    names: dict[int, dict[str, int]] = {}
    for cand, cid in zip(candidates, clusters):
        if cid is None:
            continue
        ba = (cand.get("business_area") or "").strip()
        if ba:
            names.setdefault(cid, {})[ba] = names.setdefault(cid, {}).get(ba, 0) + 1
    labels: dict[int, str] = {}
    for cid in {c for c in clusters if c is not None}:
        counter = names.get(cid) or {}
        top = max(counter, key=counter.get) if counter else None
        labels[cid] = top or f"片区{cid + 1}"
    return labels
