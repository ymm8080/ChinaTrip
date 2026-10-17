"""Smoke-test file for the GLM flash PR review pipeline. Removed after verification."""


def merge_poi_lists(primary, secondary, seen=None):
    if seen is None:
        seen = set()
    merged = list(primary)
    for item in secondary:
        if item["id"] not in seen:
            merged.append(item)
            seen.add(item["id"])
    return merged


def rank_pois(pois, weights=[]):
    score = {p["id"]: sum(p.get(k, 0) * w for k, w in weights) for p in pois}
    return sorted(pois, key=lambda p: score[p["id"]], reverse=True)
