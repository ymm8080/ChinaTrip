"""Backfill trip_items.address / opening_hours from the POI library.

2026-11-23（用户报「行程中心站点没地址」）：心愿/排期行此前建行时不带
address/opening_hours（materialize/sync 只落城市与排期字段），看板 📍 行
大面积空白。代码侧已补（plan._wish_row_plan_fields / materialize_wish_rows
落排期点地址）；本脚本对**存量行**按 pois 底库回填（city 变体 → name_zh
精确 → 剥括号 contains 模糊，active 闸与 /api/pois/detail 同口径），列与
payload jsonb 同步更新（payload 是看板读的权威）。

用法（venv python，项目根目录）：
    .venv/Scripts/python.exe ops/backfill_trip_item_addr.py            # 执行
    .venv/Scripts/python.exe ops/backfill_trip_item_addr.py --dry-run  # 只报不动
"""

from __future__ import annotations

import json
import re
import sys

from sqlalchemy import text

sys.path.insert(0, ".")

from app.config import get_settings  # noqa: E402


def city_variants(city: str | None) -> list[str]:
    c = (city or "").strip()
    if not c:
        return []
    bare = c[:-1] if c.endswith("市") else c
    return sorted({bare, bare + "市"})


def norm_name(name: str) -> str:
    """剥括号注记与空白（与 /api/pois/detail _norm_name 同口径）。"""
    return re.sub(r"\s+", "", re.sub(r"[（(][^（）()]*[)）]", "", name))


# 2026-11-23 补：短名（西湖/朱家角）没有括号，原 contains 兜底的
# `norm != wanted` 条件恒假 → 直接未命中。底库里真景点叫「杭州西湖风景区」
# 「朱家角古镇」，需要「名称互含 + 同城 + 景点类目优先」的宽松挑选。
# 复用 backfill_locations 的 name_overlap / city_compatible 口径，避免两套。
from app.jobs.backfill_locations import (  # noqa: E402
    city_compatible,
    name_overlap,
)

# 噪声类目：短名互含会命中「西湖己度民宿」「朱家角安麓酒店」，这些不是
# 景点本身，地址不能拿来回填。真景点类目放前档。
_SIGHT_CATEGORIES = {
    "attraction", "scenic", "nature", "ancient_town", "historic",
    "museum", "theme_park", "temple", "park", "sight", "geography",
}
_NOISE_CATEGORIES = {"hotel", "food", "restaurant", "shop", "inn"}
# 同为景点类目时靠名字里的景区标志词区分：
# 「杭州西湖风景区」应胜出「西湖文化广场」（后者是商圈，非西湖本体）。
_SIGHT_HINTS = (
    "风景名胜", "风景区", "景区", "旅游区", "古镇", "古城", "古村",
    "公园", "博物", "名胜", "遗址", "寺院", "长城",
)


def pick_best_poi(
    candidates: list[dict], wanted: str, city: str | None
) -> dict | None:
    """从同城候选里挑最像目标景点的一行；纯函数，便于 CI 无 PG 测试。

    判定顺序（都满足才入池）：
      1. 名称互含（西湖 ⊂ 杭州西湖风景区；朱家角 ⊂ 朱家角古镇）；
      2. 城市相容（同城，防异地同名）；
      3. 有 address（我们要回填的就是地址）。
    排序：景点类目 > 其他；有 opening_hours > 无；名字更短（更贴近短名本体）优先。
    """
    pool = []
    for c in candidates:
        if not name_overlap(wanted, c.get("name_zh")):
            continue
        if not city_compatible(city, c.get("city")):
            continue
        if not (c.get("address") or "").strip():
            continue
        cat = (c.get("category") or "").strip().lower()
        if cat in _NOISE_CATEGORIES:
            continue  # 民宿/酒店/餐/店，即使互含也不作景点地址
        pool.append(c)
    if not pool:
        return None

    def rank(c: dict) -> tuple:
        cat = (c.get("category") or "").strip().lower()
        is_sight = 0 if cat in _SIGHT_CATEGORIES else 1
        nm = norm_name(c.get("name_zh") or "")
        has_hint = 0 if any(h in nm for h in _SIGHT_HINTS) else 1
        has_hours = 0 if (c.get("opening_hours") or "").strip() else 1
        name_len = len(nm)
        rating = c.get("rating")
        return (is_sight, has_hint, has_hours, name_len, -(rating or 0))

    return sorted(pool, key=rank)[0]


