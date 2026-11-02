# -*- coding: utf-8 -*-
"""4A 批次（source='4a', 2026-11-02 并行会话入库 4,328 行）只读质检。

背景：台账 POIS_DATASOURCE.md §3.2 #10——该批超出「未审不进库」原闸，
需补一轮质检（2026-11-03 拍板派工）。纯 SQL/CSV 对账，不烧 GLM、不写库。

检查面：
  A. 对账——CSV 4674 行 vs 库 4,328 行，source_poi_id='4a_<csv行号>' 逐行
     对齐；缺行分桶（§4 红色词表命中=导入时剔除/其余=待核清单）
  B. §4 红色词表——在库 4,328 行 active 名称复扫（product_filter 正典词表）
  C. 去重——批内 (name_zh,city)/(name_zh)/source_poi_id 重复 + 跨源同名同城
  D. 分类 sanity——category 分布 vs 5a 基准、NULL 池、hotel 等异类
  E. 名称 sanity——空白/长度/括号/占位词/花字符
  F. 骨架纪律——hours/rating/ticket/intro 应为 NULL（名单导入只写骨架）
  G. 坐标——location NULL / 非法 geometry / 出中国_bounds
用法：
    .venv/Scripts/python ops/qa_4a_batch_2026-11-03.py
输出：stdout 摘要 + ops/qa_4a_report_2026-11-03.md（只写报告文件，不碰库）。
"""

from __future__ import annotations

import csv
import io
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.product_filter import red_exclusion_reason

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE, "..", "DESIGN", "POIS DATASOURCE",
                        "13_4A级旅游景区_官方汇编4674.csv")
REPORT = os.path.join(BASE, "ops", "qa_4a_report_2026-11-03.md")
DB = "postgresql+psycopg://chinatrip:chinatrip@localhost:5432/chinatrip"

CAP = 40  # 报告清单逐条上限


def cap_list(items, key=lambda x: x):
    return items[:CAP]


def city_norm(c: str | None) -> str:
    """城市口径归一：去尾部「市」（上海市↔上海、荆门市↔荆门）；州/地区保留。"""
    c = (c or "").strip()
    return c[:-1] if c.endswith("市") and len(c) > 2 else c


PURGE_BACKUP = os.path.join(BASE, "ops", "pois_inactive_purge_backup_2026-11-03.csv")
RED2_EXCLUDED = os.path.join(BASE, "ops", "red_tourism_excluded_round2_2026-11-03.csv")


