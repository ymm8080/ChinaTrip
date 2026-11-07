# -*- coding: utf-8 -*-
"""西安熊猫馆心愿落地：秦岭四宝科学公园 curated 入库（2026-11-07）。

案情：用户心愿「看熊猫」在西安行程被早前行程 _backfill_wish_city 毒成
city=成都而蒸发；库内西安没有熊猫行（active zoo 仅成都基地/北京大熊猫馆）。
引擎侧宽恕链已修（_wish_city_in_session + _wish_core_hit 别名通道），本脚本
补数据面：把 秦岭四宝科学公园（周至县楼观镇，西安周边看大熊猫主去处，
别名 西安熊猫馆/秦岭大熊猫研究中心/秦岭四宝）以 curated 入库。

针址依据（2026-11-07 amap /v3/geocode/geo 实测，无精确坐标不落库）：
- address = 陕西省西安市周至县楼观镇秦岭四宝科学公园，city=西安
- 守卫：adcode=610124（周至县）∧ level∈{兴趣点,门址,门牌号}——
  geocode 落到区县/城镇质心一律拒写（投毒铁律）。
- GCJ-02 → wgs84 用 app.services.coords 既有实现。

写入（--apply 才动库；DRY-RUN 默认）：source='curated'、
source_poi_id='curated:西安:秦岭四宝科学公园'、tags=["curated"]、
category='zoo'、name_aliases=["西安熊猫馆","秦岭大熊猫研究中心","秦岭四宝"]、
hours 旺季(03-01至11-30)周一至周日09:00-17:00、票 30、时长 240、bvt any、
rain_ok partial、district 周至县。
守卫：source_poi_id 不存在 ∧ 同城 active 无同名/别名撞行（秦岭四宝/
熊猫 字样出现即人工复核中止）。
回滚：INSERT-only，删除语句打印进报告 ops/qinling_panda_import_20261107.md。

产出：ops/qinling_panda_import_20261107.md
"""

import asyncio
import io
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

APPLY = "--apply" in sys.argv

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from app.services.coords import gcj02_to_wgs84  # noqa: E402

DSN = "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"
OUT_MD = HERE / "ops" / "qinling_panda_import_20261107.md"

PID = "curated:西安:秦岭四宝科学公园"
NAME = "秦岭四宝科学公园"
ALIASES = ["西安熊猫馆", "秦岭大熊猫研究中心", "秦岭四宝"]
CITY = "西安"
GEO_ADDRESS = "陕西省西安市周至县楼观镇秦岭四宝科学公园"
ADCODE_GUARD = "610124"  # 周至县
LEVEL_OK = {"兴趣点", "门址", "门牌号"}

HOURS = "旺季(03-01至11-30)周一至周日09:00-17:00"
INTRO = (
    "秦岭四宝科学公园（秦岭大熊猫研究中心）位于周至县楼观镇，展示大熊猫、"
    "朱鹮、金丝猴、羚牛「秦岭四宝」，是西安周边看大熊猫的主要去处。"
)
INTRO_EN = (
    "Qinling Four Treasures Science Park (Qinling Giant Panda Research Center) "
    "in Louguan Town, Zhouzhi County, is Xi'an's main spot to see giant pandas, "
    "plus crested ibis, golden monkeys and takins — the 'Four Treasures of "
    "the Qinling'."
)

KEY = ""
for line in open(HERE / ".env", encoding="utf-8-sig"):
    if line.strip().startswith("AMAP_API_KEY"):
        KEY = line.split("=", 1)[1].strip()
assert KEY, "no AMAP key"


async def geocode_with_adcode() -> dict:
    """raw /v3/geocode/geo（client.geocode 不回 adcode，守卫需要）。"""
    async with httpx.AsyncClient(timeout=10) as cli:
        r = await cli.get(
            "https://restapi.amap.com/v3/geocode/geo",
            params={
                "key": KEY,
                "address": GEO_ADDRESS,
                "city": CITY,
                "output": "JSON",
            },
        )
        r.raise_for_status()
        data = r.json()
    geos = data.get("geocodes") or []
    if not geos or not isinstance(geos[0], dict):
        return {}
    g = geos[0]
    lonlat = str(g.get("location") or "").split(",")
    return {
        "adcode": str(g.get("adcode") or ""),
        "level": str(g.get("level") or ""),
        "district": str(g.get("district") or ""),
        "lon": float(lonlat[0]) if len(lonlat) == 2 else None,
        "lat": float(lonlat[1]) if len(lonlat) == 2 else None,
    }