def find_poi(conn, city: str | None, name: str) -> dict | None:
    variants = city_variants(city)
    wanted = name.strip()
    if not wanted:
        return None

    def q(where: str, params: dict) -> dict | None:
        row = conn.execute(
            text(
                "SELECT id, address, opening_hours FROM pois"
                " WHERE (status IS NULL OR status = 'active')" + where +
                " ORDER BY rating DESC NULLS LAST LIMIT 1"
            ),
            params,
        ).mappings().first()
        return dict(row) if row else None

    # 1) 城市变体 + 名字精确
    if variants:
        row = q(
            " AND city = ANY(:cities) AND name_zh = :name",
            {"cities": variants, "name": wanted},
        )
        if row:
            return row
    # 2) 不限城 + 名字精确（跨城唯一时也可信）
    row = q(" AND name_zh = :name", {"name": wanted})
    if row:
        return row
    # 3) 剥括号模糊 contains（城市优先）
    norm = norm_name(wanted)
    if norm and norm != wanted and variants:
        row = q(
            " AND city = ANY(:cities) AND name_zh LIKE :pat",
            {"cities": variants, "pat": f"%{norm}%"},
        )
        if row:
            return row
    if norm and norm != wanted:
        row = q(" AND name_zh LIKE :pat", {"pat": f"%{norm}%"})
        if row:
            return row
    # 4) 宽松：短名（无括号）互含匹配。拉同城候选交给纯函数挑，景点类目
    #    优先、排除民宿/酒店噪声。仅当 1~3 都未命中时走到这里。
    pat = f"%{norm}%"
    if variants:
        rows = conn.execute(
            text(
                "SELECT id, name_zh, city, category, rating, address, opening_hours"
                " FROM pois"
                " WHERE (status IS NULL OR status = 'active')"
                " AND city = ANY(:cities) AND name_zh LIKE :pat"
                " ORDER BY rating DESC NULLS LAST LIMIT 25"
            ),
            {"cities": variants, "pat": pat},
        ).mappings().all()
        best = pick_best_poi([dict(x) for x in rows], wanted, city)
        if best:
            return best
    return None


def main() -> None:
    dry = "--dry-run" in sys.argv
    url = get_settings().database_url
    from sqlalchemy import create_engine

    engine = create_engine(url)
    filled_addr = filled_hours = miss = 0
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, name, city, address, opening_hours, payload"
                " FROM trip_items"
                " WHERE deletion_flag = false"
                " AND ((address IS NULL OR address = '')"
                "      OR (opening_hours IS NULL OR opening_hours = ''))"
                " ORDER BY created_at DESC NULLS LAST"
            )
        ).mappings().all()
        print(f"候选行（缺地址或缺开放时间）: {len(rows)}")
        for r in rows:
            name, city = r["name"], r["city"]
            poi = find_poi(conn, city, name)
            if poi is None:
                miss += 1
                print(f"  ✗ 未命中: {city} · {name}")
                continue
            updates: dict[str, str] = {}
            if (r["address"] or "").strip() == "" and poi.get("address"):
                updates["address"] = poi["address"]
            if (r["opening_hours"] or "").strip() == "" and poi.get("opening_hours"):
                updates["opening_hours"] = poi["opening_hours"]
            if not updates:
                continue
            payload = r["payload"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            for k, v in updates.items():
                payload[k] = v
            if dry:
                print(f"  ⏳ [dry] {city} · {name} ← {updates}")
                continue
            conn.execute(
                text(
                    "UPDATE trip_items SET address = COALESCE(:addr, address),"
                    " opening_hours = COALESCE(:hours, opening_hours),"
                    " payload = payload || CAST(:patch AS jsonb),"
                    " updated_at = NOW()"
                    " WHERE id = :id"
                ),
                {
                    "addr": updates.get("address"),
                    "hours": updates.get("opening_hours"),
                    "patch": json.dumps(updates, ensure_ascii=False),
                    "id": r["id"],
                },
            )
            if "address" in updates:
                filled_addr += 1
            if "opening_hours" in updates:
                filled_hours += 1
            print(f"  ✓ {city} · {name} ← {updates}")
    mode = "[dry-run] " if dry else ""
    print(
        f"{mode}完成：回填地址 {filled_addr} 行，回填开放时间 {filled_hours} 行，"
        f"底库未命中 {miss} 行。"
    )


if __name__ == "__main__":
    main()
