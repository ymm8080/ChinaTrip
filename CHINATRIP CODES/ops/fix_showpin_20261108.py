# -*- coding: utf-8 -*-
"""西安 5 演出行坐标投毒修复（2026-11-08）。

事故：import_shows 只插骨架行（无坐标），后续 enrich geocode 解析失败
**静默回退城市政府点**（app/services/city_fallback.py:29 注册：西安
108.94,34.341101=未央凤城八路市政府），5 行演出卡坐标+地址被投毒。

范围（只动 location/wgs84_location/address/address_en，其余字段一律不碰）：
- 22dc471c 《长恨歌》演出   ← 华清宫行（种子 CSV venue=华清宫·九龙湖）
- c92991f5 《梦回大唐》     ← 大雁塔大唐芙蓉园景区行（venue=大唐芙蓉园·凤鸣九天剧院）
- d9965828 《西安千古情》   ← 无可核实来源，人工清单（venue=宋城·西安千古情景区，库内无行，种子 CSV 无坐标列）
- dd76e61c 《驼铃传奇》秀   ← 无可核实来源，人工清单（venue=华夏文旅西安度假区，库内无行）
- 0acfffe8 《复活的军团》   ← 无可核实来源，人工清单（venue=大秦剧场（临潼），库内无行；秦俑情是另一剧场不可借用）

回源铁律：来源行坐标/地址运行时从库内实读（非硬编码），且必须 active、
非回退点、非空；目标行必须当前仍钉在回退点（防二次改写）。

用法：
    python ops/fix_showpin_20261108.py           # 干跑
    python ops/fix_showpin_20261108.py --apply   # 执行（备份+UPDATE）
"""

from __future__ import annotations

import io
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, text

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
DSN = "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"
APPLY = "--apply" in sys.argv
BAK_TABLE = "pois_showpin_bak_20261108"
MANUAL_FILE = HERE / "showpin_manual_20261108.txt"

XA_FALLBACK = (108.94, 34.341101)  # city_fallback.py 注册值

# 目标行 → 来源行（同场馆库内正确行；venue 依据 DESIGN/POIS DATASOURCE/
# 04_演艺演出_主要旅游城市.csv venue 列）
FIXES = [
    {
        "target": "22dc471c-c60c-4725-aed8-c271769c9962",
        "tname": "《长恨歌》演出",
        "source": "36144721-be9c-4c64-ba41-f3a6dae77e0e",
        "sname": "华清宫",
        "venue": "华清宫·九龙湖",
    },
    {
        "target": "c92991f5-ded1-4699-b4d6-4e4aa8886737",
        "tname": "《梦回大唐》",
        "source": "6db488ea-4110-4e62-acd6-574da600fca2",
        "sname": "大雁塔大唐芙蓉园景区",
        "venue": "大唐芙蓉园·凤鸣九天剧院",
    },
]
MANUAL = [
    ("d9965828-19fe-4b75-9ddb-c5321b701ebd", "《西安千古情》", "宋城·西安千古情景区"),
    ("dd76e61c-809d-457a-9f63-11ef748b3fdd", "《驼铃传奇》秀", "华夏文旅西安度假区"),
    ("0acfffe8-641c-44b3-94a8-7ab6873ccd48", "《复活的军团》", "大秦剧场（临潼）"),
]

SELECT = text(
    "select id, name_zh, status, address, address_en, "
    "ST_X(location::geometry) as lon, ST_Y(location::geometry) as lat, "
    "ST_X(wgs84_location::geometry) as wlon, ST_Y(wgs84_location::geometry) as wlat "
    "from pois where id=:id"
)


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    from math import asin, cos, radians, sin, sqrt

    r1, r2 = radians(lat1), radians(lat2)
    dl, dn = radians(lon2 - lon1), radians(lat2 - lat1)
    a = sin(dn / 2) ** 2 + cos(r1) * cos(r2) * sin(dl / 2) ** 2
    return 2 * 6371008.8 * asin(sqrt(a))


