# -*- coding: utf-8 -*-
"""街道行退役扫街（2026-11-07 用户拍板）。

规则（用户原话裁决）：街 + 街上有站点 → 留站点、街行退役。

v2 判定（一拍干跑 208 行证据审后收口——「附近」≠「在街上」）：
- 成员站点「在街上」的 ground truth = 站点 address/name_zh 提及街名
  （街名核=街名中任一以 街|巷|坊 结尾的 3-12 字子串）；距离仅做
  5km 封顶防坏针 nonsense，>1.5km 在台账标旗。半径直配版会把
  虎跳峡(坏针)/三里屯太古里(异街区) 当成员误退役大研花巷/751，废。
- 退役目标谓词：active ∧ (citywalk ∨ 名含街|巷|坊) ∧ category
  ∉ {hotel,transport,food,entertainment,theme_park,museum,memorial,
  gallery,art,zoo,church,temple,castle,ruins,garden}（利济巷慰安所
  旧址陈列馆=博物馆名带巷，不可退役）∧ 名不以
  镇|村|景区|风景区|旅游区|度假区 结尾（贺街镇/乌拉街镇=城镇规模）。
- 成员站点：同城 ∧ active ∧ category ∉ {hotel,transport,food,
  entertainment,theme_park} ∧ 名不含 街|巷|坊|路|大道|胡同
  （街不退役街——黄河路误退役南京路步行街案；跨源重复街交给去重链）
  ∧ (名∨地址)提及街名核 ∧ 距离≤5km。
- 回民街（964743f1-13c9-4bf5-9271-a6326d7735fe）为点名件，强制在
  退役单（漏网则补入并告警）。
- 退役 = status='inactive' 软删（引擎读池自动不见，快照可回滚）。
  退役行 hours_updated_at 顶到 NOW()：hours-refresh 供应商换键链
  （stale_pois 无 status 过滤）不再碰退役行，防换键后 seed 重插活行。
- 每行退役前：快照表 pois_street_sweep_bak_20261107 + 全字段 CSV；
  UPDATE 带 status='active' 守卫，行数不符告警。
- DRY-RUN 默认，--apply 才动库。

产出：ops/street_retire_20261107.md + ops/streets_retired_backup_2026-11-07.csv
"""

import csv
import io
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

APPLY = "--apply" in sys.argv

from sqlalchemy import bindparam, create_engine, text  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
DSN = "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"
OUT_MD = HERE / "street_retire_20261107.md"
OUT_CSV = HERE / "streets_retired_backup_2026-11-07.csv"
BAK_TABLE = "pois_street_sweep_bak_20261107"

MAX_MEMBER_KM = 5.0
QUALIFY_KM = 1.5  # ≤1.5km 且名/址提及街名核才算合格佐证；以上只标旗
FORCE_IDS = {"964743f1-13c9-4bf5-9271-a6326d7735fe"}  # 回民街（点名件）

# hospitality 词根（酒店分支/民宿/精舍/府等门店命名混名带街语素的行，
# 无论 category 标什么都不可当街退役——泽一居精舍(观前街平江路店)/
# 南锣鼓巷古韵坊四合院漫心府案）
HOSPITALITY_PAT = re.compile(r"酒店|宾馆|民宿|饭店|公寓|客栈|精舍|府$|漫心")

TARGET_SQL = (
    "select id, name_zh, city, category, source, source_poi_id, address, "
    "ST_X(location::geometry) as lon, ST_Y(location::geometry) as lat "
    "from pois where status='active' and location is not null and "
    "(category='citywalk' or (name_zh ~ '(街|巷|坊)' and "
    "(category is null or category not in "
    "('hotel','transport','food','entertainment','theme_park','museum',"
    "'memorial','gallery','art','zoo','church','temple','castle',"
    "'ruins','garden')))) "
    "and name_zh !~ '(镇|村|景区|风景区|旅游区|度假区)$'"
)
MEMBER_SQL = (
    "select id, name_zh, city, category, source, source_poi_id, address, "
    "ST_X(location::geometry) as lon, ST_Y(location::geometry) as lat "
    "from pois where status='active' and location is not null and "
    "(category is null or category not in "
    "('hotel','transport','food','entertainment','theme_park')) "
    "and name_zh !~ '(街|巷|坊|路|大道|胡同)'"
)

