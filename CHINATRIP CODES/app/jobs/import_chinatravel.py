"""ChinaTravel 种子数据导入 job（骨架：名称/坐标/类别/城市）.

ChinaTravel（NJU LAMDA 论文数据集，MIT/CC BY 4.0）提供多城景点/餐厅
种子 parquet。铁律（用户拍板 2026-10-23）：parquet 里的 opentime/
endtime/price/recommendmintime/recommendmaxtime 一律不写库 —— 时间
敏感字段只信高德/携程回源链（app.jobs.refresh_pois → poi_details
store）。本 job 只写骨架：source="chinatravel"，attraction→Poi
（category=type 归一）、restaurant→Restaurant（cuisine=type 归一），
类别经 poi_seed.normalize_category 受控映射。

坐标系判定（--assume auto，默认）：每城抽 --probe-per-city 条，用
高德关键词搜索回坐标，与源坐标算 haversine 中位数 —— <50m 判
GCJ-02（原样入库）；>150m 判 WGS84（wgs84_to_gcj02 转换后入库，
wgs84_location 存原始值）；之间按 WGS84 处理并在 stats 标 assumed。
高德不可用/无样本同样退 WGS84 假设 + assumed 标记。

住宿行归口（2026-10-31 用户拍板 v2）：attraction 种子中名称含 酒店/
宾馆/民宿/公寓 等住宿词的行强制 category='hotel' 落库（不跳过不隐
藏；曾因名称裸「园」hint 误归 category='park'），计入
accommodation_hotel；restaurant 种子中住宿行不属餐饮，仍跳过
（skipped_accommodation）。

注：poi_zh.parquet（餐厅）无 id/type 列 —— 缺 id 列时以文件行号为
稳定伪 id（source_poi_id 仍 ct_<city>_<id> 格式）；行内 id 为空则跳过。

用法：
    python -m app.jobs.import_chinatravel --parquet <path> \
        --kind attraction|restaurant [--assume gcj02|wgs84|auto] \
        [--probe-per-city 3] [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import sys
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app.models import Poi, Restaurant
from app.services.coords import haversine_m, out_of_china, wgs84_to_gcj02
from app.services.poi_classify import is_accommodation
from app.services.poi_seed import seed_upsert

logger = logging.getLogger(__name__)

#: haversine 中位数阈值（米）：低于判 GCJ-02，高于判 WGS84，之间 uncertain
GCJ02_MAX_M = 50.0
WGS84_MIN_M = 150.0


def _as_text(value: object) -> str:
    """标量 → 去空白字符串；None/NaN → ""."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _as_float(value: object) -> float | None:
    """标量 → float；None/NaN/不可解析 → None."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _norm_city(value: object) -> str:
    """城市名统一去「市」后缀（与 seed_upsert/KNOWN_CITIES 对齐）."""
    return _as_text(value).removesuffix("市")


def _norm_id(value: object) -> str | None:
    """数字 id → 整数字符串（3.0→"3"）；字符串原样；空 → None."""
    num = _as_float(value)
    if num is not None:
        return str(int(num)) if float(num).is_integer() else str(num)
    text = _as_text(value)
    return text or None


def _new_stats() -> dict[str, Any]:
    return {
        "read": 0,
        "imported": 0,
        "exists": 0,
        "skipped": 0,
        "skipped_no_name": 0,
        "skipped_no_coords": 0,
        "skipped_no_id": 0,
        "skipped_accommodation": 0,
        "accommodation_hotel": 0,
        "skipped_city": 0,
        "skipped_language": 0,
        "coord_system": None,
        "assumed": False,
        "per_city": {},
    }


def _filter_dataframe(df: pd.DataFrame, stats: dict[str, Any]) -> pd.DataFrame:
    """language 含 zh（若有此列）+ 城市去「市」后缀须在 KNOWN_CITIES."""
    if "language" in df.columns:
        mask = df["language"].map(_as_text).str.lower().str.contains("zh", na=False)
        excluded = int((~mask).sum())
        stats["skipped_language"] += excluded
        stats["skipped"] += excluded  # skipped 为全部跳过的伞计数
        df = df[mask]
    # 延迟 import：plan.py 依赖重，且防循环依赖
    from app.services.agent.plan import KNOWN_CITIES

    known = frozenset(KNOWN_CITIES)
    if "city" in df.columns:
        mask = df["city"].map(_norm_city).isin(known)
    else:
        mask = pd.Series(False, index=df.index)
    excluded = int((~mask).sum())
    stats["skipped_city"] += excluded
    stats["skipped"] += excluded
    return df[mask]


async def _judge_coords(samples: list[tuple[str, str, float, float]], amap: Any) -> str:
    """按高德回查坐标与源坐标的 haversine 中位数判源坐标系.

    返回 "gcj02" | "wgs84" | "uncertain"；无样本/全部回查失败也算
    "uncertain"（调用方按 WGS84+assumed 处理）。
    """
    dists: list[float] = []
    for city, name, lon, lat in samples:
        try:
            hits = await amap.search_poi(f"{city}{name}", city=city)
        except Exception:
            logger.info("import_chinatravel: coord probe search failed, name=%s", name)
            continue
        loc = hits[0].get("location") if hits else None
        if not isinstance(loc, dict):
            continue
        hit_lon, hit_lat = _as_float(loc.get("lon")), _as_float(loc.get("lat"))
        if hit_lon is None or hit_lat is None:
            continue
        dists.append(haversine_m(lon, lat, hit_lon, hit_lat))
    if not dists:
        return "uncertain"
    median = statistics.median(dists)
    if median < GCJ02_MAX_M:
        return "gcj02"
    if median > WGS84_MIN_M:
        return "wgs84"
    return "uncertain"


def _probe_samples(
    work: pd.DataFrame, per_city: int
) -> list[tuple[str, str, float, float]]:
    """每城抽前 per_city 条有效样本（城市, 名称, lon, lat）供判定."""
    samples: list[tuple[str, str, float, float]] = []
    for _, grp in work.groupby(work["city"].map(_norm_city)):
        for _, row in grp.head(max(per_city, 0)).iterrows():
            name = _as_text(row.get("name"))
            lon, lat = _as_float(row.get("lon")), _as_float(row.get("lat"))
            if not name or lon is None or lat is None:
                continue
            samples.append((_norm_city(row.get("city")), name, lon, lat))
    return samples


def _import_rows(
    work: pd.DataFrame,
    model: Any,
    session_factory: Callable[[], Any],
    seed: Callable[..., str],
    coord_system: str,
    stats: dict[str, Any],
) -> None:
    """逐行骨架写入：name/坐标/id 任一缺失即跳过并计数.

    住宿行归口（2026-10-31 用户拍板 v2）：attraction 种子中名称含
    酒店/宾馆/民宿/公寓 等住宿词的行强制 category='hotel' 落库——
    不跳过不隐藏，按类别归口（上游 type 误标以名称证据盖掉），
    计入 accommodation_hotel；restaurant 种子中住宿行不属餐饮，
    仍跳过（skipped_accommodation）。
    时间敏感字段（opentime/endtime/price/recommendmintime/
    recommendmaxtime）绝不传入 seed —— 只写名称/坐标/类别/城市。
    """
    per_city: dict[str, dict[str, int]] = stats["per_city"]
    has_id = "id" in work.columns
    has_type = "type" in work.columns
    for label, row in work.iterrows():
        name = _as_text(row.get("name"))
        if not name:
            stats["skipped_no_name"] += 1
            stats["skipped"] += 1
            continue
        accommodation = is_accommodation(name)
        if accommodation and model is Restaurant:
            stats["skipped_accommodation"] += 1
            stats["skipped"] += 1
            continue
        lon, lat = _as_float(row.get("lon")), _as_float(row.get("lat"))
        if lon is None or lat is None or out_of_china(lon, lat):
            stats["skipped_no_coords"] += 1
            stats["skipped"] += 1
            continue
        pid = _norm_id(row.get("id")) if has_id else str(label)
        if pid is None:
            stats["skipped_no_id"] += 1
            stats["skipped"] += 1
            continue
        city = _norm_city(row.get("city"))
        # WGS84 源：location 存转换后 GCJ-02，wgs84_location 存原始值；
        # GCJ-02 源：原样入库，不传 wgs84_lonlat
        kwargs: dict[str, Any] = {}
        if coord_system == "wgs84":
            kwargs["wgs84_lonlat"] = (lon, lat)
            kwargs["lonlat"] = wgs84_to_gcj02(lon, lat)
        else:
            kwargs["lonlat"] = (lon, lat)
        result = seed(
            session_factory,
            model,
            source="chinatravel",
            source_poi_id=f"ct_{city}_{pid}",
            city=city,
            name_zh=name,
            category="hotel"
            if accommodation
            else (_as_text(row.get("type")) if has_type else None),
            origin="chinatravel",
            **kwargs,
        )
        bucket = per_city.setdefault(city, {"imported": 0, "exists": 0})
        if result == "created":
            stats["imported"] += 1
            bucket["imported"] += 1
            if accommodation:
                stats["accommodation_hotel"] += 1
        elif result == "exists":
            stats["exists"] += 1
            bucket["exists"] += 1
        else:
            stats["skipped"] += 1


def _default_amap() -> Any | None:
    """从 settings 构建图商客户端（2026-10-28 走 map_provider 工厂）；未就绪 → None."""
    try:
        from app.config import get_settings
        from app.services.map_provider import build_map_client, map_ready

        settings = get_settings()
        if not map_ready(settings):
            return None
        return build_map_client(settings)
    except Exception:
        return None


def _default_ping() -> bool:
    try:
        from app.services.poi_details import get_poi_detail_store

        return bool(get_poi_detail_store().ping())
    except Exception:
        return False


def main(
    argv: list[str] | None = None,
    *,
    seed: Callable[..., str] = seed_upsert,
    session_factory: Callable[[], Any] | None = None,
    amap: Any | None = None,
    ping: Callable[[], bool] | None = None,
) -> int:
    """CLI 入口；seed/session_factory/amap/ping 可注入（测试用）."""
    parser = argparse.ArgumentParser(
        description="ChinaTravel parquet 种子导入（骨架：名称/坐标/类别/城市）"
    )
    parser.add_argument("--parquet", required=True, help="ChinaTravel parquet 路径")
    parser.add_argument(
        "--kind",
        required=True,
        choices=("attraction", "restaurant"),
        help="attraction→pois 表，restaurant→restaurants 表",
    )
    parser.add_argument(
        "--assume",
        choices=("gcj02", "wgs84", "auto"),
        default="auto",
        help="源坐标系；auto=高德探测（默认），不可用/无样本退 wgs84+assumed",
    )
    parser.add_argument(
        "--probe-per-city", type=int, default=3, help="auto 判定每城抽样条数"
    )
    parser.add_argument("--limit", type=int, default=None, help="最多导入条数")
    args = parser.parse_args(argv)

    path = Path(args.parquet)
    if not path.exists():
        print(
            json.dumps(
                {"error": f"parquet not found: {args.parquet}"}, ensure_ascii=True
            )
        )
        return 1
    if ping is None:
        ping = _default_ping
    if not ping():
        print(
            json.dumps(
                {
                    "error": "database unreachable — "
                    "start docker db (docker compose up -d db) "
                    "or check database_url"
                },
                ensure_ascii=True,
            )
        )
        return 1
    try:
        df = pd.read_parquet(path)
    except Exception as exc:
        print(
            json.dumps({"error": f"failed to read parquet: {exc}"}, ensure_ascii=True)
        )
        return 1

    stats = _new_stats()
    stats["read"] = int(len(df))
    work = _filter_dataframe(df, stats)
    if work.empty:
        stats["hint"] = (
            "0 rows matched — check --parquet path or city names "
            "(must be known cities after dropping 市 suffix)"
        )
        print(json.dumps(stats, ensure_ascii=True))
        return 0
    if args.limit is not None and args.limit > 0:
        work = work.head(args.limit)

    coord_system, assumed = args.assume, False
    if args.assume == "auto":
        effective_amap = amap if amap is not None else _default_amap()
        samples = (
            _probe_samples(work, args.probe_per_city)
            if effective_amap is not None
            else []
        )
        if samples:
            verdict = asyncio.run(_judge_coords(samples, effective_amap))
            coord_system = "gcj02" if verdict == "gcj02" else "wgs84"
            assumed = verdict == "uncertain"
        else:
            coord_system, assumed = "wgs84", True
    stats["coord_system"] = coord_system
    stats["assumed"] = assumed

    if session_factory is None:
        from app.db import get_session_factory

        session_factory = get_session_factory()
    model = Poi if args.kind == "attraction" else Restaurant
    _import_rows(work, model, session_factory, seed, coord_system, stats)
    print(json.dumps(stats, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