eng = create_engine(DSN, connect_args={"connect_timeout": 5})

with eng.connect() as c:
    # information_schema 对 geography 报 USER-DEFINED，实查 geography_columns
    geo_cols = {
        r[0]: (r[1], r[2])
        for r in c.execute(
            text(
                "select f_geography_column, type, srid from "
                "geography_columns where f_table_name='pois'"
            )
        ).all()
    }
print("geom cols:", geo_cols)
assert geo_cols.get("location") == ("Point", 4326), geo_cols
assert geo_cols.get("wgs84_location") == ("Point", 4326), geo_cols

log = []


def note(s: str) -> None:
    print(s)
    log.append(s)


with eng.connect() as c:
    rows = {}
    for fx in FIXES:
        t = c.execute(SELECT, {"id": fx["target"]}).mappings().one_or_none()
        s = c.execute(SELECT, {"id": fx["source"]}).mappings().one_or_none()
        assert t is not None, f"target missing {fx['target']}"
        assert s is not None, f"source missing {fx['source']}"
        assert t["name_zh"] == fx["tname"], (t["name_zh"], fx["tname"])
        assert s["name_zh"] == fx["sname"], (s["name_zh"], fx["sname"])
        assert s["status"] == "active", f"source not active: {fx['sname']}"
        assert t["status"] == "active", f"target not active: {fx['tname']}"
        # 来源行必须非回退点、坐标齐全
        assert s["lon"] is not None and s["lat"] is not None, "source coords null"
        d_src = haversine_m(s["lon"], s["lat"], *XA_FALLBACK)
        assert d_src > 5000, f"source {fx['sname']} 距回退点仅 {d_src:.0f}m，不可作来源"
        # 目标行必须当前仍钉在回退点（±200m）
        d_t = haversine_m(t["lon"], t["lat"], *XA_FALLBACK)
        assert d_t <= 200, f"target {fx['tname']} 不在回退点（{d_t:.0f}m），已被改过？"
        rows[fx["target"]] = (t, s)
    manual_rows = []
    for mid, mname, venue in MANUAL:
        m = c.execute(SELECT, {"id": mid}).mappings().one_or_none()
        assert m is not None and m["name_zh"] == mname, (m, mname)
        manual_rows.append(m)

