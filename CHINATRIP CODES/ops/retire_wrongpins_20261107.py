# -*- coding: utf-8 -*-
"""错针批量退役（2026-11-07）。承接 scan_wrongpins_20261107.py 的只读扫描，
对主清单（tier1 131 对）执行保守自动退役 + 全量人工复核归档。

口径（从紧，宁缺勿滥）：
- 自动退役仅限「事故形态」行：A 为 ct 形态（source_poi_id 带 ct_ 前缀，
  锦里古戏台/武侯祠案同型）∧ tier1 ∧ A/B 同 category ∧ 无 B区块旗
  （B 为面实体时子点位 1-5km 属合法几何，扫描口径即标「缓判」）
  ∧ 无类别差旗 ∧ A 名无分馆/馆区/展区/校区类分支标记 ∧ A 或 B 针
  无跨行重复（重复针=导入串行污染，须修坐标而非退役）∧ B 针在同城
  池行经纬框内（防 B 本身坏针）。
- 其余全部 SKIP 归档人工复核（含 68 对非 ct 源：品牌并名 5A/景区
  活动点/子场馆等假阳性形态密集，不进自动批）。
- 每行退役前：快照表 pois_wrongpin_bak_20261107 + 全字段 CSV 备份；
  UPDATE 带 status='active' 守卫，行数不符即记异常。
- 退役 = 软删让位（status='inactive'），引擎读池自动改用 B
  （既有口径：退役先查同城 active 同实体）。

产出：ops/wrongpin_retire_20261107.md + stdout 统计。
"""

import csv
import io
import importlib.util
import json
import re
import sys
from datetime import datetime
from pathlib import Path

APPLY = "--apply" in sys.argv

from sqlalchemy import bindparam, create_engine, text

sys.stdout.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
DSN = "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"
OUT_MD = HERE / "wrongpin_retire_20261107.md"
OUT_CSV = HERE / "pois_retired_backup_2026-11-07_wrongpin_batch.csv"
BAK_TABLE = "pois_wrongpin_bak_20261107"

# ---------------------------------------------------------------- 复用扫描
spec = importlib.util.spec_from_file_location(
    "wrongpin_scan", HERE / "scan_wrongpins_20261107.py"
)
scan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scan)  # 只读重扫，附带刷新 MD

main_pairs = scan.main_pairs  # tier1 且非地理核
print(f"scan: main_pairs={len(main_pairs)}")

# ---------------------------------------------------------------- 守卫
BRANCH_PAT = re.compile(
    r"分馆|馆区|展区|校区|新馆|东馆|西馆|南馆|北馆|[（(][^（）()]*馆[)）]"
)
ACTIVITY_CAT = {"entertainment", "theme_park", "show"}
COORD_KEY = lambda lon, lat: (round(lon, 5), round(lat, 5))  # noqa: E731

eng = create_engine(DSN, connect_args={"connect_timeout": 3})
with eng.connect() as c:
    all_rows = c.execute(
        text(
            "select id, name_zh, source_poi_id, city, category, status, "
            "ST_X(location::geometry) as lon, ST_Y(location::geometry) as lat "
            "from pois where location is not null"
        )
    ).mappings().all()

by_id = {str(r["id"]): dict(r) for r in all_rows}
# 同城针重复索引（5dp）：pin -> [id,...]（含全状态行，污染检测要全量）
pin_index = {}
city_bbox = {}
for r in all_rows:
    city = (r["city"] or "").strip()
    key = COORD_KEY(float(r["lon"]), float(r["lat"]))
    pin_index.setdefault(key, []).append(str(r["id"]))
    b = city_bbox.setdefault(city, [999.0, 999.0, -999.0, -999.0])
    lon, lat = float(r["lon"]), float(r["lat"])
    b[0] = min(b[0], lon)
    b[1] = min(b[1], lat)
    b[2] = max(b[2], lon)
    b[3] = max(b[3], lat)

decisions = []  # (pair, decision, reason)


def classify(p):
    a, b = p["a"], p["b"]
    ra = by_id.get(a["id"])
    if ra is None or ra["status"] != "active":
        return "skip", "A行已不在池/非active"
    cur = COORD_KEY(float(ra["lon"]), float(ra["lat"]))
    if cur != COORD_KEY(a["lon"], a["lat"]):
        return "skip", "A坐标已变（扫描后被动过）"
    if BRANCH_PAT.search(a["name"]):
        return "manual", "A名含分馆/馆区/校区类标记（疑真实分支场馆）"
    if not p["ct"]:
        return "manual", "非ct形态（品牌并名/活动点形态密集，人工复核）"
    if a["cat"] != b["cat"]:
        return "manual", f"类别差{a['cat']}/{b['cat']}（异实体或活动点嫌疑）"
    if "B区块" in p["notes"]:
        return "manual", "B为面实体/区块（子点位合法几何，人工缓判）"

    def core_tail(nm):
        return re.sub(r"[（(][^（）()]*[)）]", "", nm)[-2:]

    if core_tail(a["name"]) != core_tail(b["name"]):
        return "manual", (
            f"尾词异{core_tail(a['name'])}/{core_tail(b['name'])}"
            "（广场/大桥/展厅类异实体嫌疑）"
        )
    # 重复针污染：A 或 B 的针与任一同城异行完全相等
    for side in (a, b):
        hits = pin_index.get(COORD_KEY(side["lon"], side["lat"]), [])
        if any(h != side["id"] for h in hits):
            return "manual", (
                f"{side['name']}针与其余行完全重复"
                "（导入串针污染，须修坐标非退役）"
            )
    # B 针须在同城框内
    bb = city_bbox.get(b["city"])
    if bb and not (bb[0] <= b["lon"] <= bb[2] and bb[1] <= b["lat"] <= bb[3]):
        return "manual", "B针出同城框（B自身坏针嫌疑，退役A会丢真身）"
    return "retire", "事故形态全闸通过"


