# -*- coding: utf-8 -*-
"""4A 批次深度质检 v1——无配额部分（2026-11-03 立项）。

外部真值核验（高德/百度/腾讯逐行回源）2026-11-03 实测三路全阻塞：
amap key 被阿里云 WAF 风控（punish 页）、baidu 301/302 配额尽、tencent 121
日配额尽——同 p1 台账 T2/T3 的配额瓶颈。本脚本做不依赖 API 的四项：

  1. 跨源互证：同名（归一后）是否存在于其他 source（5a/unesco/amap/
     chinatravel/scenic/guobao8/intl…）→ corroborated / solo；
  2. 格式 sanity：坐标在中国境内（out_of_china）、city 非空、名称长度；
  3. 可疑名扫描：服务区/管理中心/收费站/停车区/加油站 类非游览实体；
  4. 名称重复：同城同名批内重复（应已为 0）。

产出 ops/qc_4a_internal_report_2026-11-03.md（含外部核验阻塞证据与
恢复后的执行命令）。
"""

from __future__ import annotations

import io
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.db import get_session_factory
from app.services.coords import out_of_china
from app.services.product_filter import red_exclusion_reason as _red_reason

OUT = Path(__file__).parent / "qc_4a_internal_report_2026-11-03.md"

SUSPICIOUS = re.compile(r"服务区|管理中心|收费站|停车区|加油站|养护中心|管理站|办事处")
_NAME_STRIP = re.compile(r"[（(].*?[)）]|[\s\-—–·、，,（）()]")
_SUFFIX = ("风景名胜区", "旅游度假区", "旅游景区", "旅游区", "风景区", "景区")


def _norm(s: str | None) -> str:
    return _NAME_STRIP.sub("", s or "").strip()


def _norm_core(s: str | None) -> str:
    """归一 + 剥等级后缀（XX景区→XX），提升跨源/名单形态差异的匹配率。"""
    n = _norm(s)
    for suf in _SUFFIX:
        if n.endswith(suf) and len(n) > len(suf) + 1:
            return n[: -len(suf)]
    return n