# ---------------------------------------------------------------- 备份 + UPDATE
if APPLY:
    from sqlalchemy import bindparam

    with eng.begin() as c:
        c.execute(
            text(
                f"create table if not exists {BAK_TABLE} as "
                "select * from pois where false"
            )
        )
        c.execute(
            text(
                f"insert into {BAK_TABLE} select * from pois "
                "where id in :ids and id not in (select id from "
                f"{BAK_TABLE})"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": [fx["target"] for fx in FIXES]},
        )
        note(f"[backup] {BAK_TABLE} <- {len(FIXES)} rows")

        for fx in FIXES:
            t, s = rows[fx["target"]]
            res = c.execute(
                text(
                    "update pois set "
                    "location = ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, "
                    "wgs84_location = "
                    "ST_SetSRID(ST_MakePoint(:wlon,:wlat),4326)::geography, "
                    "address = :addr, address_en = :addr_en, updated_at = :now "
                    "where id = :id and status = 'active'"
                ),
                {
                    "lon": s["lon"],
                    "lat": s["lat"],
                    "wlon": s["wlon"],
                    "wlat": s["wlat"],
                    "addr": s["address"],
                    "addr_en": s["address_en"],
                    "now": datetime.now(timezone.utc),
                    "id": fx["target"],
                },
            )
            assert res.rowcount == 1, f"rowcount={res.rowcount} for {fx['tname']}"
            note(
                f"[update] {fx['tname']} ({fx['target'][:8]}) "
                f"venue={fx['venue']} <- {fx['sname']}\n"
                f"  loc : ({t['lon']:.6f},{t['lat']:.6f}) -> "
                f"({s['lon']:.6f},{s['lat']:.6f})\n"
                f"  wgs : ({t['wlon']:.6f},{t['wlat']:.6f}) -> "
                f"({s['wlon']:.6f},{s['wlat']:.6f})\n"
                f"  addr: {t['address']} -> {s['address']}"
            )
else:
    note("[dry-run] 不执行备份/UPDATE。逐行预览：")
    for fx in FIXES:
        t, s = rows[fx["target"]]
        note(
            f"[plan] {fx['tname']} ({fx['target'][:8]}) venue={fx['venue']} "
            f"<- {fx['sname']} ({fx['source'][:8]})\n"
            f"  loc : ({t['lon']:.6f},{t['lat']:.6f}) -> "
            f"({s['lon']:.6f},{s['lat']:.6f})\n"
            f"  addr: {t['address']} -> {s['address']}"
        )

# ---------------------------------------------------------------- 验证
with eng.connect() as c:
    note("\n== 验证 ==")
    for fx in FIXES:
        t = c.execute(SELECT, {"id": fx["target"]}).mappings().one()
        d_fb = haversine_m(t["lon"], t["lat"], *XA_FALLBACK)
        s = c.execute(SELECT, {"id": fx["source"]}).mappings().one()
        d_venue = haversine_m(t["lon"], t["lat"], s["lon"], s["lat"])
        ok = d_fb > 5000 and (d_venue < 1 if APPLY else True)
        note(
            f"{'OK ' if ok else '?? '}{t['name_zh']}: "
            f"({t['lon']:.5f},{t['lat']:.5f}) 距市政府回退点 {d_fb/1000:.2f}km；"
            f"距{fx['sname']} {d_venue:.1f}m；addr={t['address']}"
        )
    for m in manual_rows:
        d_fb = haversine_m(m["lon"], m["lat"], *XA_FALLBACK)
        note(
            f"MANUAL {m['name_zh']}: 仍钉回退点 ({d_fb:.0f}m) 未动 — "
            "无可核实来源"
        )

# ---------------------------------------------------------------- 人工清单
manual_txt = [
    "# 西安演出卡坐标投毒 — 人工待办（2026-11-08, fix_showpin_20261108.py）",
    "#",
    "# 3 行已修：长恨歌←华清宫行、梦回大唐←大唐芙蓉园行（备份表",
    f"# {BAK_TABLE}）。以下 3 行无可核实来源，未动，须人工核址后修复：",
    "# 可用路径：人工查场馆真实地址 -> 百度 geocode（有地址才 geocode；",
    "# 高德 WAF 封禁中不可用）；或等高德解封后用 POI 搜索回填。",
    "",
]
for mid, mname, venue in MANUAL:
    m = next(r for r in manual_rows if str(r["id"]) == mid)
    manual_txt += [
        f"- {mname}  id={mid}",
        f"  现状: loc=({m['lon']:.6f},{m['lat']:.6f}) addr={m['address']}",
        f"  场馆(种子CSV venue列): {venue}",
        "  不可用来源: 库内无该场馆行；04 号种子及其它 DESIGN CSV 均无坐标列；",
        "  高德 WAF；百度仅当地址已核实正确（现地址已投毒，不满足）。",
        "",
    ]
manual_txt += [
    "# 附带观察（超出本任务 5 行范围，未动，仅登记）：",
    "# - 陕西水利博物馆 id=bdb55542-00fe-4d32-8b57-0ec48cade43c (active, museum3)",
    "#   同钉西安回退点 108.94,34.341101，需另行回源核实。",
    "# - 周至水街沙沙河景区 id=f6d5727a-6a5d-444b-b4e0-1783efbc54df (inactive, 4a)",
    "#   同钉回退点，已退役影响小，登记备查。",
]
with io.open(MANUAL_FILE, "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(manual_txt) + "\n")
note(f"\nmanual list written: {MANUAL_FILE}")

with io.open(HERE / "_tmp_fix_showpin_20261108.log", "w", encoding="utf-8", newline="\n") as f:
    f.write("\n".join(log) + "\n")
print(f"\nmode={'APPLY' if APPLY else 'DRY-RUN'} done.")
