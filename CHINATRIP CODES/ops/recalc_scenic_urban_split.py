"""风景区时长按「市区内/外」一次性重算（ops，2026-10-31 用户拍板）。

背景：POIS 库名称含景区标记（风景名胜区/旅游景区/旅游区/风景区/景区）
的行时长档混杂——两行城市拍板 180、旧 nature 地板遗留 180、90→240 重算
240。2026-10-31 用户拍板统一口径：**市区内的设成 180 分钟，市区外的设
成 240 分钟**（有实际值不覆盖）；同日补充拍板：**名称含「山」的景区
行一律 240**（山体景区即市区内也是大半天量级，覆盖市区半径判定；
真值不覆盖）。

口径（判定顺序：人工表 → 山名 → 市区半径）：
- 山名规则：名称含「山」→ 240（2026-10-31 第二次拍板）；
- 市区内/外判定：POI 坐标到市中心的球面距离 ≤ 25km 算市区内。坐标
  wgs84_location 优先，缺则退 location（GCJ-02，与 WGS-84 中心差
  百米级，25km 门限下可忽略）；市中心取自
  app.services.weather_open_meteo.CITY_COORDS（高德行政区划 API 官方
  表，WGS-84）+ 本脚本州府中心补充表；
- CITY_COORDS 是天气口径（直辖市取全域质心），天津质心在宝坻方向，
  本判定须市区核——_CITY_CENTER_FIX 对天津覆写市区坐标；
- 只动 duration_source='heuristic' 的行——真值行（ctrip/qunar/llm_web）
  有实际值不覆盖（2026-10-31 用户拍板），与 duration_upgradable 语义
  一致；
- 名称含 酒店/民宿/宾馆/公寓/度假村 的住宿噪声行不动（2026-10-31 拍板
  另行处理）；
- 无城市锚点/海岛目的地等机械规则会误判的行进 _MANUAL_ROWS 人工拍板
  表，输出单列供复核；
- 重算后 duration_source 维持 'heuristic'。

用法：python ops/recalc_scenic_urban_split.py            # dry-run 打印对照
      python ops/recalc_scenic_urban_split.py --apply   # 落库
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

import psycopg

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.weather_open_meteo import CITY_COORDS  # noqa: E402

DSN = "postgresql://chinatrip:chinatrip@localhost:5432/chinatrip"

SCENIC_NAME_RE = r"风景名胜区|旅游景区|旅游区|风景区|景区"
STAY_NOISE_RE = re.compile(r"酒店|民宿|宾馆|公寓|度假村")

# 市区半径（2026-10-31 拍板「市区内/外」的可操作化：建成区+近郊量级，
# 再远就是单占一天的远郊景区）
URBAN_RADIUS_KM = 25.0

# 直辖市全域质心 ≠ 市区（天气口径可用、本判定不行）：天津质心在宝坻
# 方向，把南开区古文化街判成 27km「市区外」。覆写为市区核（和平区一带，
# 与北京=天安门/上海=人民广场/重庆=渝中同口径）。
_CITY_CENTER_FIX: dict[str, tuple[float, float]] = {
    "天津": (39.1255, 117.2005),
}

# CITY_COORDS 只覆盖天气城市表，缺州府/县城中心——POI 库 city 列会出现
# 这些自治州/地区名。坐标为州府驻地（WGS-84 近似，25km 门限下无需精确）。
_PREFECTURE_CENTERS: dict[str, tuple[float, float]] = {
    "伊犁": (43.9168, 81.3243),  # 伊宁市
    "巴音郭楞": (41.7378, 86.1520),  # 库尔勒市
    "甘孜": (30.0521, 101.9637),  # 康定市
    "保亭": (18.6363, 109.7004),  # 保亭县城
    "陵水": (18.5083, 110.0242),  # 陵水县城
    "石家庄": (38.0428, 114.5149),
    "阿勒泰": (47.8484, 88.1396),  # 阿勒泰市
    "临夏": (35.5995, 103.2110),  # 临夏市
    "兴安盟": (46.0727, 122.0774),  # 乌兰浩特
    "博尔塔拉": (44.9060, 82.0667),  # 博乐市
    "大兴安岭": (50.4207, 124.1194),  # 加格达奇
    "延边": (42.9048, 129.5089),  # 延吉市
    "敦化": (43.3660, 128.2320),  # 敦化市（延边敦化全称的后缀实城）
    "文山": (23.3694, 104.2446),  # 文山市
    "新疆生产建设兵团阿拉尔": (40.5419, 81.2859),  # 阿拉尔市
    "日喀则": (29.2690, 88.8800),  # 桑珠孜区
    "昌吉": (44.0146, 87.3043),  # 昌吉市
    "海北": (36.8985, 100.9017),  # 海晏县西海镇
    "海南州": (36.2836, 100.6196),  # 共和县
    "湘西": (28.3119, 109.7395),  # 吉首市
    "黔东南": (26.5833, 107.9667),  # 凯里市
    "黔南": (26.2560, 107.5172),  # 都匀市
}

# 机械规则会误判的行（无城市锚点 / 目的地型），按名称子串人工拍板。
# (目标分钟, 理由)——输出单列，供用户复核推翻。
_MANUAL_ROWS: dict[str, tuple[int, str]] = {
    "矮寨": (240, "无城市锚点，湘西远郊峡谷目的地"),
    "长白山": (240, "无城市锚点，白山/延边交界远郊目的地"),
    "分界洲岛": (240, "海岛目的地（含船程），距县城半径会误判市区内"),
    "三五九旅": (240, "5A 品牌含沙漠之门（市区外 40km），目的地型"),
}

_earth_radius_km = 6371.0088


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _earth_radius_km * math.asin(math.sqrt(a))


def _resolve_center(city: str | None) -> tuple[float, float] | None:
    """ city → 市中心 (lat, lon)：直查 → 全称后缀/包含归一。"""
    if not city:
        return None
    tables = (
        {**CITY_COORDS, **_CITY_CENTER_FIX},
        _PREFECTURE_CENTERS,
    )
    for table in tables:
        if city in table:
            return table[city]
    # 全称变体：喀什地区喀什 / 大理白族自治州大理 / 恩施土家族苗族自治州恩施
    for table in tables:
        suffix_hits = [k for k in table if len(k) >= 2 and city.endswith(k)]
        if suffix_hits:
            return table[max(suffix_hits, key=len)]
        contains = [k for k in table if len(k) >= 2 and k in city]
        if contains:
            return table[max(contains, key=len)]
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="落库（默认 dry-run）")
    args = ap.parse_args()

    with psycopg.connect(DSN, connect_timeout=5) as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT id, name_zh, city, suggested_duration_min,
                   ST_Y(wgs84_location::geometry), ST_X(wgs84_location::geometry),
                   ST_Y(location::geometry), ST_X(location::geometry)
            FROM pois
            WHERE status='active'
              AND duration_source='heuristic'
              AND suggested_duration_min IN (180, 240)
              AND name_zh ~ %s
              AND name_zh !~ '酒店|民宿|宾馆|公寓|度假村'
            ORDER BY city NULLS LAST, name_zh
            """,
            (SCENIC_NAME_RE,),
        )
        rows = cur.fetchall()

        plan: dict[str, tuple[str, str, int, float | None]] = {}
        no_coord: list[tuple[str, str, int]] = []
        no_center: list[tuple[str, str, int]] = []
        manual_hits: list[str] = []
        mountain_hits: list[str] = []
        transitions = {"180->180": 0, "180->240": 0, "240->180": 0, "240->240": 0}
        borderline: list[str] = []

        for pid, name, city, cur_min, wlat, wlon, glat, glon in rows:
            manual = next(
                (v for k, v in _MANUAL_ROWS.items() if k in name), None
            )
            if manual is not None:
                target, why = manual
                plan[pid] = (name, city or "?", target, None)
                transitions[f"{cur_min}->{target}"] += 1
                manual_hits.append(f"   [{cur_min}→{target}] {city or '?'} | {name}（{why}）")
                continue
            if "山" in name:
                # 山名规则（2026-10-31 第二次拍板）：山体景区一律 240，
                # 无需坐标/中心——顺带救起无坐标的山名行
                plan[pid] = (name, city or "?", 240, None)
                transitions[f"{cur_min}->240"] += 1
                if cur_min == 180:
                    mountain_hits.append(f"   {city or '?'} | {name} | 180→240")
                continue
            lat, lon = (wlat, wlon) if wlat is not None else (glat, glon)
            if lat is None:
                no_coord.append((city or "?", name, cur_min))
                continue
            center = _resolve_center(city)
            if center is None:
                no_center.append((city or "?", name, cur_min))
                continue
            dist = _haversine_km(lat, lon, center[0], center[1])
            target = 180 if dist <= URBAN_RADIUS_KM else 240
            plan[pid] = (name, city or "?", target, dist)
            transitions[f"{cur_min}->{target}"] += 1
            if 20 <= dist <= 35:
                borderline.append(
                    f"   [{dist:.0f}km] {city} | {name} | {cur_min}→{target}"
                )

        n_change = sum(
            v for k, v in transitions.items() if k.split("->")[0] != k.split("->")[1]
        )
        print(
            f"选取 {len(rows)} 行：变更 {n_change}，"
            f"维持 {transitions['180->180'] + transitions['240->240']}；"
            f"无坐标不动 {len(no_coord)}，城市缺市中心 {len(no_center)}"
        )
        print(
            "分档明细：180维持 {a}，180→240 {b}，240→180 {c}，240维持 {d}".format(
                a=transitions["180->180"],
                b=transitions["180->240"],
                c=transitions["240->180"],
                d=transitions["240->240"],
            )
        )
        if manual_hits:
            print(f"\n== 人工拍板行（{len(manual_hits)}，可复核推翻）==")
            for line in manual_hits:
                print(line)
        if mountain_hits:
            print(f"\n== 山名规则 180→240（{len(mountain_hits)} 行）==")
            for line in sorted(mountain_hits):
                print(line)
        if no_coord:
            print("\n== 无坐标不动（缺位置判不了市区，请人工补坐标）==")
            for c, n, m in sorted(no_coord):
                print(f"   [{m}min] {c} | {n}")
        if no_center:
            print("\n== 城市不在中心表（不覆盖）==")
            for c, n, m in sorted(no_center):
                print(f"   [{m}min] {c} | {n}")
        if borderline:
            print(f"\n== 边界行 20-35km（{len(borderline)} 行，请复核）==")
            for line in sorted(borderline):
                print(line)

        if not args.apply:
            print("\n(dry-run，加 --apply 落库)")
            return 0
        for pid, (_name, _city, minutes, _dist) in plan.items():
            cur.execute(
                "UPDATE pois SET suggested_duration_min=%s WHERE id=%s",
                (minutes, pid),
            )
        con.commit()
        print(f"已落库：{len(plan)} 行更新（无坐标/缺市中心行未动）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