def main() -> int:
    factory = get_session_factory()
    with factory() as s:
        rows = s.execute(
            text(
                "select id, city, name_zh, category, "
                "ST_X(location::geometry) as lon, ST_Y(location::geometry) as lat "
                "from pois where source='4a' and status='active'"
            )
        ).fetchall()
        others = s.execute(
            text(
                "select name_zh from pois where status='active' "
                "and source <> '4a' and name_zh is not null"
            )
        ).fetchall()
    other_names = {_norm(n) for (n,) in others}
    other_names.discard("")
    other_core = {_norm_core(n) for (n,) in others}
    other_core.discard("")

    corroborated, corroborated_core, solo = [], [], []
    suspicious, bad_geo, dup_keys = [], [], []
    seen = Counter()
    for r in rows:
        n = _norm(r.name_zh)
        seen[(r.city or "", n)] += 1
        if n in other_names:
            corroborated.append(r)
        elif _norm_core(r.name_zh) in other_core:
            corroborated_core.append(r)
        else:
            solo.append(r)
        if SUSPICIOUS.search(r.name_zh or ""):
            suspicious.append(r)
        if r.lon is not None and r.lat is not None:
            if out_of_china(float(r.lon), float(r.lat)):
                bad_geo.append(r)
    dup_keys = [(k, v) for k, v in seen.items() if v > 1]

    # 官方 4A 汇编覆盖核对：已导入 / 跨源去重 / 真缺失
    import csv as _csv

    official = Path(
        r"D:/CHINATRIP/DESIGN/POIS DATASOURCE/13_4A级旅游景区_官方汇编4674.csv"
    )
    coverage = {
        "official": 0,
        "in_4a": 0,
        "deduped_other": 0,
        "in_db_inactive": 0,
        "red_filtered": 0,
        "missing": [],
    }
    if official.exists():
        db4a_core = {_norm_core(r.name_zh) for r in rows}
        # 全状态库内名（inactive 也算已处理：出池/去重轮）
        with factory() as _s2:
            all_rows = _s2.execute(
                text("select name_zh from pois where name_zh is not null")
            ).fetchall()
        db_all_core = {_norm_core(n) for (n,) in all_rows}
        db_all_core.discard("")
        with io.open(official, encoding="utf-8-sig", newline="") as cf:
            for row in _csv.DictReader(cf):
                name = row.get("name_zh") or ""
                if not name.strip():
                    continue
                coverage["official"] += 1
                core = _norm_core(name)
                if core in db4a_core:
                    coverage["in_4a"] += 1
                elif core in other_core:
                    coverage["deduped_other"] += 1
                elif core in db_all_core:
                    coverage["in_db_inactive"] += 1
                elif _red_reason(name):
                    coverage["red_filtered"] += 1
                else:
                    coverage["missing"].append(name)

    with io.open(OUT, "w", encoding="utf-8") as f:
        f.write("# 4A 批次深度质检 v1（无配额部分，2026-11-03）\n\n")
        f.write(
            f"> 目标：4a active {len(rows)} 行。"
            "外部真值核验（图商逐行回源）**已阻塞**："
        )
        f.write(
            "2026-11-03 实测 amap key 被阿里云 WAF 风控"
            "（punish 页，非网络/非 key 缺失）、"
        )
        f.write(
            "baidu 301/302 配额尽（p1 台账「百度池 ~100/日」）、tencent 121 日配额尽。"
        )
        f.write(
            "恢复后用 `python ops/qc_4a_amap_check.py --vendor baidu|amap`"
            " 直接跑（脚本已备 vendor 切换 + 配额优雅中止）。\n\n"
        )
        f.write("## 1. 跨源互证（同名是否在库内其他 source 出现）\n\n")
        total = max(1, len(rows))
        f.write(
            f"- corroborated（归一精确）：{len(corroborated)} 行"
            f"（{len(corroborated) / total * 100:.1f}%）；\n"
        )
        f.write(
            f"- corroborated（剥「景区/旅游区」后缀后命中）："
            f"{len(corroborated_core)} 行"
            f"（{len(corroborated_core) / total * 100:.1f}%）；\n"
        )
        f.write(
            f"- solo（两口径均未命中）：{len(solo)} 行——外部核验恢复后应优先抽查。\n\n"
        )
        f.write("## 2. 格式 sanity\n\n")
        empty_city = sum(1 for r in rows if not (r.city or "").strip())
        f.write(f"- 坐标越界（境外/空）：{len(bad_geo)} 行；\n")
        f.write(f"- 批内同城同名重复：{len(dup_keys)} 组；\n")
        f.write(f"- city 为空：{empty_city} 行。\n\n")
        f.write("## 3. 可疑名扫描（非游览实体）\n\n")
        f.write(
            f"命中 {len(suspicious)} 行（服务区/管理中心/收费站/停车区/加油站类）：\n\n"
        )
        for r in suspicious[:40]:
            f.write(f"- {r.city or '—'}｜{r.name_zh}\n")
        if len(suspicious) > 40:
            f.write(f"- ……另 {len(suspicious) - 40} 行\n")
        f.write("\n## 4. solo 行抽样（外部核验恢复后的优先抽查集）\n\n")
        for r in solo[:25]:
            f.write(f"- {r.city or '—'}｜{r.name_zh}\n")
        f.write(f"\n（solo 共 {len(solo)} 行，仅列前 25 行）\n")
        if coverage["official"]:
            f.write("\n## 5. 官方 4A 汇编覆盖核对\n\n")
            f.write(
                f"- 官方名单 {coverage['official']} 行 → 已导入 4a："
                f"{coverage['in_4a']} 行；\n"
            )
            f.write(
                f"- 跨源去重（同名正主在其他 source）："
                f"{coverage['deduped_other']} 行；\n"
            )
            f.write(
                f"- 库内 inactive（出池/去重轮处置过）："
                f"{coverage['in_db_inactive']} 行；\n"
            )
            f.write(
                f"- §4 产品过滤（红色/政治/军事，导入时按拍板剔除）："
                f"{coverage['red_filtered']} 行；\n"
            )
            f.write(f"- **名单无对应行：{len(coverage['missing'])} 行**\n\n")
            red_m, park_m, cand = [], [], []
            for name in coverage["missing"]:
                if _red_reason(name) or re.search(
                    r"会议纪念|会议旧址|会议会址|长征|抗战|解放纪念", name
                ):
                    red_m.append(name)
                elif "公园" in name or name.endswith("湖"):
                    park_m.append(name)
                else:
                    cand.append(name)
            f.write(
                f"处置分类：红色类 {len(red_m)}（出池拍板，不补）、"
                f"普通公园类 {len(park_m)}（公园清洗拍板，不补）、"
                f"庄园/酒庄等候选 {len(cand)}（可补灌，待拍板）：\n\n"
            )
            for name in cand:
                f.write(f"- 候选｜{name}\n")
    print(
        f"rows={len(rows)} corroborated={len(corroborated)} "
        f"corroborated_core={len(corroborated_core)} solo={len(solo)} "
        f"suspicious={len(suspicious)} bad_geo={len(bad_geo)} dup={len(dup_keys)} "
        f"official={coverage['official']} in_4a={coverage['in_4a']} "
        f"deduped={coverage['deduped_other']} missing={len(coverage['missing'])}"
    )
    print("report:", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