_MORPH = ("街", "巷", "坊")


def street_cores(name: str) -> list[str]:
    """街名核：以 街|巷|坊 结尾的 3-12 字子串（长官方名剥省市区前缀
    靠子串枚举天然覆盖）。"""
    out: set[str] = set()
    n = len(name)
    for i in range(n):
        for j in range(i + 3, min(i + 13, n + 1)):
            seg = name[i:j]
            if seg.endswith(_MORPH):
                out.add(seg)
    return sorted(out, key=len, reverse=True)


eng = create_engine(DSN, connect_args={"connect_timeout": 3})
with eng.connect() as c:
    _streets = c.execute(text(TARGET_SQL)).mappings().all()
    members = c.execute(text(MEMBER_SQL)).mappings().all()

# 主名才测街语素（括号剥除）：苏州古运河游船(山塘街白居易码头) 这类
# 分支括注行不是街；门店词根行无论 category 不是街。
streets = []
for s in _streets:
    nm = s["name_zh"] or ""
    main = re.sub(r"[（(][^（）()]*[)）]", "", nm)
    if not any(m in main for m in _MORPH):
        continue
    if HOSPITALITY_PAT.search(main):
        continue
    streets.append(s)

print(f"street rows={len(streets)} member-site rows={len(members)}")

by_city: dict[str, list[dict]] = {}
for r in members:
    by_city.setdefault((r["city"] or "").strip(), []).append(dict(r))


