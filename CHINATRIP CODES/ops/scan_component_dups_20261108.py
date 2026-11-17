# -*- coding: utf-8 -*-
"""组件行重复退役引擎·全库扫（2026-11-08，永宁门案泛化，用户拍板）。

形态：弱源组件行 A（城门/广场/被并名件）与权威组合行 B（5A/unesco 的
景区/·并名行，如 城墙·碑林历史文化景区、大雁塔大唐芙蓉园景区）同城
近距、同类目——两行同池入选=同一实体排两天（西安 11-08 案实录）。

口径（从紧，承 11-07 错针批纪律：自动档只收用户已拍板形态）：
- B：active ∧ 权威源（5a_/unesco）∧ 名含 景区/旅游区/风景名胜 或「·」。
- A：active ∧ 同城 ∧ 同 category ∧ 弱源 ∧ 距 B ≤3km ∧ 无分馆/馆区类
  分支标记 ∧ 名 ≠ B 名。
- AUTO（自动退役）＝城门类：B 名含「城墙」∧ A 名以「门」结尾 ∧
  len(A 名)≤3（永宁门/安定门/中华门…同型；正阳门等独立地标本有
  景区级 B 缺失即不进档）。
- MANUAL（只归档不动库）＝名称包含类（A 名 ⊂ B 名）/ 广场类 / 其余
  近距对——11-06 四轮去重后残余，语义包含歧义大，宁缺勿滥。
- 每行退役前：快照表 pois_component_bak_20261108 + 全字段 CSV；
  UPDATE 带 status='active' 守卫。

用法：python ops/scan_component_dups_20261108.py [--apply]
回滚（逐行）：UPDATE pois SET status='active' WHERE id='<row id>';
"""

import csv
import io
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import bindparam, create_engine, text

sys.stdout.reconfigure(encoding="utf-8")

APPLY = "--apply" in sys.argv

HERE = Path(__file__).resolve().parent
DSN = "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"
BAK_TABLE = "pois_component_bak_20261108"
OUT_MD = HERE / "component_dup_scan_20261108.md"
OUT_CSV = HERE / "pois_retired_backup_2026-11-08_component_batch.csv"

COMBO_PAT = re.compile(r"景区|旅游区|风景名胜")
BRANCH_PAT = re.compile(r"分馆|馆区|展区|校区|新馆|东馆|西馆|南馆|北馆")
AUTH_PREFIXES = ("5a_", "unesco")
NEAR_KM = 3.0
WEAK_EXCLUDE_CATS = {"museum", "show", "entertainment", "food", "hotel"}


