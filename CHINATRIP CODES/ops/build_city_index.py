# -*- coding: utf-8 -*-
"""build_city_index.py — 生成 app/services/data/city_index.json（省→地级市→县级）。

用途（backlog P2 城市解析器）：07 国保单位只有 address、06 名村只有县级
locality，需要把「县/区/县级市」上卷到「地级市」，并把地级市名归一到
与 `app.services.weather.CITY_ADCODES`（= `plan.KNOWN_CITIES`，226 座旅游
城市）同口径的短名（去「市/地区/盟」，自治州去民族限定）。

数据源：modood/Administrative-divisions-of-China 的 dist/pca-code.json
（GB/T 2260 三级区划，2026-11-01 抓取，存
`DESIGN/POIS DATASOURCE/_src/pca-code.json`）。纯离线，零 API。

用法（在 `CHINATRIP CODES` 下）：
    .venv\\Scripts\\python.exe ops\\build_city_index.py            # 写入
    .venv\\Scripts\\python.exe ops\\build_city_index.py --check    # 只比对
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.agent.plan import KNOWN_CITIES  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[1]
RAW = pathlib.Path(r"D:\CHINATRIP\DESIGN\POIS DATASOURCE\_src\pca-code.json")
OUT = REPO / "app" / "services" / "data" / "city_index.json"

MUNICIPALITIES = {
    "北京市": "北京",
    "上海市": "上海",
    "天津市": "天津",
    "重庆市": "重庆",
}

# 民族限定语（长名优先），用于把「阿坝藏族羌族自治州」削成「阿坝」。
ETHNIC = (
    "维吾尔",
    "柯尔克孜",
    "乌孜别克",
    "哈萨克",
    "塔吉克",
    "塔塔尔",
    "达斡尔",
    "鄂温克",
    "鄂伦春",
    "朝鲜",
    "俄罗斯",
    "蒙古",
    "土家",
    "布依",
    "哈尼",
    "傈僳",
    "拉祜",
    "纳西",
    "景颇",
    "仡佬",
    "仫佬",
    "毛南",
    "阿昌",
    "普米",
    "独龙",
    "裕固",
    "撒拉",
    "东乡",
    "保安",
    "锡伯",
    "德昂",
    "基诺",
    "门巴",
    "珞巴",
    "赫哲",
    "回",
    "藏",
    "苗",
    "彝",
    "壮",
    "侗",
    "瑶",
    "白",
    "傣",
    "黎",
    "佤",
    "畲",
    "水",
    "土",
    "羌",
    "怒",
    "京",
    "满",
)
_ETHNIC_SORTED = tuple(sorted(ETHNIC, key=len, reverse=True))
_AUTONOMOUS_RE = re.compile(r"自治(州|县|旗|区)$")
_PSEUDO_PREFECTURES = {"市辖区", "县", "省直辖县级行政区划", "自治区直辖县级行政区划"}
_KNOWN = frozenset(KNOWN_CITIES)


def short_prefecture(name: str) -> str:
    """地级名 → 短名：去自治州民族限定 + 去 市/地区/盟/州 后缀。

    `阿拉善盟`/`神农架林区` 这类注册名本身带后缀，由 `canonical_prefecture`
    优先命中注册表回退处理。
    """
    s = _AUTONOMOUS_RE.sub("", name)
    s = s.replace("族", "")
    changed = True
    while changed:
        changed = False
        for eth in _ETHNIC_SORTED:
            if s.endswith(eth) and len(s) > len(eth):
                s = s[: -len(eth)]
                changed = True
                break
    for suf in ("市", "地区", "盟", "州", "区", "县", "旗"):
        if s.endswith(suf) and len(s) > len(suf):
            return s[: -len(suf)]
    return s


def canonical_province(full: str) -> str:
    """省级全名 → 短名。**不能**走 `short_prefecture`：`内蒙古/西藏/贵州`
    会被民族语/「州」后缀规则误削成「内/西/贵」。"""
    s = full
    for suf in ("壮族自治区", "回族自治区", "维吾尔自治区", "自治区", "省", "市"):
        if s.endswith(suf):
            return s[: -len(suf)]
    return s


def canonical_prefecture(name: str) -> str:
    """注册表优先：`阿坝藏族羌族自治州`→`阿坝`（注册名）、`阿拉善盟`→`阿拉善盟`。"""
    if name in _KNOWN:
        return name
    short = short_prefecture(name)
    if short in _KNOWN:
        return short
    for suf in ("盟", "林区", "市", "州"):
        if short + suf in _KNOWN:
            return short + suf
    return short


def iter_prefectures(raw: list[dict]):
    for prov in raw:
        pfull = prov["name"]
        for city in prov.get("children") or []:
            yield pfull, city


def build(raw: list[dict]) -> dict:
    provinces: dict[str, dict] = {}
    for prov in raw:
        pfull = prov["name"]
        if pfull in MUNICIPALITIES:
            # 直辖市：区/县一律上卷到市本身（北京 → 北京）
            pshort = MUNICIPALITIES[pfull]
        else:
            pshort = canonical_province(pfull)
        entry = provinces.setdefault(
            pshort, {"full": pfull, "prefectures": {}, "counties": {}}
        )
        for city in prov.get("children") or []:
            cfull = city["name"]
            if cfull in _PSEUDO_PREFECTURES:
                if pfull in MUNICIPALITIES:
                    for area in city.get("children") or []:
                        entry["counties"][area["name"]] = pshort
                else:
                    # 省直辖县级单位（济源/仙桃/潜江/石河子…）：自成一城
                    for area in city.get("children") or []:
                        entry["counties"][area["name"]] = canonical_prefecture(
                            area["name"]
                        )
                continue
            cshort = canonical_prefecture(cfull)
            entry["prefectures"][cfull] = cshort
            entry["prefectures"].setdefault(cshort, cshort)
            for area in city.get("children") or []:
                entry["counties"][area["name"]] = cshort
    total_pref = sum(len(v["prefectures"]) for v in provinces.values())
    total_county = sum(len(v["counties"]) for v in provinces.values())
    return {
        "_meta": {
            "generated_on": date.today().isoformat(),
            "source": (
                "modood/Administrative-divisions-of-China "
                "dist/pca-code.json (GB/T 2260)"
            ),
            "note": "地级名按 KNOWN_CITIES/CITY_ADCODES 短名口径归一；"
            "县级名上卷到属地级市",
            "provinces": len(provinces),
            "prefecture_keys": total_pref,
            "county_keys": total_county,
        },
        "provinces": provinces,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对，不写盘")
    args = ap.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    if not RAW.exists():
        print(f"missing source: {RAW}")
        return 2
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    index = build(raw)
    text = json.dumps(index, ensure_ascii=False, indent=1, sort_keys=True)
    if args.check:
        cur = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        same = json.loads(cur) if cur else None
        print("identical" if same == index else "DIFFERENT")
        return 0 if same == index else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    meta = index["_meta"]
    print(
        f"wrote {OUT} ({len(text.encode('utf-8'))} bytes) "
        f"provinces={meta['provinces']} prefecture_keys={meta['prefecture_keys']} "
        f"county_keys={meta['county_keys']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