for p in main_pairs:
    d, why = classify(p)
    decisions.append((p, d, why))

retire = [(p, w) for p, d, w in decisions if d == "retire"]
manual = [(p, w) for p, d, w in decisions if d == "manual"]
skipped = [(p, w) for p, d, w in decisions if d == "skip"]
ids = [p["a"]["id"] for p, _ in retire]
print(f"retire={len(retire)} manual={len(manual)} skip={len(skipped)} "
      f"({'APPLY' if APPLY else 'DRY-RUN'})")

# ---------------------------------------------------------------- 备份
if ids and APPLY:
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
            {"ids": ids},
        )
    # CSV 全字段备份
    with eng.connect() as c:
        snap = c.execute(
            text("select * from pois where id in :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        ).mappings().all()
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

# ---------------------------------------------------------------- 退役
retired_rows = []
if ids and APPLY:
    with eng.begin() as c:
        for pid in ids:
            res = c.execute(
                text(
                    "update pois set status='inactive', updated_at=NOW() "
                    "where id=:id and status='active'"
                ),
                {"id": pid},
            )
            if res.rowcount != 1:
                print(f"!! rowcount={res.rowcount} for {pid}")
            retired_rows.append(pid)

# ---------------------------------------------------------------- 报告
now = datetime.now().isoformat(timespec="seconds")
md = []
md.append(f"# 错针批量退役处置单（2026-11-07，{'已执行' if APPLY else '干跑清单'}）\n")
md.append(
    "> 承接 wrongpin_scan_20261107.md（tier1 131 对）。自动退役从紧口径："
    "仅事故形态（ct 形态∧tier1∧同类别∧无B区块旗∧无类别差∧无分支标记"
    "∧无重复针污染∧B针入同城框）。其余归档人工复核。退役=软删让位"
    "（status='inactive'），引擎自动改用同实体高优 B 行。快照表 "
    f"{BAK_TABLE} + CSV {OUT_CSV.name}。\n"
)
md.append(f"\n处置时刻 {now}；自动退役 {len(retired_rows)} 行，"
          f"人工复核 {len(manual)} 对，跳过 {len(skipped)} 对。\n")

md.append("\n## 一、自动退役（已执行）\n\n")
md.append("| 城市 | A 名 | A source_poi_id | B 名（接位） | B source | 距离km |\n"
          "|---|---|---|---|---|---|\n")
for p, _ in retire:
    a, b = p["a"], p["b"]
    md.append(
        f"| {p['city']} | {a['name']} | `{a['spid']}` | {b['name']} "
        f"| {b['source']} | {p['dist_m']/1000:.2f} |\n"
    )

md.append("\n### 回滚语句（逐行）\n\n```sql\n")
for pid in retired_rows:
    md.append(
        f"UPDATE pois SET status='active', updated_at=NOW() "
        f"WHERE id='{pid}' AND NOT EXISTS (SELECT 1 FROM {BAK_TABLE} "
        f"b WHERE b.id='{pid}' AND b.status<>'active');\n"
    )
md.append("```\n")

md.append("\n## 二、人工复核清单（未动库）\n\n")
md.append("| 处置 | 城市 | A 名 | A spid | B 名 | 距离km | 原因 |\n"
          "|---|---|---|---|---|---|---|\n")
for p, why in manual:
    a, b = p["a"], p["b"]
    md.append(
        f"| manual | {p['city']} | {a['name']} | `{a['spid']}` "
        f"| {b['name']} | {p['dist_m']/1000:.2f} | {why} |\n"
    )
for p, why in skipped:
    a, b = p["a"], p["b"]
    md.append(
        f"| skip | {p['city']} | {a['name']} | `{a['spid']}` "
        f"| {b['name']} | {p['dist_m']/1000:.2f} | {why} |\n"
    )

md.append(
    "\n## 三、人工复核操作指引\n\n"
    "1. 逐对看 A.address 是否落在错误街道（事故形态地址会暴露错针，"
    "如武侯祠案锦悦西路）。\n"
    "2. 确认错针后两选一：针拷贝（UPDATE A.location=B.location, "
    "wgs84_location=B.wgs84_location, address=B.address）或软删让位"
    "（status='inactive'）。重复针污染对先修坐标再定退役。\n"
    "3. 执行前单行 dump A/B 全字段；回滚查快照表。\n"
)

with io.open(OUT_MD, "w", encoding="utf-8", newline="\n") as f:
    f.write("".join(md))

print("md written:", OUT_MD)
print("csv written:", OUT_CSV if ids else "(none)")
print("== RETIRED ==")
for p, _ in retire:
    a, b = p["a"], p["b"]
    print(f"  {p['city']:6s} {a['name']} <- {b['name']} ({p['dist_m']/1000:.2f}km)")
