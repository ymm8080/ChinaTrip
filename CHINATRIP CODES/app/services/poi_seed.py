"""POI 底库种子存储层（外部源骨架导入）.

铁律（DESIGN/feature_gap_and_dev_plan_2026-10-23.md §4.2）：外部源
（ChinaTravel/OSM/5A）只写「骨架」——名称/坐标/类别；时间敏感字段
（hours/price/phone）绝不在此层写，只信后续高德/携程回源链
（app.jobs.refresh_pois → poi_details store）。**duration 例外**
（2026-10-25 用户拍板）：新 Poi 行插入即按名称/类别打 heuristic
地板值（duration_source='heuristic'），真值源（ctrip/qunar）可
升级覆盖——见 app.services.poi_classify.duration_upgradable。
判重键 (source, source_poi_id)，已存在的行不覆盖任何字段。DB 异常
降级为 log warning + "skipped"，导入 job 继续跑。
同馆去重闸（2026-10-26 用户令：所有入表行先过同馆去重）：新建路径先
按名称级候选（来名 + 来别名等值查询）找同馆行——判定阶梯：同键异源
＞城市相容（双向子串，与 import_intl_picks._same_city 同约定）＞跨粒
度（一侧省级回退名 + 类别相容）。命中则骨架字段只填空并入已有行；
incoming 为 curated 名单源且孪生为渠道行时，curated 当权威：新行吸收
孪生骨架字段后建行、孪生退役。同名不同场馆（孙中山纪念馆 南京/广州）
不受影响正常插入。时间敏感字段（hours/price/phone）闸内一律不搬。
并发窗口不做库级唯一约束（跨粒度合并与唯一索引互斥），导入作业串行。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.services.coords import make_point, wgs84_to_gcj02
from app.services.poi_classify import classify

logger = logging.getLogger(__name__)

#: curated 名单源——同馆去重时权威行优先（curated 行吸收渠道孪生）
CURATED_SOURCES = frozenset(
    {"museum1", "museum2", "museum3", "artmuseum", "unesco", "5a"}
)

#: 省级行政区名（直辖市兼市名）——museum/unesco 等 curated 骨架 city
#: 省级回退与渠道行市名之间的跨粒度同城判定用
PROVINCE_LEVEL = frozenset(
    {
        "北京",
        "上海",
        "天津",
        "重庆",
        "河北",
        "山西",
        "辽宁",
        "吉林",
        "黑龙江",
        "江苏",
        "浙江",
        "安徽",
        "福建",
        "江西",
        "山东",
        "河南",
        "湖北",
        "湖南",
        "广东",
        "海南",
        "四川",
        "贵州",
        "云南",
        "陕西",
        "甘肃",
        "青海",
        "内蒙古",
        "广西",
        "西藏",
        "宁夏",
        "新疆",
        "香港",
        "澳门",
        "台湾",
    }
)


def _is_active(row: Any) -> bool:
    return (getattr(row, "status", None) or "active") == "active"


def _city_compatible(a: str, b: str) -> bool:
    """城市相容：既有约定（import_intl_picks._same_city）= 双向子串包含."""
    return bool(a) and bool(b) and (a in b or b in a)


def _skeleton_backfill(target: Any, fields: dict[str, Any]) -> list[str]:
    """骨架字段只填空回填（铁律 §4.2：坐标/类别/名称/标签/时长地板；
    时间敏感字段 hours/price/phone 绝不在此层写）。返回已填字段名。"""
    filled: list[str] = []
    for f, v in fields.items():
        if v is None:
            continue
        if f == "name_aliases":
            merged = list(getattr(target, "name_aliases", None) or [])
            add = [
                x
                for x in (v or [])
                if x and x not in merged and x != getattr(target, "name_zh", None)
            ]
            if add:
                target.name_aliases = [*merged, *add]
                filled.append(f)
            continue
        if getattr(target, f, None) is not None:
            continue
        setattr(target, f, v)
        filled.append(f)
    return filled


def _find_same_venue(
    session: Any,
    model: Any,
    *,
    source: str,
    source_poi_id: str,
    name_zh: str,
    city: str,
    category: str | None,
    aliases: list[str] | None,
) -> Any | None:
    """名称级同馆候选（2026-10-26 用户令：入表前同馆去重）。

    候选发现 = name_zh 等值查询（来名 + 来别名逐个；等值写法让
    FakeSession 单测可跑）；判定计分：同键异源(3) > 城市相容(2) >
    跨粒度省级(1)，curated 孪生同级加分。无场馆信号 → None（不同
    场馆，正常插入）。候选发现异常 → None（闸放行，导入不断）。
    """
    names = [name_zh]
    seen = {name_zh}
    for a in aliases or []:
        a = (a or "").strip()
        if a and a not in seen:
            seen.add(a)
            names.append(a)
    cands: list[Any] = []
    got: set[int] = set()
    for n in names:
        try:
            rows = session.query(model).filter(model.name_zh == n).all()
        except Exception:
            return None
        for r in rows:
            if id(r) not in got and _is_active(r):
                got.add(id(r))
                cands.append(r)
    best: tuple[tuple[int, int], Any] | None = None
    for r in cands:
        if r.source == source and r.source_poi_id == source_poi_id:
            continue
        venue = 0
        if r.source_poi_id == source_poi_id and r.source != source:
            venue = 3  # 血统影子：同键异源
        else:
            tw_city = (getattr(r, "city", "") or "").strip()
            if _city_compatible(city, tw_city):
                venue = 2
            else:
                gran = (city in PROVINCE_LEVEL) != (tw_city in PROVINCE_LEVEL)
                tw_cat = getattr(r, "category", None)
                if gran and (category is None or tw_cat is None or tw_cat == category):
                    venue = 1
        if not venue:
            continue
        cur = 1 if r.source in CURATED_SOURCES else 0
        key = (venue, cur)
        if best is None or key > best[0]:
            best = (key, r)
    return best[1] if best else None


#: 中文/OSM 原始类别 → 受控英文类别（精确匹配层）
CATEGORY_MAP: dict[str, str] = {
    # ChinaTravel type 值
    "博物馆/纪念馆": "museum",
    "公园/广场": "park",
    "历史遗迹": "historic",
    "寺庙/教堂": "temple",
    "自然风光": "nature",
    "游乐园": "theme_park",
    "动物园/植物园": "zoo",
    "观景台/地标": "viewpoint",
    "文化村/古镇": "ancient_town",
    "其他": "other",
    # OSM tourism/leisure 值
    "attraction": "attraction",
    "museum": "museum",
    "gallery": "gallery",
    "zoo": "zoo",
    "theme_park": "theme_park",
    "viewpoint": "viewpoint",
    "ruins": "ruins",
    "castle": "castle",
    "memorial": "memorial",
    "temple": "temple",
    "church": "church",
    "park": "park",
    "garden": "garden",
}


def normalize_category(raw: str | None) -> str | None:
    """原始类别 → 受控英文类别；先精确后包含，匹配不上返回 None."""
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    hit = CATEGORY_MAP.get(text) or CATEGORY_MAP.get(text.lower())
    if hit is not None:
        return hit
    lowered = text.lower()
    best: tuple[int, str] | None = None  # (命中词长度, 受控类别)
    for key, target in CATEGORY_MAP.items():
        for part in key.split("/"):  # 「博物馆/纪念馆」拆词参与包含匹配
            pl = part.lower()
            if (pl in lowered or lowered in pl) and (best is None or len(pl) > best[0]):
                best = (len(pl), target)
    return best[1] if best else None


def seed_upsert(
    session_factory: Callable[[], Any],
    model: Any,  # Poi 或 Restaurant
    *,
    source: str,
    source_poi_id: str,
    city: str,
    name_zh: str,
    category: str | None = None,
    lonlat: tuple[float, float] | None = None,
    wgs84_lonlat: tuple[float, float] | None = None,
    name_en: str | None = None,
    origin: str | None = None,
    tags: list[str] | None = None,  # 等级/品质标签（非时间敏感，可与骨架同写）
    tags_source: str | None = None,
    name_aliases: list[str] | None = None,  # 曾用名/别名（名称匹配层用）
) -> str:
    """骨架 upsert，返回 "created" | "exists" | "skipped".

    存在同 (source, source_poi_id) 行则不覆盖任何字段（"exists"）；
    名称级同馆命中（模块头「同馆去重闸」）同样归 "exists"——已有行
    只填空回填骨架字段；incoming curated 且孪生为渠道行时 curated
    行建行、孪生退役（归 "created"）；
    空 name_zh 或 DB 异常返回 "skipped"（job 继续）。city 统一去「市」
    后缀；category 经 normalize_category 归一（Poi→category，
    Restaurant→cuisine）；location 恒存 GCJ-02，仅给 WGS84 时自动
    派生，wgs84_location 存原始 WGS84。时间敏感字段（hours/price/
    phone）绝不在此层写；duration 地板例外——Poi 新行插入即分类
    填 suggested_duration_min + duration_source='heuristic'（2026-10-25
    拍板，真值源可升级），Restaurant 不受影响。
    """
    name_zh = (name_zh or "").strip()
    if not name_zh:
        return "skipped"
    city = (city or "").strip().removesuffix("市")
    name_en = (name_en or "").strip() or None
    cat = normalize_category(category)
    indoor = rain_ok = floor = None
    if hasattr(model, "suggested_duration_min"):  # Poi：插入即分类填列
        cat, indoor, rain_ok, floor = classify(name_zh, cat)
    if lonlat is None and wgs84_lonlat is not None:
        lonlat = wgs84_to_gcj02(*wgs84_lonlat)
    try:
        with session_factory() as session:
            row = (
                session.query(model)
                .filter_by(source=source, source_poi_id=source_poi_id)
                .one_or_none()
            )
            if row is not None:
                return "exists"  # 骨架不覆盖：已有行原样保留
            if source == "chinatravel":
                # 血统防影子：ct_* 骨架被回源升级后 source 变 "amap"
                # （2026-10 前的老升级连 origin 都留空，可靠血统标记只剩
                # source_poi_id 本身——amap 原生 ID 不会长成 ct_<city>_<n>）。
                # 同一 source_poi_id 只要在其它 source 下已存在即视为已导入，
                # 不重建 data-poor 影子行。仅对 chinatravel 生效，unesco/5a
                # 跨源共存按设计不动。
                twins = (
                    session.query(model)
                    .filter(model.source_poi_id == source_poi_id)
                    .all()
                )
                if any(r.source != source for r in twins):
                    return "exists"
            kwargs: dict[str, Any] = {
                "id": uuid4(),
                "source": source,
                "source_poi_id": source_poi_id,
                "city": city,
                "name_zh": name_zh,
                "status": "active",
                "origin": origin or source,
            }
            if cat is not None:
                if hasattr(model, "category"):
                    kwargs["category"] = cat
                elif hasattr(model, "cuisine"):
                    kwargs["cuisine"] = cat
            if indoor is not None and hasattr(model, "indoor"):
                kwargs["indoor"] = indoor
            if rain_ok is not None and hasattr(model, "rain_ok"):
                kwargs["rain_ok"] = rain_ok
            if floor is not None and hasattr(model, "suggested_duration_min"):
                kwargs["suggested_duration_min"] = floor
                kwargs["duration_source"] = "heuristic"
            if name_en is not None:
                kwargs["name_en"] = name_en
            if tags:
                kwargs["tags"] = list(tags)
            if tags_source:
                kwargs["tags_source"] = tags_source
            if name_aliases:
                kwargs["name_aliases"] = list(name_aliases)
            if lonlat is not None:
                kwargs["location"] = make_point(*lonlat)
            if wgs84_lonlat is not None:
                kwargs["wgs84_location"] = make_point(*wgs84_lonlat)
            twin = _find_same_venue(
                session,
                model,
                source=source,
                source_poi_id=source_poi_id,
                name_zh=name_zh,
                city=city,
                category=cat,
                aliases=name_aliases,
            )
            skeleton = {
                "category" if hasattr(model, "category") else "cuisine": cat,
                "indoor": indoor,
                "rain_ok": rain_ok,
                "name_en": name_en,
                "location": kwargs.get("location"),
                "wgs84_location": kwargs.get("wgs84_location"),
                "tags": list(tags) if tags else None,
                "tags_source": tags_source,
                "name_aliases": list(name_aliases) if name_aliases else None,
            }
            if twin is not None:
                if source in CURATED_SOURCES and twin.source not in CURATED_SOURCES:
                    # curated 权威行优先：新行吸收孪生骨架字段后建行，
                    # 渠道孪生退役（时间敏感字段不搬，回源链会重填）
                    for f in skeleton:
                        if kwargs.get(f) is not None:
                            continue
                        v = skeleton.get(f)
                        if v is None:
                            v = getattr(twin, f, None)
                        if v is not None:
                            kwargs[f] = v
                    if (
                        kwargs.get("suggested_duration_min") is None
                        and getattr(twin, "duration_source", None) == "heuristic"
                    ):
                        kwargs["suggested_duration_min"] = twin.suggested_duration_min
                        kwargs["duration_source"] = "heuristic"
                    al = list(kwargs.get("name_aliases") or [])
                    al += [a for a in (twin.name_aliases or []) if a not in al]
                    if twin.name_zh != name_zh and twin.name_zh not in al:
                        al.append(twin.name_zh)
                    if al:
                        kwargs["name_aliases"] = al
                    tw_city = (getattr(twin, "city", "") or "").strip()
                    if (
                        city in PROVINCE_LEVEL
                        and tw_city
                        and tw_city not in PROVINCE_LEVEL
                    ):
                        kwargs["city"] = tw_city
                    session.add(model(**kwargs))
                    twin.status = "retired"
                    session.commit()
                    logger.info(
                        "poi_seed: curated %s/%s 吸收渠道孪生 %s/%s（retired）",
                        source,
                        source_poi_id,
                        twin.source,
                        twin.source_poi_id,
                    )
                    return "created"
                filled = _skeleton_backfill(twin, skeleton)
                if (
                    getattr(twin, "suggested_duration_min", None) is None
                    and floor is not None
                    and hasattr(model, "suggested_duration_min")
                ):
                    twin.suggested_duration_min = floor
                    twin.duration_source = "heuristic"
                    filled.append("suggested_duration_min")
                tw_city = (getattr(twin, "city", "") or "").strip()
                if city not in PROVINCE_LEVEL and tw_city in PROVINCE_LEVEL:
                    twin.city = city
                    filled.append("city")
                if filled:
                    session.commit()
                logger.info(
                    "poi_seed: 同馆并入 %s/%s -> 已有行 %s/%s（%s）",
                    source,
                    source_poi_id,
                    twin.source,
                    twin.source_poi_id,
                    ",".join(filled) or "无字段可填",
                )
                return "exists"
            session.add(model(**kwargs))
            session.commit()
        return "created"
    except Exception:
        logger.warning(
            "poi_seed: seed_upsert failed (%s/%s)",
            source,
            source_poi_id,
            exc_info=True,
        )
        return "skipped"


def mark_status(
    session_factory: Callable[[], Any],
    model: Any,
    source: str,
    source_poi_id: str,
    status: str,
) -> bool:
    """置行 status（如 OSM delete → "inactive"）；行不存在返回 False."""
    try:
        with session_factory() as session:
            row = (
                session.query(model)
                .filter_by(source=source, source_poi_id=source_poi_id)
                .one_or_none()
            )
            if row is None:
                return False
            row.status = status
            session.commit()
        return True
    except Exception:
        logger.warning(
            "poi_seed: mark_status failed (%s/%s)",
            source,
            source_poi_id,
            exc_info=True,
        )
        return False
