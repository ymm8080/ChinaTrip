# -*- coding: utf-8 -*-
"""贴邻演出对普查（2026-11-07 锦里古戏台/武侯祠案影响面）：

只读扫描。夜场演出行（名称命中 poi_classify._SHOW_HINTS 且 opening_hours
不含 多场/全天/日场——引擎 _show_night_only 同口径）× 同城 1.5km 步行圈内
高优先档观光行（unesco/5a/museum1/museum2/museum3/artmuseum/street/histown）。
这些对在现行引擎里会被「演出钉末日 + 王牌预占最早天」拆成两天，
plan.py 新增 _SHOW_ADJACENT_KM 贴邻同日偏好后同日连排。

输出 ops/show_adjacent_scan_20261107.md。可重复跑（只读）。
"""

from sqlalchemy import create_engine, text

ENG = create_engine(
    "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip",
    connect_args={"connect_timeout": 3},
)
SHOW_HINTS = (
    "剧场",
    "剧院",
    "戏院",
    "戏台",
    "戏楼",
    "剧社",
    "梨园",
    "变脸",
    "川剧",
    "相声",
    "演出",
)
PREMIUM = (
    "unesco",
    "5a",
    "museum1",
    "museum2",
    "museum3",
    "artmuseum",
    "street",
    "histown",
)
RADIUS_M = 1500
OUT = r"D:/CHINATRIP/CHINATRIP CODES/ops/show_adjacent_scan_20261107.md"

name_filter = " or ".join(
    f"name_zh like '%{h}%'" for h in SHOW_HINTS
)

with ENG.connect() as c:
    sources = [
        r[0] for r in c.execute(text("select distinct source from pois")).fetchall()
    ]
    shows = c.execute(
        text(
            f"""
            select id, name_zh, source, city, category, opening_hours,
                   ST_Y(location::geometry) as lat, ST_X(location::geometry) as lng
            from pois
            where status='active' and category not in ('food','hotel')
              and location is not null and ({name_filter})
            order by city, name_zh
            """
        )
    ).fetchall()

night_only, multi = [], []
for r in shows:
    hours = r.opening_hours or ""
    if hours and any(m in hours for m in ("多场", "全天", "日场")):
        multi.append(r)
    else:
        night_only.append(r)

pairs = []
sources_csv = ", ".join(f"'{s}'" for s in PREMIUM)
with ENG.connect() as c:
    for r in night_only:
        near = c.execute(
            text(
                f"""
                select name_zh, source, category,
                       round(ST_Distance(
                           location,
                           ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                       )::numeric) as dist_m
                from pois
                where status='active' and city=:city
                  and source in ({sources_csv})
                  and category not in ('food','hotel')
                  and location is not null
                  and ST_DWithin(
                      location,
                      ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                      :radius
                  )
                order by dist_m
                """
            ),
            {
                "lng": r.lng,
                "lat": r.lat,
                "city": r.city,
                "radius": RADIUS_M,
            },
        ).fetchall()
        if near:
            pairs.append((r, near))

pairs.sort(key=lambda p: (p[0].city, p[0].name_zh))

lines = [
    "# 贴邻演出对普查（2026-11-07）",
    "",
    "夜场演出行 × 同城 1500m 步行圈高优先档观光行——现行引擎拆两天、",
    "贴邻同日偏好（_SHOW_ADJACENT_KM）修复的影响面。",
    "",
    f"- 库内 source 取值：{', '.join(sorted(str(s) for s in sources))}",
    f"- 演出行（命中词表）：{len(shows)} 行；其中仅夜场（含空 hours）"
    f"{len(night_only)} 行、多场次 {len(multi)} 行",
    f"- 有贴邻王牌的仅夜场演出：{len(pairs)} 行，共 "
    f"{sum(len(n) for _, n in pairs)} 对",
    "",
]
by_city: dict = {}
for r, near in pairs:
    by_city.setdefault(r.city, []).append((r, near))
for city in sorted(by_city):
    lines.append(f"## {city}（{len(by_city[city])} 演出行）")
    lines.append("")
    for r, near in by_city[city]:
        lines.append(
            f"- {r.name_zh}（{r.source}｜{r.category}｜hours="
            f"{r.opening_hours or '空'}｜{r.lng:.4f},{r.lat:.4f}）"
        )
        for n in near:
            lines.append(f"    - {n.dist_m}m ← {n.name_zh}（{n.source}｜{n.category}）")
    lines.append("")

with open(OUT, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"shows={len(shows)} night_only={len(night_only)} multi={len(multi)}")
print(f"pairs_rows={len(pairs)} pairs_total={sum(len(n) for _, n in pairs)}")
cd = [p for p in pairs if p[0].city and "成都" in str(p[0].city)]
print(f"chengdu_rows={len(cd)}")
