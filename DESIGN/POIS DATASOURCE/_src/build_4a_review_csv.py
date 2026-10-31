"""生成 13_4A级旅游景区 审阅包 CSV（2026-10-28）。

输入（DESIGN/4a_3a_dataset/，上游 dev/build_official_4a.py 产物）：
  4a-official.json         官方名录汇编 4,612 条（省级文旅厅/政府公告）
  4a-updates-official.json 正式认定增补 67 条（湘39/陕13/晋11/闽4，含 2026 新批）
  rating-corrections.json  正式取消/降级 15 条（皖7/粤5/京2/辽1）
  4a-audit.json            suspected_5a_upgrades 6 条（needs_identity_review）
  ../../POIS DATASOURCE/02_5A级旅游景区_358.csv  现行 5A 名单（跨级查重参照）

变换：
  1) official + updates 合并（(province, norm(name)) 判重，updates 优先；
     aliases 并入 alias_zh）；两表实测零重叠，判重为兜底。
  2) 剔除 corrections 命中行（removed=取消 4A；downgraded=现 3A，均非现行 4A），
     全清单移交 README.md 留痕。
  3) 与 02_5A 名单跨级查重（同省 + 变体阶梯：norm/去行政前缀/去景区类后缀/
     双向包含≥3字）→ 不剔除（audit 明示「仅候选，未据此合并」），remark 标注。
  4) 安徽/江苏为 partial_provinces（省级名录仅部分覆盖）→ remark 标注。

输出：../13_4A级旅游景区_<行数>.csv
列：name_zh,province,city,grade,batch,alias_zh,source_url,remark
（前 7 列 = POIS_DATASOURCE.md §5 统一 schema；batch=名录/认定日期 as_of；
remark 为审阅标注列，导入时忽略。）

用法：python build_4a_review_csv.py
"""

from __future__ import annotations

import csv
import json
import os
import re
import unicodedata

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.normpath(os.path.join(_HERE, "..", "..", "4a_3a_dataset"))
_OUT = os.path.normpath(os.path.join(_HERE, ".."))

_NAME_STRIP = re.compile(r"[\s（）()\-－—–·、,，。.：:；;「」『』【】\[\]\"'']+")
_ADMIN_PREFIX = re.compile(r"^.+?(?:省|市|自治区|自治州|自治县|盟|地区|林区|县|旗)")
_SCENIC_SUFFIXES = ("风景名胜区", "旅游景区", "旅游区", "风景区", "景区")


def norm(name: str | None) -> str:
    if not name:
        return ""
    return _NAME_STRIP.sub("", unicodedata.normalize("NFKC", str(name))).lower()


def name_variants(name_zh: str) -> set[str]:
    full = norm(name_zh)
    out = {full}
    stripped = {full}
    m = _ADMIN_PREFIX.match(full)
    if m and 2 < len(m.group(0)) <= 12:
        stripped.add(full[len(m.group(0)) :])
    for base in stripped:
        for suf in _SCENIC_SUFFIXES:
            if base.endswith(suf) and len(base) > len(suf) + 1:
                out.add(base[: -len(suf)])
    return {v for v in out if len(v) >= 2}


def matches_5a(name: str, province: str, index5a: dict) -> str | None:
    """同省 5A 命中 → 返回命中方式（exact/contains）；未命中 None。"""
    keys = name_variants(name) or {norm(name)}
    for key in keys:
        if key in index5a.get(province, set()):
            return "exact"
    for key in keys:
        if len(key) < 3:
            continue
        for db_key in index5a.get(province, set()):
            if len(db_key) >= 3 and (db_key in key or key in db_key):
                return "contains"
    return None


def main() -> int:
    official = json.load(open(os.path.join(_SRC, "4a-official.json"), encoding="utf-8"))
    updates = json.load(
        open(os.path.join(_SRC, "4a-updates-official.json"), encoding="utf-8")
    )
    corrections = json.load(
        open(os.path.join(_SRC, "rating-corrections.json"), encoding="utf-8")
    )
    audit = json.load(open(os.path.join(_SRC, "4a-audit.json"), encoding="utf-8"))

    # 现行 5A 名单 → {省全称: {norm 名}}（与 4A 表同用省全称口径）
    index5a: dict[str, set[str]] = {}
    p5a = os.path.join(_OUT, "02_5A级旅游景区_358.csv")
    with open(p5a, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            index5a.setdefault(r["province"], set()).add(norm(r["name_zh"]))

    # corrections 命中键（含别名）
    corrected: set[tuple[str, str]] = set()
    for c in corrections["items"]:
        corrected.add((c["province"], norm(c["name"])))
        for a in c.get("aliases", []):
            corrected.add((c["province"], norm(a)))

    partial = set(audit.get("partial_provinces") or [])

    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    stats = {
        "official": len(official["items"]),
        "updates": len(updates["items"]),
        "merged_dup": 0,
        "corrected_out": 0,
        "flag_5a": 0,
        "flag_partial": 0,
    }

    def emit(item: dict, aliases: list[str], from_update: bool) -> None:
        name = (item.get("name") or "").strip()
        province = (item.get("province") or "").strip()
        if not name or not province:
            stats["merged_dup"] += 1  # 缺关键列，弃
            return
        key = (province, norm(name))
        alias_keys = {(province, norm(a)) for a in aliases if a.strip()}
        if key in seen or (alias_keys & seen):
            stats["merged_dup"] += 1
            return
        seen.add(key)
        seen.update(alias_keys)
        if key in corrected or any(k in corrected for k in alias_keys):
            stats["corrected_out"] += 1
            return
        remarks = []
        if matches_5a(name, province, index5a):
            remarks.append("疑似已升5A（与02表同名近名，需人工核）")
            stats["flag_5a"] += 1
        if province in partial:
            remarks.append("所在省名录仅部分覆盖")
            stats["flag_partial"] += 1
        rows.append(
            {
                "name_zh": name,
                "province": province,
                "city": (item.get("city") or "").strip(),
                "grade": (item.get("rating") or "4A").strip(),
                "batch": (item.get("as_of") or "").strip(),
                "alias_zh": ";".join(a.strip() for a in aliases if a.strip()),
                "source_url": (item.get("source_url") or "").strip(),
                "remark": "；".join(remarks),
                "_update": from_update,
            }
        )

    for item in official["items"]:
        emit(item, item.get("aliases") or [], from_update=False)
    for item in updates["items"]:
        emit(item, item.get("aliases") or [], from_update=True)

    rows.sort(key=lambda r: (r["province"], r["city"], r["name_zh"]))
    out_name = f"13_4A级旅游景区_官方汇编{len(rows)}.csv"
    out_path = os.path.join(_OUT, out_name)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "name_zh",
                "province",
                "city",
                "grade",
                "batch",
                "alias_zh",
                "source_url",
                "remark",
            ],
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(rows)

    stats["rows"] = len(rows)
    stats["updates_in_rows"] = sum(1 for r in rows if r["_update"])
    stats["out"] = out_path
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
