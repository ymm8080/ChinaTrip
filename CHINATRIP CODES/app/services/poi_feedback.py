"""自产反馈存储（DESIGN §3.4 D1/D2 + §4 互动闭环，2026-10-25）。

卡片 👍/👎、行中打卡、行后点评三类事件的落地层。评价键 name@city
（与展示层一致；poi_id 对齐由聚合作业/DB 匹配兜底）——**我们的用户
就是外国人，本存储天然积累「外国人视角」评论资产（§3.6-③）**。

双写策略与 PoiDetailStore 同款：内存 always-on（无 PG 也能跑），
DB best-effort（poi_reviews 逐条 + poi_stats 计数，按 name+city →
pois 行匹配，未匹配只留内存不报错）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.models import Poi, PoiReview, PoiStat

logger = logging.getLogger(__name__)

# 点评标签词表（§4-④；入境专属维度 §3.6）
REVIEW_TAGS = (
    "人多",
    "出片",
    "一般",
    "亲子友好",
    "不值",
    "外卡支付可用",
    "英文菜单/服务",
    "护照预订友好",
    "免签适用",
)


def _norm(name: str, city: str | None) -> tuple[str, str]:
    n = (name or "").strip()
    c = (city or "").strip().removesuffix("市")
    return n, c


class PoiFeedbackStore:
    """投票/打卡/点评：内存计数 + 最近点评，DB 双写尽力而为。"""

    def __init__(self, session_factory=None) -> None:
        self._factory = session_factory
        # key = (name, city) → counters
        self._counters: dict[tuple[str, str], dict] = {}
        self._reviews: dict[tuple[str, str], list[dict]] = {}

    # --- write ----------------------------------------------------------

    def vote(self, name: str, city: str | None, *, up: bool) -> dict:
        key = _norm(name, city)
        c = self._counters.setdefault(
            key,
            {
                "thumbs_up": 0,
                "thumbs_down": 0,
                "visit_count": 0,
                "xhs_mentions": 0,
            },
        )
        c["thumbs_up" if up else "thumbs_down"] += 1
        self._flush_stats(key)
        return self.stats_for(name, city)

    def visit(self, name: str, city: str | None) -> dict:
        key = _norm(name, city)
        c = self._counters.setdefault(
            key,
            {
                "thumbs_up": 0,
                "thumbs_down": 0,
                "visit_count": 0,
                "xhs_mentions": 0,
            },
        )
        c["visit_count"] += 1
        self._flush_stats(key)
        return self.stats_for(name, city)

    def note_link_mention(self, name: str, city: str | None) -> None:
        """§5.3：链接解析事件按 POI 聚合计数（小红书热度代理，只存统计）。"""
        key = _norm(name, city)
        c = self._counters.setdefault(
            key,
            {
                "thumbs_up": 0,
                "thumbs_down": 0,
                "visit_count": 0,
                "xhs_mentions": 0,
            },
        )
        c["xhs_mentions"] += 1

    def add_review(
        self,
        name: str,
        city: str | None,
        *,
        rating: int | None = None,
        tags: list[str] | None = None,
        text: str | None = None,
        device_id: str | None = None,
        source: str = "post_visit",
    ) -> dict:
        if rating is not None and not 1 <= int(rating) <= 5:
            raise ValueError("rating_out_of_range")
        clean_tags = [t for t in (tags or []) if t in REVIEW_TAGS][:8]
        key = _norm(name, city)
        review = {
            "id": uuid4().hex,
            "name": key[0],
            "city": key[1],
            "rating": int(rating) if rating else None,
            "tags": clean_tags,
            "text": (text or "").strip()[:500] or None,
            "device_id": device_id,
            "source": source,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._reviews.setdefault(key, []).append(review)
        self._flush_review(key, review)
        return review

    # --- read -----------------------------------------------------------

    def stats_for(self, name: str, city: str | None) -> dict:
        key = _norm(name, city)
        c = dict(self._counters.get(key) or {})
        reviews = self._reviews.get(key) or []
        rated = [r["rating"] for r in reviews if r["rating"]]
        if rated:
            c["avg_rating"] = round(sum(rated) / len(rated), 1)
        c["review_count"] = len(reviews)
        return c

    def export_counters(self) -> dict[tuple[str, str], dict]:
        """聚合作业消费（D2）：计数快照。"""
        return {k: dict(v) for k, v in self._counters.items()}

    def recent_reviews(self, name: str, city: str | None, limit: int = 5) -> list[dict]:
        key = _norm(name, city)
        reviews = list(self._reviews.get(key) or [])
        reviews.reverse()
        return reviews[:limit]

    # --- DB best-effort ---------------------------------------------------

    def _resolve_poi_id(self, session, name: str, city: str) -> UUID | None:
        row = (
            session.query(Poi)
            .filter(Poi.name_zh == name, Poi.city.in_({city, f"{city}市"}))
            .first()
        )
        return row.id if row is not None else None

    def _flush_stats(self, key: tuple[str, str]) -> None:
        if self._factory is None:
            return
        name, city = key
        counters = self._counters.get(key) or {}
        try:
            with self._factory() as session:
                poi_id = self._resolve_poi_id(session, name, city)
                if poi_id is None:
                    return
                row = session.get(PoiStat, poi_id)
                if row is None:
                    row = PoiStat(poi_id=poi_id)
                    session.add(row)
                row.thumbs_up = counters.get("thumbs_up", 0)
                row.dislike_count = counters.get("thumbs_down", 0)
                row.visit_count = counters.get("visit_count", 0)
                row.xhs_mentions = counters.get("xhs_mentions", 0)
                row.updated_at = datetime.now(timezone.utc)
                session.commit()
        except Exception:
            logger.warning("poi_feedback: stats flush failed", exc_info=True)

    def _flush_review(self, key: tuple[str, str], review: dict) -> None:
        if self._factory is None:
            return
        name, city = key
        try:
            with self._factory() as session:
                poi_id = self._resolve_poi_id(session, name, city)
                if poi_id is None:
                    return
                session.add(
                    PoiReview(
                        id=uuid4(),
                        poi_id=poi_id,
                        device_id=review.get("device_id"),
                        rating=review.get("rating"),
                        tags=review.get("tags"),
                        body=review.get("text"),
                        visited_at=None,
                        source=review.get("source"),
                    )
                )
                session.commit()
        except Exception:
            logger.warning("poi_feedback: review flush failed", exc_info=True)


_store_singleton: PoiFeedbackStore | None = None


def get_poi_feedback_store() -> PoiFeedbackStore:
    """Process-wide lazy singleton; DB factory wired when available."""
    global _store_singleton
    if _store_singleton is None:
        from app.db import get_session_factory

        try:
            factory = get_session_factory()
        except Exception:
            factory = None
        _store_singleton = PoiFeedbackStore(session_factory=factory)
    return _store_singleton