def main() -> int:
    geo = asyncio.run(geocode_with_adcode())
    print("geocode:", json.dumps(geo, ensure_ascii=False))
    if (
        geo.get("lon") is None
        or geo.get("adcode") != ADCODE_GUARD
        or geo.get("level") not in LEVEL_OK
    ):
        print(
            f"!! 守卫不符：adcode={geo.get('adcode')} level={geo.get('level')} "
            f"（要求 adcode={ADCODE_GUARD} ∧ level∈{sorted(LEVEL_OK)}）——不落库"
        )
        return 2
    lon, lat = geo["lon"], geo["lat"]
    wlon, wlat = gcj02_to_wgs84(lon, lat)
    print(f"pin gcj=({lon},{lat})  wgs=({wlon:.6f},{wlat:.6f})")

    eng = create_engine(DSN, connect_args={"connect_timeout": 3})
    with eng.connect() as c:
        dup_pid = c.execute(
            text("select 1 from pois where source='curated' and source_poi_id=:p"),
            {"p": PID},
        ).first()
        clash = c.execute(
            text(
                "select name_zh, status, source from pois where city=:city "
                "and (name_zh like '%秦岭四宝%' or name_zh like '%熊猫%' "
                "or cast(name_aliases as text) like '%秦岭四宝%' "
                "or cast(name_aliases as text) like '%熊猫%')"
            ),
            {"city": CITY},
        ).all()
    if dup_pid:
        print(f"!! source_poi_id 已存在：{PID}——幂等退出")
        return 0
    if clash:
        for n, st, src in clash:
            print(f"!! 同城撞行：{n} ({st}, {src})——人工复核，中止")
        return 3

    print(f"({APPLY=}) insert curated row: {NAME} aliases={ALIASES}")
    if not APPLY:
        print("DRY-RUN 完，未写库")
        return 0

    now = datetime.now()
    with eng.begin() as c:
        c.execute(
            text(
                """insert into pois
                (id, source, source_poi_id, city, name_zh, name_en, category,
                 status, location, wgs84_location, address, district,
                 opening_hours, hours_source, hours_updated_at,
                 suggested_duration_min, duration_source,
                 best_visit_time, best_visit_time_source,
                 ticket_price_min, ticket_price_max, ticket_source,
                 tags, tags_source, intro, intro_source, intro_en,
                 address_en, name_aliases, rain_ok, indoor, updated_at)
                values (:id, 'curated', :pid, :city, :name, :name_en, 'zoo',
                 'active',
                 ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
                 ST_SetSRID(ST_MakePoint(:wlon, :wlat), 4326)::geography,
                 :address, :district, :hours, 'curated', :hnow,
                 240, 'curated', 'any', 'curated',
                 30, 30, 'curated',
                 '["curated"]'::jsonb, 'curated', :intro, 'curated', :intro_en,
                 :address_en, cast(:aliases as jsonb), 'partial', 'no', :hnow)"""
            ),
            {
                "id": str(uuid.uuid4()),
                "pid": PID,
                "city": CITY,
                "name": NAME,
                "name_en": "Qinling Four Treasures Science Park",
                "lon": lon,
                "lat": lat,
                "wlon": wlon,
                "wlat": wlat,
                "address": GEO_ADDRESS,
                "district": geo.get("district") or "周至县",
                "hours": HOURS,
                "hnow": now,
                "intro": INTRO,
                "intro_en": INTRO_EN,
                "address_en": "Louguan Town, Zhouzhi County, Xi'an, Shaanxi Province",
                "aliases": json.dumps(ALIASES, ensure_ascii=False),
            },
        )

    md = []
    state = "已执行" if APPLY else "干跑"
    md.append(f"# 秦岭四宝科学公园 curated 入库单（2026-11-07，{state}）\n")
    md.append(
        "\n> 案情：心愿「看熊猫」被跨程 backfill 毒城成都而蒸发；西安库内无熊猫行。"
        "引擎宽恕链+别名通道已修，本脚本补数据面。针址 amap geocode 实测"
        f"（adcode={ADCODE_GUARD} 周至县，level={geo.get('level')}），"
        f"gcj=({lon},{lat})。\n"
    )
    md.append(f"\n执行时刻 {now.isoformat(timespec='seconds')}\n")
    md.append(
        f"\n行：{PID}｜aliases={ALIASES}｜zoo｜240min｜票30｜bvt any｜"
        "rain_ok partial｜hours " + HOURS + "\n"
    )
    md.append("\n### 回滚语句\n\n```sql\n")
    md.append(f"DELETE FROM pois WHERE source='curated' AND source_poi_id='{PID}';\n")
    md.append("```\n")
    io.open(OUT_MD, "w", encoding="utf-8", newline="\n").write("".join(md))
    print("md written:", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
