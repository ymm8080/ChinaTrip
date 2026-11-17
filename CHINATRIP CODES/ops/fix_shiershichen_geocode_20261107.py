# -*- coding: utf-8 -*-
"""长安十二时辰主题街区坏针修复（2026-11-07，用户拍板「修」）。

案情：pois 行 11bde382-5242-46fe-b9a2-c59b21b87cb6（source=show，西安）整条
地理编码落在长安区政府（韦曲，108.907/34.158），address/address_en 同错；
真实位置是雁塔区大雁塔旁曼蒂广场（约 4.8km 外）。

修针依据（2026-11-07 amap 实测）：
- /v5/place/around 独立风控池检索到街区本体 POI B0IA1HURD6
  「长安十二时辰主题街区」(购物服务;特色商业街)，GCJ-02
  (108.966004, 34.21198)，address=大唐不夜城东侧曼蒂广场南门；
- /v3/geocode/geo「曼蒂广场」= (108.966051, 34.212861) level=兴趣点，交叉印证；
- regeo 标准地址 = 陕西省西安市雁塔区大雁塔街道曼蒂广场（district=雁塔区，
  与库内 district 裸格式一致；business_area 西安全空，不动）。

写入（--apply 才动库；DRY-RUN 默认）：
- location        = amap GCJ-02 (108.966004, 34.21198)（街区本体针，非商场质心）
- wgs84_location  = gcj02_to_wgs84 同点（app/services/coords 既有实现）
- address/address_en/district 按上述定稿；updated_at=NOW()
守卫：id ∧ status='active' ∧ 旧地址含「长安区人民政府」——坏针已被人修过则拒写。
备份：表 pois_shiershichen_geofix_bak_20261107 全行快照 + JSON 逐行落盘；
回滚语句打印进报告 ops/shiershichen_geofix_20261107.md。

产出：ops/shiershichen_geofix_20261107.md
      ops/pois_shiershichen_geofix_backup_20261107.json
"""

import io
import json
import sys
from datetime import datetime
from pathlib import Path

APPLY = "--apply" in sys.argv

from sqlalchemy import create_engine, text  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from app.services.coords import gcj02_to_wgs84  # noqa: E402

DSN = "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"
POI_ID = "11bde382-5242-46fe-b9a2-c59b21b87cb6"
BAK_TABLE = "pois_shiershichen_geofix_bak_20261107"
OUT_JSON = HERE / "ops" / "pois_shiershichen_geofix_backup_20261107.json"
OUT_MD = HERE / "ops" / "shiershichen_geofix_20261107.md"

# amap 实测定稿（见模块 docstring 依据链）
NEW = {
    "address": "陕西省西安市雁塔区大雁塔街道曼蒂广场",
    "address_en": "Mandi Plaza, Dayanta Subdistrict, Yanta District, Xi'an, "
    "Shaanxi Province",
    "district": "雁塔区",
}
GCJ_LON, GCJ_LAT = 108.966004, 34.21198
WGS_LON, WGS_LAT = gcj02_to_wgs84(GCJ_LON, GCJ_LAT)

OLD_GUARD = "长安区人民政府"  # 坏针指纹：address 仍指区政府才允许写

eng = create_engine(DSN, connect_args={"connect_timeout": 3})

with eng.connect() as c:
    row = (
        c.execute(
            text(
                "select id, name_zh, city, address, district, status, "
                "ST_X(location::geometry) as lon, ST_Y(location::geometry) as lat "
                "from pois where id=:id"
            ),
            {"id": POI_ID},
        )
        .mappings()
        .first()
    )
if not row:
    print("!! 目标行不存在:", POI_ID)
    sys.exit(1)