def haversine_km(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


hits = []  # (street, [ (member, dist_km, via, core), ... ] 近→远)
flags = []  # (street, member, dist) 1.5-5km 名/址提及但针远——只标旗
for s in streets:
    pool = by_city.get((s["city"] or "").strip(), [])
    cores = street_cores(s["name_zh"] or "")
    if not cores:
        continue
    near = []
    for m in pool:
        if str(m["id"]) == str(s["id"]):
            continue
        mname = m["name_zh"] or ""
        maddr = m["address"] or ""
        core = next((k for k in cores if k in mname), None)
        via = "name" if core else None
        if core is None:
            core = next((k for k in cores if k in maddr), None)
            via = "addr" if core else None
        if core is None:
            continue
        d = haversine_km(
            float(s["lon"]), float(s["lat"]), float(m["lon"]), float(m["lat"])
        )
        if d > MAX_MEMBER_KM:
            continue
        if d <= QUALIFY_KM:
            near.append((m, d, via, core))
        else:
            flags.append((s, m, d))
    near.sort(key=lambda t: t[1])
    if near:
        hits.append((s, near))

retire_ids = {str(s["id"]) for s, _ in hits}
all_street_ids = {str(s["id"]) for s in streets}
missing_force = FORCE_IDS - retire_ids
if missing_force:
    with eng.connect() as c:
        for pid in missing_force:
            row = (
                c.execute(
                    text(
                        "select id, name_zh, city, category, source, source_poi_id, "
                        "address, ST_X(location::geometry) as lon, "
                        "ST_Y(location::geometry) as lat "
                        "from pois where id=:id and status='active'"
                    ),
                    {"id": pid},
                )
                .mappings()
                .first()
            )
            if row:
                hits.append((dict(row), []))
                retire_ids.add(str(row["id"]))
                print(f"!! 点名件漏网补入: {row['name_zh']} ({row['city']})")

print(
    f"retire={len(retire_ids)} keep={len(all_street_ids - retire_ids)} "
    f"({'APPLY' if APPLY else 'DRY-RUN'})"
)

city_stat: dict[str, int] = {}
for s, _ in hits:
    city = (s["city"] or "").strip()
    city_stat[city] = city_stat.get(city, 0) + 1
print("retire by city:", dict(sorted(city_stat.items(), key=lambda kv: -kv[1])))

ids = sorted(retire_ids)

# ---------------------------------------------------------------- 备份+退役
if ids and APPLY:
    with eng.begin() as c:
        c.execute(
            text(
                f"create table if not exists {BAK_TABLE}"
                " as select * from pois where false"
            )
        )
        c.execute(
            text(
                f"insert into {BAK_TABLE} select * from pois "
                "where id in :ids and id not in (select id from " + BAK_TABLE + ")"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": ids},
        )
        for pid in ids:
            res = c.execute(
                text(
                    "update pois set status='inactive', updated_at=NOW(), "
                    "hours_updated_at=NOW() where id=:id and status='active'"
                ),
                {"id": pid},
            )
            if res.rowcount != 1:
                print(f"!! rowcount={res.rowcount} for {pid}")
    with eng.connect() as c:
        snap = (
            c.execute(
                text("select * from pois where id in :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"ids": ids},
            )
            .mappings()
            .all()
        )
    if snap:
        cols = list(snap[0].keys())

        def cell(v):
            if v is None:
                return ""
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False)
            return str(v)

        with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in snap:
                w.writerow([cell(r[k]) for k in cols])

# ---------------------------------------------------------------- 报告
now = datetime.now().isoformat(timespec="seconds")
md = []
md.append(f"# 街道行退役处置单（2026-11-07，{'已执行' if APPLY else '干跑清单'}）\n")
md.append(
    "\n> 用户拍板：街 + 街上有站点 → 留站点、街行退役。v2 判定：站点"
    "「在街上」= address/name 提及街名核（3-12 字以街|巷|坊结尾子串），"
    "距离仅 5km 封顶（>1.5km 标旗）；退役目标剔场馆类别与镇/村/景区尾；"
    "成员剔街名行（街不退役街）。回民街为点名件。退役=status='inactive'"
    f" 软删+hours_updated_at 冷却（防 refresh 换键复活）。快照表 "
    f"{BAK_TABLE} + CSV {OUT_CSV.name}。\n"
)
md.append(
    f"\n处置时刻 {now}；街道候选 {len(streets)} 行，退役 {len(retire_ids)} 行，"
    f"保留（无在街站点）{len(all_street_ids - retire_ids)} 行。\n"
)
md.append("\n退役分城：\n\n| 城市 | 退役数 |\n|---|---|\n")
for city, n in sorted(city_stat.items(), key=lambda kv: -kv[1]):
    md.append(f"| {city} | {n} |\n")

md.append("\n## 退役清单（含在街站点证据）\n\n")
md.append(
    "| 城市 | 街道行 | source | 在街站点（近→远，km，经名/经址） |\n|---|---|---|---|\n"
)
for s, near in hits:
    ev = (
        "；".join(
            f"{m['name_zh']}({d:.2f},{via}:{core})" for m, d, via, core in near[:5]
        )
        or "（点名件强制退役）"
    )
    md.append(f"| {s['city']} | {s['name_zh']} | {s['source']} | {ev} |\n")

flagged = flags
if flagged:
    md.append("\n## 距离标旗（1.5-5km，名/址提及但针远——只标旗不退役）\n\n")
    md.append("| 城市 | 街道行 | 站点 | 距离km |\n|---|---|---|---|\n")
    for s, m, d in flagged:
        md.append(f"| {s['city']} | {s['name_zh']} | {m['name_zh']} | {d:.2f} |\n")

md.append("\n### 回滚语句（逐行）\n\n```sql\n")
for pid in ids:
    md.append(
        f"UPDATE pois SET status='active', updated_at=NOW() "
        f"WHERE id='{pid}' AND NOT EXISTS (SELECT 1 FROM {BAK_TABLE} "
        f"b WHERE b.id='{pid}' AND b.status<>'active');\n"
    )
md.append("```\n")

with io.open(OUT_MD, "w", encoding="utf-8", newline="\n") as f:
    f.write("".join(md))

print("md written:", OUT_MD)
print("csv written:", OUT_CSV if (ids and APPLY) else "(dry-run, no csv)")
print("== RETIRED (first 60) ==")
for s, near in hits[:60]:
    ev = f"{near[0][0]['name_zh']}({near[0][1]:.2f},{near[0][2]})" if near else "FORCE"
    print(f"  {s['city']:6s} {s['name_zh']} <- {ev}")