def hav_km(lon1, lat1, lon2, lat2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


eng = create_engine(DSN, connect_args={"connect_timeout": 3})
with eng.connect() as c:
    rows = c.execute(
        text(
            "select id, name_zh, source_poi_id, city, category, status, "
            "ST_X(location::geometry) as lon, ST_Y(location::geometry) as lat "
            "from pois where status='active' and location is not null "
            "and city is not null"
        )
    ).mappings().all()

by_city: dict[str, list[dict]] = {}
for r in rows:
    by_city.setdefault((r["city"] or "").strip(), []).append(dict(r))


def is_auth(spid: str | None) -> bool:
    return bool(spid) and str(spid).startswith(AUTH_PREFIXES)


def combo_eligible(r: dict) -> bool:
    nm = r["name_zh"] or ""
    return is_auth(r["source_poi_id"]) and (
        bool(COMBO_PAT.search(nm)) or "·" in nm
    )


pairs: list[dict] = []
for city, rs in by_city.items():
    combos = [r for r in rs if combo_eligible(r)]
    for a in rs:
        if a in combos or is_auth(a["source_poi_id"]):
            continue
        nm_a = a["name_zh"] or ""
        if not nm_a or BRANCH_PAT.search(nm_a):
            continue
        for b in combos:
            if a["name_zh"] == b["name_zh"] or (a["category"] or "") != (
                b["category"] or ""
            ):
                continue
            km = hav_km(a["lon"], a["lat"], b["lon"], b["lat"])
            if km > NEAR_KM:
                continue
            if "城墙" in (b["name_zh"] or "") and nm_a.endswith("门") and len(nm_a) <= 3:
                cls = "AUTO-城门"
            elif len(nm_a) >= 2 and nm_a in (b["name_zh"] or ""):
                cls = "MANUAL-名称包含"
            elif nm_a.endswith("广场"):
                cls = "MANUAL-广场"
            else:
                cls = "MANUAL-近距"
            pairs.append({"a": a, "b": b, "km": km, "cls": cls})

# 同 A 多 B：留最近一条（按类内最近）
best: dict[str, dict] = {}
for p in pairs:
    key = str(p["a"]["id"]) + "|" + p["cls"].split("-")[0]
    if key not in best or p["km"] < best[key]["km"]:
        best[key] = p
pairs = sorted(best.values(), key=lambda p: (p["cls"], p["a"]["city"] or "", p["km"]))

auto = [p for p in pairs if p["cls"].startswith("AUTO")]
manual = [p for p in pairs if not p["cls"].startswith("AUTO")]
print(
    f"scan: cities={len(by_city)} pairs={len(pairs)} "
    f"auto={len(auto)} manual={len(manual)} "
    f"({'APPLY' if APPLY else 'DRY-RUN'})"
)
for p in auto:
    print(f"  AUTO {p['a']['city']} {p['a']['name_zh']} <- {p['b']['name_zh']} "
          f"{p['km']:.2f}km")

# ---------------------------------------------------------------- 退役（仅 AUTO）
ids = [str(p["a"]["id"]) for p in auto]
if ids and APPLY:
    with eng.begin() as c:
        c.execute(
            text(f"create table if not exists {BAK_TABLE} as "
                 "select * from pois where false")
        )
        c.execute(
            text(
                f"insert into {BAK_TABLE} select * from pois where id in :ids "
                "and id not in (select id from " + BAK_TABLE + ")"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": ids},
        )
    with eng.connect() as c:
        snap = c.execute(
            text("select * from pois where id in :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        ).mappings().all()
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

# ---------------------------------------------------------------- 报告
now = datetime.now().isoformat(timespec="seconds")
md = [
    f"# 组件行重复退役引擎·全库扫描（2026-11-08，{'已执行' if APPLY else '干跑'}）\n",
    "> 永宁门案泛化：弱源组件行 vs 权威组合行（5a_/unesco ∧ 景区/·并名）"
    f"同城 ≤{NEAR_KM}km 同类目。AUTO 仅城门类（B 含城墙 ∧ A 名 ≤3 字以门结尾）；"
    "名称包含/广场/近距对全部人工复核（11-06 四轮去重后残余，语义歧义大）。"
    f"快照表 {BAK_TABLE}；回滚见文末。\n",
    f"\n扫描时刻 {now}；组合行候选对 {len(pairs)}，AUTO {len(auto)}，"
    f"MANUAL {len(manual)}。\n",
    "\n## 一、AUTO 已退役（城门类）\n\n"
    "| 城市 | A 名 | A 源 | B 组合行 | B 源 | km |\n|---|---|---|---|---|---|\n",
]
for p in auto:
    md.append(
        f"| {p['a']['city']} | {p['a']['name_zh']} | `{p['a']['source_poi_id']}` "
        f"| {p['b']['name_zh']} | `{p['b']['source_poi_id']}` | {p['km']:.2f} |\n"
    )
md.append("\n```sql\n")
for p in auto:
    md.append(
        f"UPDATE pois SET status='active', updated_at=NOW() "
        f"WHERE id='{p['a']['id']}';\n"
    )
md.append("```\n")
md.append(
    "\n## 二、人工复核（未动库）\n\n"
    "| 类 | 城市 | A 名 | A 源/类目 | B 组合行 | km |\n"
    "|---|---|---|---|---|---|\n"
)
for p in manual:
    md.append(
        f"| {p['cls']} | {p['a']['city']} | {p['a']['name_zh']} "
        f"| `{p['a']['source_poi_id']}`/{p['a']['category']} "
        f"| {p['b']['name_zh']} | {p['km']:.2f} |\n"
    )

with io.open(OUT_MD, "w", encoding="utf-8", newline="\n") as f:
    f.write("".join(md))
print("md written:", OUT_MD)
if ids and APPLY:
    print("csv written:", OUT_CSV)