def main() -> None:
    import psycopg
    conn = psycopg.connect("host=localhost port=5432 dbname=chinatrip "
                           "user=chinatrip password=chinatrip")
    cur = conn.cursor()

    # ── CSV 侧 ────────────────────────────────────────────────────────
    with io.open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        csv_rows = list(csv.DictReader(f))
    csv_by_no = {i + 1: r for i, r in enumerate(csv_rows)}
    # 批内重复（同省市同名）
    seen: Counter = Counter()
    for r in csv_rows:
        seen[(r["name_zh"].strip(), r["city"].strip())] += 1
    csv_dup = {k: v for k, v in seen.items() if v > 1}

    # ── 库侧 4a 全行 ──────────────────────────────────────────────────
    cur.execute("""
        SELECT id, source_poi_id, name_zh, city, category, status, tags,
               origin, tags_source, name_en,
               opening_hours, rating, ticket_price_min, intro,
               location IS NULL AS loc_null, name_aliases
        FROM pois WHERE source='4a' ORDER BY id
    """)
    cols = [d[0] for d in cur.description]
    db_rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    db_total = len(db_rows)

    # source_poi_id='4a_<n>' → CSV 行号对齐
    n_re = re.compile(r"^4a_(\d+)$")
    db_by_no: dict[int, dict] = {}
    id_bad = []
    for r in db_rows:
        m = n_re.match(r["source_poi_id"] or "")
        if m:
            db_by_no[int(m.group(1))] = r
        else:
            id_bad.append(r["source_poi_id"])
    aligned = set(db_by_no) & set(csv_by_no)
    name_mismatch = [n for n in sorted(aligned)
                     if db_by_no[n]["name_zh"] != csv_by_no[n]["name_zh"].strip()]

    missing_nos = sorted(set(csv_by_no) - set(db_by_no))
    miss_red, miss_other = [], []
    for n in missing_nos:
        r = csv_by_no[n]
        reason = red_exclusion_reason(r["name_zh"])
        (miss_red if reason else miss_other).append(
            (n, r["name_zh"], r["city"], reason or ""))
    extra_nos = sorted(set(db_by_no) - set(csv_by_no))

    # 非红色缺行复核：是否已有他源行在库（去重闸跳过=合规；真缺=待核）
    # 今日 inactive 硬清备份——曾在库、红色/公园清洗软删、今日硬清的行也在其中
    purge_names: set[str] = set()
    if os.path.exists(PURGE_BACKUP):
        with io.open(PURGE_BACKUP, encoding="utf-8-sig", newline="") as f:
            purge_names = {(r.get("name_zh") or "").strip() for r in csv.DictReader(f)}
    red2_names: set[str] = set()
    if os.path.exists(RED2_EXCLUDED):
        with io.open(RED2_EXCLUDED, encoding="utf-8-sig", newline="") as f:
            red2_names = {(r.get("name_zh") or "").strip() for r in csv.DictReader(f)}
    miss_deduped, miss_purged, miss_unexplained = [], [], []
    for n, name, city, _ in miss_other:
        cur.execute("""
            SELECT source, status FROM pois
            WHERE name_zh = %s AND city IN (%s, %s) LIMIT 5
        """, (name, city.strip(), city_norm(city)))
        hits = cur.fetchall()
        if hits:
            miss_deduped.append((n, name, city,
                                 "、" .join(f"{s}({st})" for s, st in hits)))
        elif name.strip() in purge_names:
            tag = "红色出池" if name.strip() in red2_names else "其他软删(公园清洗等)"
            miss_purged.append((n, name, city, f"今日硬清备份命中[{tag}]"))
        else:
            cur.execute("SELECT source, status FROM pois WHERE name_zh = %s LIMIT 5",
                        (name,))
            hits2 = cur.fetchall()
            if hits2:
                miss_deduped.append((n, name, city,
                                     "同名(城写法异):" + "、".join(
                                         f"{s}({st})" for s, st in hits2)))
            else:
                miss_unexplained.append((n, name, city))

    # ── B. §4 复扫在座行 ─────────────────────────────────────────────
    red_hits = []
    for r in db_rows:
        reason = red_exclusion_reason(r["name_zh"])
        if reason:
            red_hits.append((r["id"], r["source_poi_id"], r["name_zh"],
                             r["city"], r["category"], reason))

    # ── C. 去重 ──────────────────────────────────────────────────────
    c_nc: Counter = Counter()
    c_n: Counter = Counter()
    c_id: Counter = Counter()
    for r in db_rows:
        c_nc[(r["name_zh"], r["city"])] += 1
        c_n[r["name_zh"]] += 1
        c_id[r["source_poi_id"]] += 1
    dup_nc = {k: v for k, v in c_nc.items() if v > 1}
    dup_n = {k: v for k, v in c_n.items() if v > 1}
    dup_id = {k: v for k, v in c_id.items() if v > 1}
    # 跨源同名同城（全部 source，含本批对照；城市口径归一后比对）
    cur.execute("""
        SELECT name_zh, city, source, status, count(*) 
        FROM pois
        WHERE name_zh IN (
            SELECT name_zh FROM pois WHERE source='4a'
        ) AND source <> '4a'
        GROUP BY name_zh, city, source, status
    """)
    cross = {}
    db4_cities: dict[str, set[str]] = {}
    for r in db_rows:
        db4_cities.setdefault(r["name_zh"], set()).add(city_norm(r["city"]))
    for name, city, src, st, n in cur.fetchall():
        if city_norm(city) in db4_cities.get(name, set()):
            cross.setdefault((name, city), []).append((src, st, n))

    # ── D. 分类 ──────────────────────────────────────────────────────
    cat_db: Counter = Counter(r["category"] or "（NULL）" for r in db_rows)
    cur.execute("""SELECT category, count(*) FROM pois WHERE source='5a'
                   GROUP BY category ORDER BY 2 DESC""")
    cat_5a = cur.fetchall()
    cur.execute("""SELECT category, count(*) FROM pois WHERE source='4a'
                   AND category='nature' AND (name_zh LIKE '%博物馆%'
                   OR name_zh LIKE '%纪念馆%' OR name_zh LIKE '%乐园%'
                   OR name_zh LIKE '%庄园%' OR name_zh LIKE '%度假区%')
                   GROUP BY 1""")
    nat_mis = cur.fetchall()
    null_cat = [(r["id"], r["source_poi_id"], r["name_zh"], r["city"])
                for r in db_rows if not r["category"]]
    odd_cat = [(r["id"], r["name_zh"], r["city"], r["category"])
               for r in db_rows if r["category"] in ("hotel", "restaurant",
                                                     "bar", "shop", "other")]

    # ── E. 名称 sanity ───────────────────────────────────────────────
    bad_ws = [r for r in db_rows if r["name_zh"] != (r["name_zh"] or "").strip()]
    bad_len = [r for r in db_rows
               if not r["name_zh"] or len(r["name_zh"]) < 2 or len(r["name_zh"]) > 40]
    bad_bracket = [r for r in db_rows
                   if (r["name_zh"] or "").count("（") != (r["name_zh"] or "").count("）")
                   or (r["name_zh"] or "").count("(") != (r["name_zh"] or "").count(")")]
    placeholder_re = re.compile(r"待定|测试|示例|unknown|XXX|暂无|占位", re.I)
    bad_ph = [r for r in db_rows if placeholder_re.search(r["name_zh"] or "")]
    # 叠词尾：名称尾部同一词连写两遍（如「温泉温泉」）
    bad_dupword = []
    for r in db_rows:
        n = r["name_zh"] or ""
        m = re.search(r"^(.*)(景区|旅游区|公园|古镇|温泉|度假区)(.*)$", n)
        if m and n.count(m.group(2)) >= 2 and m.group(2) * 2 in n:
            bad_dupword.append(r)

    # ── F. 骨架纪律 ──────────────────────────────────────────────────
    filled = {
        "opening_hours": sum(1 for r in db_rows if r["opening_hours"]),
        "rating": sum(1 for r in db_rows if r["rating"] is not None),
        "ticket_price_min": sum(1 for r in db_rows if r["ticket_price_min"] is not None),
        "intro": sum(1 for r in db_rows if r["intro"]),
        "name_en": sum(1 for r in db_rows if r["name_en"]),
    }
    # 非空字段来源归属（名单导入只写骨架；非空=回源/enrich 链后续补的，看 source 列）
    src_rows = {}
    for col in ("hours_source", "rating_source", "ticket_source", "intro_source"):
        cur.execute(f"""SELECT coalesce({col},'（NULL）'), count(*) FROM pois
                        WHERE source='4a' GROUP BY 1 ORDER BY 2 DESC""")
        src_rows[col] = cur.fetchall()

    # ── G. 坐标 ──────────────────────────────────────────────────────
    cur.execute("""SELECT count(*) FROM pois WHERE source='4a' AND location IS NOT NULL""")
    loc_filled = cur.fetchone()[0]
    cur.execute("""SELECT count(*) FROM pois WHERE source='4a' AND location IS NOT NULL
                   AND NOT ST_IsValid(location::geometry)""")
    loc_invalid = cur.fetchone()[0]
    cur.execute("""SELECT id, name_zh, city, ST_X(location::geometry), ST_Y(location::geometry)
                   FROM pois WHERE source='4a' AND location IS NOT NULL
                   AND (ST_Y(location::geometry) NOT BETWEEN 15 AND 55
                        OR ST_X(location::geometry) NOT BETWEEN 73 AND 136) LIMIT 60""")
    loc_out = cur.fetchall()
    # 无坐标行分类分布（是否集中在 NULL 分类池）
    cur.execute("""SELECT coalesce(category,'（NULL）'), count(*) FROM pois
                   WHERE source='4a' AND location IS NULL
                   GROUP BY 1 ORDER BY 2 DESC""")
    locnull_cat = cur.fetchall()

    # ── 报告 ─────────────────────────────────────────────────────────
    L: list[str] = []
    a = L.append
    a("# 4A 批次质检报告（source='4a'，2026-11-03）")
    a("")
    a("> 只读质检：CSV 对账 + §4 词表复扫 + 去重 + 分类/名称 sanity + 骨架/坐标纪律。")
    a("> 不烧 GLM、不写库。工具：`ops/qa_4a_batch_2026-11-03.py`。")
    a("")
    a("## 总览")
    a("")
    a(f"- CSV 行数：{len(csv_rows)}（13 号审阅包口径 4,674）")
    status_cnt = Counter(r["status"] for r in db_rows)
    a(f"- 库内 source='4a' 行数：{db_total}（status: " +
      "、".join(f"{k}×{v}" for k, v in status_cnt.most_common()) + "）")
    a(f"- source_poi_id 规则 `4a_<csv行号>` 对齐：对上 {len(aligned)}，"
      f"行号不在 CSV 范围 {len(extra_nos)}，非 `4a_<n>` 格式 {len(id_bad)}，"
      f"行号对齐但名称不一致 {len(name_mismatch)}")
    gap = len(csv_rows) - db_total
    a(f"- 差额 {gap} = 导入时剔除/跳过行数（下方分桶）")
    a("")

    a("## A. 对账分桶（缺的 346 行去哪了）")
    a("")
    a(f"- §4 红色词表命中（导入时正闸剔除，可回灌）：**{len(miss_red)}**")
    a(f"- 非红色缺行：**{len(miss_other)}** —— 他源行在库（去重闸跳过，合规）："
      f"**{len(miss_deduped)}**；今日硬清备份命中（曾入库→红色/公园清洗软删→11-03 硬清，"
      f"备份可回灌）：**{len(miss_purged)}**；全库查无同名（真缺，需核）："
      f"**{len(miss_unexplained)}**")
    a("")
    if miss_purged:
        a("今日硬清备份命中（行号 | 名称 | 城市 | 归因）：")
        a("")
        a("```")
        for n, name, city, tag in cap_list(miss_purged):
            a(f"{n} | {name} | {city} | {tag}")
        if len(miss_purged) > CAP:
            a(f"…共 {len(miss_purged)} 行")
        a("```")
        a("")
    if miss_unexplained:
        a("真缺清单（行号 | 名称 | 城市）——库内无任何同名行，导入闸漏网或改名：")
        a("")
        a("```")
        for n, name, city in cap_list(miss_unexplained, key=lambda x: x[0]):
            a(f"{n} | {name} | {city}")
        if len(miss_unexplained) > CAP:
            a(f"…共 {len(miss_unexplained)} 行")
        a("```")
        a("")
    if miss_deduped:
        a("去重闸跳过（抽样，行号 | 名称 | 城市 | 他源命中）：")
        a("")
        a("```")
        for n, name, city, src in cap_list(miss_deduped):
            a(f"{n} | {name} | {city} | {src}")
        if len(miss_deduped) > CAP:
            a(f"…共 {len(miss_deduped)} 行")
        a("```")
        a("")
    if miss_red:
        a("红色命中缺行（抽样）：")
        a("")
        a("```")
        for n, name, city, reason in cap_list(miss_red):
            a(f"{n} | {name} | {city} | {reason}")
        a("```")
        a("")

    a("## B. §4 红色词表复扫（在库 4,328 行）")
    a("")
    a(f"- 命中：**{len(red_hits)}**（预期 0——命中应已导入时剔除；hotel 类路名误报按拍板保留）")
    a("")
    if red_hits:
        a("| poi_id | source_poi_id | 名称 | 城市 | category | 理由 |")
        a("|---|---|---|---|---|---|")
        for hid, spid, name, city, cat, reason in cap_list(red_hits):
            a(f"| {hid} | {spid} | {name} | {city} | {cat} | {reason} |")
        a("")

    a("## C. 去重")
    a("")
    a(f"- 批内 (name_zh,city) 重复：**{len(dup_nc)}** 组")
    a(f"- 批内同名（跨市，可能合法·同名景区）：{len(dup_n)} 组")
    a(f"- source_poi_id 重复：**{len(dup_id)}**")
    a(f"- CSV 批内 (name,city) 重复：{len(csv_dup)} 组")
    a(f"- 跨源同名同城（4a 行与他源同 POI 并行在库）：**{len(cross)}** 组")
    a("")
    if dup_nc:
        a("批内 (name,city) 重复明细：")
        a("")
        a("```")
        for (name, city), v in list(dup_nc.items())[:CAP]:
            a(f"{name} | {city} ×{v}")
        a("```")
        a("")
    if cross:
        top = sorted(cross.items(), key=lambda kv: -sum(x[2] for x in kv[1]))
        a("跨源撞名 TOP（名称 | 城市 | 他源分布）：")
        a("")
        a("```")
        for (name, city), srcs in cap_list(top, key=lambda kv: -sum(x[2] for x in kv[1])):
            src_s = "、".join(f"{s}({st},{n})" for s, st, n in srcs)
            a(f"{name} | {city} | {src_s}")
        a("```")
        a("")

    a("## D. 分类 sanity")
    a("")
    a("| category | 4a 行数 | 5a 基准 |")
    a("|---|---|---|")
    cat5 = dict(cat_5a)
    all_cats = set(cat_db) | {k or "（NULL）" for k, _ in cat_5a}
    for k in sorted(all_cats, key=lambda k: -cat_db.get(k, 0)):
        a(f"| {k} | {cat_db.get(k, 0)} | {cat5.get(None if k == '（NULL）' else k, 0)} |")
    a("")
    a("- NULL 分类：{0} 行（backfill 链已有 NULL 分类守卫，属待补）".format(len(null_cat)))
    a(f"- 异类（hotel/restaurant/bar/shop/other）：{len(odd_cat)} 行")
    a(f"- nature 桶疑似错分（博物馆/纪念馆/乐园/庄园/度假区字样）：{nat_mis[0][1] if nat_mis else 0} 行"
      "——5a 基准为 attraction 兜底，4a 批 nature 兜底属口径分叉，建议后续 enrich 重分类（本轮不动库）")
    a("")
    if odd_cat:
        a("| poi_id | 名称 | 城市 | category |")
        a("|---|---|---|---|")
        for pid, name, city, cat in odd_cat:
            a(f"| {pid} | {name} | {city} | {cat} |")
        a("")

    a("## E. 名称 sanity")
    a("")
    a(f"- 前后空白：{len(bad_ws)}；长度越界(<2/>40)：{len(bad_len)}；"
      f"括号不平衡：{len(bad_bracket)}；占位词：{len(bad_ph)}；叠词尾：{len(bad_dupword)}")
    a("")
    for label, items in (("前后空白", bad_ws), ("长度越界", bad_len),
                         ("括号不平衡", bad_bracket), ("占位词", bad_ph),
                         ("叠词尾", bad_dupword)):
        if items:
            a(f"{label}（抽样）：")
            a("")
            a("```")
            for r in cap_list(items):
                a(f"{r['id']} | {r['name_zh']} | {r['city']}")
            a("```")
            a("")

    a("## F. 骨架纪律（名单导入只写骨架，时间敏感字段应为 NULL）")
    a("")
    a("| 字段 | 非空行数 |")
    a("|---|---|")
    for k, v in filled.items():
        a(f"| {k} | {v} |")
    a("")
    a("非空字段来源归属（区分名单导入 vs 回源链后续补齐）：")
    a("")
    for col, dist in src_rows.items():
        a(f"- {col}: " + "、".join(f"{k}×{v}" for k, v in dist))
    a("")
    # 名称有问题的行，CSV 源头是否同样脏（源数据 bug vs 导入 bug）
    offenders = bad_bracket + bad_dupword
    a("名称问题行 CSV 源头核对：")
    a("")
    a("")
    csv_names = {r["name_zh"].strip(): i + 1 for i, r in enumerate(csv_rows)}
    a("| poi_id | 库内名称 | 城市 | CSV 同名行 |")
    a("|---|---|---|---|")
    for r in offenders:
        src_no = csv_names.get((r["name_zh"] or "").strip())
        a(f"| {r['id']} | {r['name_zh']} | {r['city']} | "
          f"{'存在(第' + str(src_no) + '行,源数据同脏)' if src_no else '不存在(导入侧产生)'} |")
    a("")

    a("## G. 坐标")
    a("")
    a(f"- location 已填：{loc_filled}（回源链可继续补）")
    a(f"- 非法 geometry：**{loc_invalid}**")
    a(f"- 出中国范围（lon 73-136 / lat 15-55 之外）：{len(loc_out)}")
    a("")
    if loc_out:
        a("| poi_id | 名称 | 城市 | lon | lat |")
        a("|---|---|---|---|---|")
        for pid, name, city, x, y in loc_out[:CAP]:
            a(f"| {pid} | {name} | {city} | {x:.4f} | {y:.4f} |")
        a("")
    a("无坐标行分类分布：")
    a("")
    a("```")
    for k, v in locnull_cat:
        a(f"{k}: {v}")
    a("```")
    a("")

    a("## 结论")
    a("")
    red_ok = len(red_hits) == 0 or all("hotel" in (h[4] or "") for h in red_hits)
    a(f"- 对账：差额 {gap} 行 = §4 剔除 {len(miss_red)} + 他源去重 {len(miss_deduped)}"
      f" + 硬清备份命中 {len(miss_purged)} + 真缺 {len(miss_unexplained)}"
      f"（{'✅ 全部有解释' if len(miss_red) + len(miss_deduped) + len(miss_purged) + len(miss_unexplained) == gap and not extra_nos and not name_mismatch else '⚠️ 有未解释项'}）")
    a(f"- §4 复扫：{'✅ 干净' if red_ok else '⚠️ 有命中需裁'}（{len(red_hits)} 行）")
    a(f"- 去重：批内 (name,city) 重复 {len(dup_nc)} / id 重复 {len(dup_id)} / "
      f"跨源撞名 {len(cross)}")
    a(f"- 分类：NULL {cat_db.get('（NULL）', 0)}，异类 {len(odd_cat)}")
    a(f"- 名称：空白 {len(bad_ws)} / 长度 {len(bad_len)} / 括号 {len(bad_bracket)} / "
      f"占位 {len(bad_ph)} / 叠词 {len(bad_dupword)}")
    a(f"- 骨架：hours {filled['opening_hours']} / rating {filled['rating']} / "
      f"ticket {filled['ticket_price_min']} / intro {filled['intro']} 非空")
    a(f"- 坐标：非法 {loc_invalid} / 出界 {len(loc_out)}")

    with io.open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    print("\n".join(L))
    print(f"\n[written] {REPORT}")
    conn.close()


if __name__ == "__main__":
    main()
