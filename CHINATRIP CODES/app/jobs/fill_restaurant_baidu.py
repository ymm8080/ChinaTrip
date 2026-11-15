"""restaurants baidu 一轮收割：rating + price + hours + cuisine（place v2 scope=2）。

DESIGN tag_implementation_decisions_2026-11-12 §D1/D2。一次 scope=2 请求
的 detail_info 同时携带：overall_rating/comment_num → rating+rating_count
（rating_source='baidu'——携程美食页 11-11 判死后餐厅评分唯一活源，实测
5088 行 rating 全 NULL）；price（人均，元）→ avg_cost+price_level
（band_for_cost 五档）；shop_hours/regular_open_hour → opening_hours
（hours_source='baidu'——**餐厅表 hours 首个富化通道**，实测 5088 行全
NULL，meal_periods 回填正等着它喂）；classified_poi_tag（「美食;中餐馆;
火锅店;四川火锅」）→ 过 classify_cuisine 交叉回填 cuisine_group/family 空行。

amap 备胎移除（text 整族被 WAF deny、around 须坐标+熔断，性价比不值）；
携程国内美食页 = JS 空壳无价格（11-11 已判死）。复用 enrich_baidu_map 的
_search/_variants/_best_hit/_key_from_env（与 ops/fill_hours_rating_driver.py
同一套 baidu 日池）。

纪律（照 fill_hours_rating_driver 四条铁律）：
  * fill-empty-only——四个目标逐列独立只填空，写前复查；
  * miss 台账 ops/fill_restaurant_baidu_missed.txt：no_match/全空的行只试
    一次，配额永远花在新行；
  * 配额/风控首撞（status 401/402/302）即整批短路，未尝试行不入台账；
  * 名称闸：_best_hit 变体命中 + 库名双向包含复核，错店不写；
  * baidu 日池 ~100 次/日与 03:55 日批共享——本任务默认 --limit 20
    （≤40 次/轮），礼貌排队。

用法：
    python -m app.jobs.fill_restaurant_baidu [--limit 20] [--dry-run]
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_session_factory  # noqa: E402
from app.jobs.enrich_baidu_map import (  # noqa: E402
    _best_hit,
    _key_from_env,
    _search,
    _variants,
)
from app.models import Restaurant  # noqa: E402
from app.services.cuisine_taxonomy import classify_cuisine  # noqa: E402
from app.services.price_band import band_for_cost  # noqa: E402

logger = logging.getLogger(__name__)

_OPS = Path(__file__).resolve().parents[2] / "ops"
_MISS_FILE = _OPS / "fill_restaurant_baidu_missed.txt"
_QUOTA_STATUSES = {401, 402, 302}
_HOURS_MAX = 200


def _load_missed() -> dict[str, str]:
    if not _MISS_FILE.exists():
        return {}
    out: dict[str, str] = {}
    for line in _MISS_FILE.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(None, 1)
        if parts:
            out[parts[0]] = parts[1] if len(parts) > 1 else ""
    return out


def _append_missed(new: dict[str, str]) -> None:
    if not new:
        return
    _MISS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _MISS_FILE.open("a", encoding="utf-8") as fh:
        for rid, reason in sorted(new.items()):
            fh.write(f"{rid} {reason}\n")


def _select_rows(session_factory, *, limit: int, missed: dict[str, str]):
    from sqlalchemy import not_, or_

    with session_factory() as session:
        q = session.query(Restaurant).filter(
            Restaurant.status == "active",
            Restaurant.city.isnot(None),
            Restaurant.city != "",
            # 四个收割目标任一为空即入选（rating / price 对 / hours / cuisine 交叉）
            or_(
                Restaurant.rating.is_(None),
                Restaurant.avg_cost.is_(None),
                Restaurant.price_level.is_(None),
                Restaurant.opening_hours.is_(None),
                Restaurant.cuisine_group.is_(None),
                Restaurant.cuisine_family.is_(None),
            ),
        )
        if missed:
            import uuid as _uuid

            ids = []
            for k in missed:
                try:
                    ids.append(_uuid.UUID(str(k)))
                except (ValueError, TypeError):
                    pass
            if ids:
                q = q.filter(not_(Restaurant.id.in_(ids)))
        # 评分高的先吃配额（米其林/黑珍珠多为高分，性价比顺位自然靠前）
        rows = (
            q.order_by(Restaurant.rating.desc().nullslast(), Restaurant.id)
            .limit(limit)
            .all()
        )
        session.expunge_all()
    return rows


def _norm(s: object) -> str:
    return "".join(str(s or "").split()).lower()


def _search_hit(client, key: str, variants: list[str], city: str):
    """首变体不中再试末变体（最多两次检索），返回 _best_hit 命中或 None。"""
    d = _search(client, key, variants[0], city)
    hit = _best_hit(d.get("results") or [], variants)
    if hit is None and len(variants) > 1:
        d = _search(client, key, variants[-1], city)
        hit = _best_hit(d.get("results") or [], variants)
    return hit


def _name_like(db_name: object, matched: object) -> bool:
    """名称双向包含复核（去空白 lower；错店价格比缺价格更毒）。"""
    a, b = _norm(db_name), _norm(matched)
    return bool(a and b and len(a) >= 2 and len(b) >= 2 and (a in b or b in a))


def run(*, limit: int = 20, dry_run: bool = False) -> dict:
    # 锁：巡检 agent / 计划任务 / 会话可能同时起本作业；锁新鲜（<90min）
    # 则让位（同 enrich_ctrip_detail 的 90min 自锁约定，锁不删靠 mtime）。
    # dry-run 不占锁（探针不该挡真轮）。
    import os

    import httpx

    lock = _OPS.parent / "DESIGN" / "restaurant_baidu.lock"
    if not dry_run:
        try:
            if time.time() - os.path.getmtime(lock) < 90 * 60:
                logger.info("restaurant baidu fill skipped: lock_fresh")
                return {"skipped": "lock_fresh"}
        except OSError:
            pass
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text(str(time.time()), encoding="utf-8")

    factory = get_session_factory()
    missed = _load_missed()
    rows = _select_rows(factory, limit=limit, missed=missed)
    stats = {
        "selected": len(rows),
        "skipped_miss_file": len(missed),
        "filled_rating": 0,
        "filled_rating_count": 0,
        "filled_price": 0,
        "filled_hours": 0,
        "filled_cuisine": 0,
        "no_match": 0,
        "no_fields": 0,
        "quota_stop": None,
        "errors": 0,
    }
    if not rows:
        return stats
    key = _key_from_env()
    if not key:
        stats["quota_stop"] = "no_key"
        return stats

    new_missed: dict[str, str] = {}
    try:
        with httpx.Client(
            headers={"User-Agent": "chinatrip-enrich/0.1"}, timeout=15
        ) as client:
            for row in rows:
                name = (row.name_zh or "").strip()
                city = (row.city or "").strip()
                if not name or not city:
                    new_missed[str(row.id)] = "no_name_or_city"
                    continue
                variants = _variants(name)
                time.sleep(0.8)  # baidu QPS 风控（实测连发 ~10 次即 302），逐行缓行
                try:
                    hit = _search_hit(client, key, variants, city)
                except Exception as exc:  # noqa: BLE001
                    st = getattr(exc, "status", None)
                    if st in _QUOTA_STATUSES:
                        # 302 也可能是 QPS 风控而非日池枯竭：缓 20s 重试一次
                        time.sleep(20)
                        try:
                            hit = _search_hit(client, key, variants, city)
                        except Exception as exc2:  # noqa: BLE001
                            st2 = getattr(exc2, "status", None)
                            if st2 in _QUOTA_STATUSES:
                                stats["quota_stop"] = f"quota:{st2}"
                                break  # 真日池/风控死顶，整批短路
                            stats["errors"] += 1
                            logger.info(
                                "search retry err %s: %s", name, type(exc2).__name__
                            )
                            continue
                    else:
                        stats["errors"] += 1
                        logger.info("search err %s: %s", name, type(exc).__name__)
                        continue
                if not hit:
                    new_missed[str(row.id)] = "no_match"
                    stats["no_match"] += 1
                    continue
                di = hit.get("detail_info") or {}
                price = di.get("price")
                try:
                    cost = float(price) if price not in (None, "") else None
                except (TypeError, ValueError):
                    cost = None
                band = band_for_cost(cost)
                cp_tag = (
                    di.get("classified_poi_tag")
                    if isinstance(di.get("classified_poi_tag"), str)
                    else None
                )
                _hours_raw = di.get("shop_hours") or di.get("regular_open_hour")
                hours = (
                    str(_hours_raw).strip()[:_HOURS_MAX]
                    if isinstance(_hours_raw, str) and _hours_raw.strip()
                    else None
                )
                rv = di.get("overall_rating")
                try:
                    rv = float(rv) if rv not in (None, "") else None
                except (TypeError, ValueError):
                    rv = None
                if rv is not None and not 0 <= rv <= 5:
                    rv = None
                cn = di.get("comment_num")
                try:
                    cn = int(cn) if cn not in (None, "") else None
                except (TypeError, ValueError):
                    cn = None
                if cn is not None and not 0 <= cn <= 10_000_000:
                    cn = None
                if cost is None and not cp_tag and not hours and rv is None:
                    new_missed[str(row.id)] = "no_fields"
                    stats["no_fields"] += 1
                    continue
                # 名称闸复核（_best_hit 已做变体匹配，这里对库名再核一道）
                if (cost is not None or hours or rv is not None) and not _name_like(
                    name, hit.get("name")
                ):
                    new_missed[str(row.id)] = "name_gate"
                    stats["no_fields"] += 1
                    continue
                if dry_run:
                    logger.info(
                        "dry %s %s: price=%s band=%s hours=%s tag=%s",
                        row.id,
                        name,
                        cost,
                        band,
                        hours,
                        cp_tag,
                    )
                    if cost is not None:
                        stats["filled_price"] += 1
                    if hours:
                        stats["filled_hours"] += 1
                    if rv is not None:
                        stats["filled_rating"] += 1
                    continue
                with factory() as session:
                    db_row = session.get(Restaurant, row.id)
                    if db_row is None:
                        continue
                    # 三个目标逐列只填空，写前复查（读-写间隙可能已被他轮填过）
                    if (
                        cost is not None
                        and db_row.avg_cost is None
                        and db_row.price_level is None
                        and _name_like(db_row.name_zh, hit.get("name"))
                    ):
                        db_row.avg_cost = cost
                        db_row.price_level = band_for_cost(cost)
                        stats["filled_price"] += 1
                    if hours and db_row.opening_hours is None:
                        db_row.opening_hours = hours
                        db_row.hours_source = "baidu"
                        stats["filled_hours"] += 1
                    if (
                        rv is not None
                        and db_row.rating is None
                        and _name_like(db_row.name_zh, hit.get("name"))
                    ):
                        db_row.rating = rv
                        db_row.rating_source = "baidu"
                        stats["filled_rating"] += 1
                    if (
                        cn is not None
                        and db_row.rating_count is None
                        and _name_like(db_row.name_zh, hit.get("name"))
                    ):
                        db_row.rating_count = cn
                        stats["filled_rating_count"] += 1
                    if cp_tag and db_row.cuisine_group is None:
                        fam, grp = classify_cuisine(cp_tag)
                        if fam is not None:
                            db_row.cuisine_family = fam
                            db_row.cuisine_group = grp
                            stats["filled_cuisine"] += 1
                    session.commit()
    finally:
        _append_missed(new_missed)
    logger.info("restaurant baidu fill(rating+price+hours+cuisine): %s", stats)
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    run(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