print(f"target: {row['name_zh']} ({row['city']}) status={row['status']}")
print(f"  old addr: {row['address']}")
print(f"  old pin : {row['lon']:.6f},{row['lat']:.6f}")
print(f"  new addr: {NEW['address']}")
print(f"  new gcj : {GCJ_LON:.6f},{GCJ_LAT:.6f}   new wgs: {WGS_LON:.6f},{WGS_LAT:.6f}")
print(f"({len(NEW)} fields + 2 pins, {'APPLY' if APPLY else 'DRY-RUN'})")

if row["status"] != "active" or OLD_GUARD not in (row["address"] or ""):
    print(f"!! 守卫不符：status={row['status']} 或旧地址已不含坏针指纹——拒写")
    sys.exit(2)

if APPLY:
    with eng.begin() as c:
        c.execute(
            text(
                f"create table if not exists {BAK_TABLE} as "
                "select * from pois where false"
            )
        )
        c.execute(
            text(
                f"insert into {BAK_TABLE} select * from pois where id=:id "
                f"and id not in (select id from {BAK_TABLE})"
            ),
            {"id": POI_ID},
        )
        res = c.execute(
            text(
                "update pois set address=:address, address_en=:address_en, "
                "district=:district, "
                "location=ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography, "
                "wgs84_location=ST_SetSRID(ST_MakePoint(:wlon, :wlat), 4326)::geography, "
                "updated_at=NOW() "
                "where id=:id and status='active' and address like :guard"
            ),
            {
                "id": POI_ID,
                "guard": f"%{OLD_GUARD}%",
                "lon": GCJ_LON,
                "lat": GCJ_LAT,
                "wlon": WGS_LON,
                "wlat": WGS_LAT,
                **NEW,
            },
        )
        if res.rowcount != 1:
            print(f"!! rowcount={res.rowcount}（守卫或并发拦截），中止")
            sys.exit(3)

    with eng.connect() as c:
        snap = (
            c.execute(
                text("select * from pois where id=:id"), {"id": POI_ID}
            )
            .mappings()
            .first()
        )
    out = {}
    for k, v in dict(snap).items():
        if isinstance(v, (bytes, memoryview)):
            v = bytes(v).hex()  # geography 列回读 EWKB，hex 落盘可重灌
        out[k] = v
    OUT_JSON.write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )

    now = datetime.now().isoformat(timespec="seconds")
    md = []
    md.append(f"# 十二时辰坏针修复单（2026-11-07，{'已执行' if APPLY else '干跑'}）\n")
    md.append(
        "\n> 案情：show 源行整条地理编码落在长安区政府（韦曲），真身在雁塔区"
        "曼蒂广场。依据 amap place/around POI B0IA1HURD6 + geocode 曼蒂广场 "
        "+ regeo 标准地址交叉定稿。守卫：旧地址含「长安区人民政府」∧ active。"
        f"备份表 {BAK_TABLE} + JSON {OUT_JSON.name}。\n"
    )
    md.append(f"\n执行时刻 {now}\n")
    md.append(f"\n新值：address={NEW['address']}；district={NEW['district']}；"
              f"gcj=({GCJ_LON},{GCJ_LAT})；wgs=({WGS_LON:.6f},{WGS_LAT:.6f})\n")
    md.append("\n### 回滚语句\n\n```sql\n")
    md.append(
        f"UPDATE pois SET address=(select address from {BAK_TABLE} where id='{POI_ID}'),"
        f" address_en=(select address_en from {BAK_TABLE} where id='{POI_ID}'),"
        f" district=(select district from {BAK_TABLE} where id='{POI_ID}'),"
        f" location=(select location from {BAK_TABLE} where id='{POI_ID}'),"
        f" wgs84_location=(select wgs84_location from {BAK_TABLE} where id='{POI_ID}'),"
        f" updated_at=NOW() WHERE id='{POI_ID}';\n"
    )
    md.append("```\n")
    io.open(OUT_MD, "w", encoding="utf-8", newline="\n").write("".join(md))
    print("md written:", OUT_MD)
    print("json written:", OUT_JSON)
