import uuid
from datetime import datetime, time

from geoalchemy2 import Geography, WKBElement
from sqlalchemy import (
    ARRAY,
    TIME,
    TIMESTAMP,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    region: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class Poi(Base):
    __tablename__ = "pois"
    __table_args__ = (
        UniqueConstraint("source", "source_poi_id"),
        Index("idx_pois_location", "location", postgresql_using="gist"),
        Index("idx_pois_city", "city"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    source_poi_id: Mapped[str] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(50))
    name_zh: Mapped[str | None] = mapped_column(String(200))
    name_en: Mapped[str | None] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str | None] = mapped_column(
        String(20), server_default=text("'active'")
    )
    location: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, nullable=True)
    )
    # v2.4.4: display details maintained by the daily refresh job
    # (app.jobs.refresh_pois); planning reads them, never fetches live.
    address: Mapped[str | None] = mapped_column(String(200))
    address_en: Mapped[str | None] = mapped_column(String(200))
    opening_hours: Mapped[str | None] = mapped_column(String(500))
    # 双语 P1.6：EN 营业时间（只填空；翻译较 zh 膨胀 2-3 倍故用 TEXT，0017）
    opening_hours_en: Mapped[str | None] = mapped_column(Text)
    hours_source: Mapped[str | None] = mapped_column(String(20))
    hours_updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    # v1.7: WGS84 twin of `location` (GCJ-02), written in pairs at ingest;
    # overseas map rendering (Phase 2) reads this to avoid GCJ-02 drift.
    wgs84_location: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, nullable=True)
    )
    # v2.5 POI 底库 (DESIGN §4.2): 铁律——外部源仅写骨架（名称/坐标/类别），
    # 时间敏感字段（hours/price/duration）只信高德/携程回源链。
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(300))
    rating: Mapped[float | None] = mapped_column(Numeric(3, 1))
    rating_source: Mapped[str | None] = mapped_column(String(20))
    tags: Mapped[list | None] = mapped_column(JSONB)
    tags_source: Mapped[str | None] = mapped_column(String(20))
    intro: Mapped[str | None] = mapped_column(Text)
    intro_source: Mapped[str | None] = mapped_column(String(20))
    # 双语 P1（DESIGN language_dual_system §5.2）：*_en 只填空，NULL 回退中文
    intro_en: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[list | None] = mapped_column(JSONB)
    photos_source: Mapped[str | None] = mapped_column(String(20))
    best_visit_time: Mapped[str | None] = mapped_column(
        String(10), server_default=text("'any'")
    )
    best_visit_time_source: Mapped[str | None] = mapped_column(String(20))
    suggested_duration_min: Mapped[int | None] = mapped_column(Integer)
    # source 升级为 amap（回源真相）后，origin 保留初始发现渠道。
    origin: Mapped[str | None] = mapped_column(String(20))
    # 规划引擎升级 0009（DESIGN planning_engine_upgrade_2026-10-24）：
    # A/B/C 组富化列——全部只填空/带溯源，时间敏感字段仍只信回源链。
    rating_count: Mapped[int | None] = mapped_column(Integer)
    review_tags: Mapped[list | None] = mapped_column(JSONB)
    review_tags_source: Mapped[str | None] = mapped_column(String(20))
    review_tags_en: Mapped[list | None] = mapped_column(JSONB)
    ticket_price_min: Mapped[int | None] = mapped_column(Integer)
    ticket_price_max: Mapped[int | None] = mapped_column(Integer)
    ticket_source: Mapped[str | None] = mapped_column(String(20))
    district: Mapped[str | None] = mapped_column(String(50))
    business_area: Mapped[str | None] = mapped_column(String(50))
    indoor: Mapped[str | None] = mapped_column(String(10))  # yes/no/partial
    rain_ok: Mapped[str | None] = mapped_column(String(10))  # yes/no/partial
    name_aliases: Mapped[list | None] = mapped_column(JSONB)
    duration_source: Mapped[str | None] = mapped_column(String(20))
    review_summary: Mapped[str | None] = mapped_column(Text)
    review_summary_source: Mapped[str | None] = mapped_column(String(20))
    # 双语 P1.5：口碑摘要 EN（只填空，回退中文）
    review_summary_en: Mapped[str | None] = mapped_column(Text)
    # G1（§14.3）：预约制门票约束——故宫/国博类提前 N 天 8:00 放票秒光，
    # 入境第一实操痛；booking_url 缺省落 affiliate 转链（Klook/Trip.com
    # 代抢 = 外国人标准解法）
    reservation_required: Mapped[bool | None] = mapped_column(Boolean)
    reservation_advance_days: Mapped[int | None] = mapped_column(Integer)
    booking_url: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class PoiHour(Base):
    __tablename__ = "poi_hours"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    poi_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pois.id")
    )
    rule_type: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict] = mapped_column(JSONB)


class Restaurant(Base):
    # v2.5 POI 底库：餐厅独立表（用户拍板 2026-10-23），骨架列与 pois 同构。
    __tablename__ = "restaurants"
    __table_args__ = (
        UniqueConstraint("source", "source_poi_id"),
        Index("idx_restaurants_location", "location", postgresql_using="gist"),
        Index("idx_restaurants_city", "city"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    source_poi_id: Mapped[str] = mapped_column(String(100))
    city: Mapped[str] = mapped_column(String(50))
    name_zh: Mapped[str | None] = mapped_column(String(200))
    name_en: Mapped[str | None] = mapped_column(String(200))
    cuisine: Mapped[str | None] = mapped_column(String(50))
    cuisine_en: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str | None] = mapped_column(
        String(20), server_default=text("'active'")
    )
    location: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, nullable=True)
    )
    wgs84_location: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, nullable=True)
    )
    address: Mapped[str | None] = mapped_column(String(200))
    address_en: Mapped[str | None] = mapped_column(String(200))
    opening_hours: Mapped[str | None] = mapped_column(String(500))
    # 双语 P1.6：EN 营业时间（只填空；翻译较 zh 膨胀 2-3 倍故用 TEXT，0017）
    opening_hours_en: Mapped[str | None] = mapped_column(Text)
    hours_source: Mapped[str | None] = mapped_column(String(20))
    hours_updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    phone: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(300))
    avg_cost: Mapped[float | None] = mapped_column(Numeric(10, 2))
    rating: Mapped[float | None] = mapped_column(Numeric(3, 1))
    rating_source: Mapped[str | None] = mapped_column(String(20))
    tags: Mapped[list | None] = mapped_column(JSONB)
    tags_source: Mapped[str | None] = mapped_column(String(20))
    intro: Mapped[str | None] = mapped_column(Text)
    intro_source: Mapped[str | None] = mapped_column(String(20))
    intro_en: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[list | None] = mapped_column(JSONB)
    photos_source: Mapped[str | None] = mapped_column(String(20))
    origin: Mapped[str | None] = mapped_column(String(20))
    # 规划引擎升级 0009：restaurants 专属富化列（C 组 + 评论域）。
    rating_count: Mapped[int | None] = mapped_column(Integer)
    review_tags: Mapped[list | None] = mapped_column(JSONB)
    review_tags_source: Mapped[str | None] = mapped_column(String(20))
    review_tags_en: Mapped[list | None] = mapped_column(JSONB)
    signature_dishes: Mapped[list | None] = mapped_column(JSONB)
    signature_dishes_en: Mapped[list | None] = mapped_column(JSONB)
    taste_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    env_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    service_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    price_level: Mapped[str | None] = mapped_column(String(10))  # <=50/50-100/...
    meal_periods: Mapped[list | None] = mapped_column(JSONB)  # 早茶/正餐/夜宵
    district: Mapped[str | None] = mapped_column(String(50))
    business_area: Mapped[str | None] = mapped_column(String(50))
    name_aliases: Mapped[list | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class PoiReview(Base):
    """自产评论（DESIGN §3.4 D1 / §4 互动闭环）。

    外部合法评论负责展示与初排；本表只收我们自己的用户（主要客户
    =外国入境游客，2026-10-24 定调）产生的评价——外国人视角的独家
    资产：外卡支付/英文服务/护照预订这类标签只有外国游客会给。
    """

    __tablename__ = "poi_reviews"
    __table_args__ = (
        Index("idx_poi_reviews_poi", "poi_id"),
        Index("idx_poi_reviews_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    poi_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("pois.id"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    device_id: Mapped[str | None] = mapped_column(String(64))
    rating: Mapped[int | None] = mapped_column(SmallInteger)  # 1-5
    tags: Mapped[list | None] = mapped_column(JSONB)  # 人多/出片/外卡支付...
    # 属性名必须避开 sqlalchemy.text——DB 列名仍为 text
    body: Mapped[str | None] = mapped_column("text", Text)
    visited_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    source: Mapped[str | None] = mapped_column(
        String(20)
    )  # post_visit | card_thumbs | chat
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class PoiStat(Base):
    """POI 行为热度聚合（DESIGN §3.4 D2，夜作业全量重建）。

    trip_items 每天产生的行为（wishlist=wish、scheduled/plan、unwanted
    =dislike）+ 卡片反馈/打卡/链接提及计数——竞品拿不到的自有热度源。
    """

    __tablename__ = "poi_stats"

    poi_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pois.id"), primary_key=True
    )
    wish_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    plan_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    visit_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    dislike_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    thumbs_up: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    xhs_mentions: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class WeatherReport(Base):
    # v2.5 参考数据域：城市天气快照（高德天气 API，上游中国气象局）。
    # latest-wins：每 (source, adcode, kind) 仅存最新一行——report_time 是
    # 高德侧数据时间（实况每小时更、预报每日约 8/11/18 时更），fetched_at
    # 是本侧拉取时间；不堆历史，见 DESIGN/database_design.md §6.2 矩阵行。
    __tablename__ = "weather_reports"
    __table_args__ = (
        UniqueConstraint("source", "adcode", "kind"),
        Index("idx_weather_reports_city", "city"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    adcode: Mapped[str] = mapped_column(String(10))
    city: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(10))  # live|forecast
    report_time: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    fetched_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class Itinerary(Base):
    __tablename__ = "itineraries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    cities: Mapped[list[str]] = mapped_column(ARRAY(Text))
    title: Mapped[str | None] = mapped_column(String(200))
    working_sync_version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    # No ForeignKey here: circular dependency with itinerary_snapshots.
    active_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str | None] = mapped_column(
        String(20), server_default=text("'draft'")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class ItinerarySnapshot(Base):
    __tablename__ = "itinerary_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    name: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text)
    sync_version: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class ItineraryDay(Base):
    __tablename__ = "itinerary_days"
    __table_args__ = (UniqueConstraint("itinerary_id", "day", "snapshot_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itinerary_snapshots.id")
    )
    day: Mapped[int] = mapped_column(Integer)
    base_city: Mapped[str] = mapped_column(String(50))


class IntercityTransfer(Base):
    __tablename__ = "intercity_transfers"
    __table_args__ = (UniqueConstraint("itinerary_id", "day", "seq", "snapshot_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itinerary_snapshots.id")
    )
    day: Mapped[int] = mapped_column(Integer)
    seq: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    from_city: Mapped[str | None] = mapped_column(String(50))
    to_city: Mapped[str | None] = mapped_column(String(50))
    mode: Mapped[str | None] = mapped_column(String(20))


class ItineraryItem(Base):
    __tablename__ = "itinerary_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itinerary_snapshots.id")
    )
    day: Mapped[int] = mapped_column(Integer)
    poi_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pois.id")
    )
    position: Mapped[float] = mapped_column(Float)
    start_time: Mapped[time | None] = mapped_column(TIME)
    end_time: Mapped[time | None] = mapped_column(TIME)
    draft: Mapped[bool | None] = mapped_column(Boolean, server_default=text("true"))


class ExecutionEvent(Base):
    # Real partitioning lives in the migration DDL (autogen can't express
    # PARTITION BY); PG also requires the partition key inside the PK.
    __tablename__ = "execution_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    ts: Mapped[datetime] = mapped_column(TIMESTAMP, primary_key=True)
    type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict | None] = mapped_column(JSONB)


class Entitlement(Base):
    __tablename__ = "entitlements"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    product_id: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class IapTransaction(Base):
    __tablename__ = "iap_transactions"
    __table_args__ = (UniqueConstraint("transaction_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    entitlement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("entitlements.id")
    )
    platform: Mapped[str] = mapped_column(String(10))
    transaction_id: Mapped[str] = mapped_column(String(100))
    receipt_payload: Mapped[dict | None] = mapped_column(JSONB)
    verified_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class PaywallRule(Base):
    __tablename__ = "paywall_rules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    enabled: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    priority: Mapped[int | None] = mapped_column(Integer, server_default=text("100"))
    trigger_event: Mapped[str] = mapped_column(String(40))
    conditions: Mapped[dict | None] = mapped_column(JSONB)
    offer: Mapped[dict] = mapped_column(JSONB)
    caps: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class ActionHandoff(Base):
    # v1.9 §6.11 (design v2.0): booking deeplink handoff trail — conversion
    # funnel + commission reconciliation. Iron rule 22: handoff only, never
    # transact on the user's behalf. refund_policy/refund_deadline per v1.9.4
    # (iron rule 23: no handoff without a refund-policy summary shown first).
    __tablename__ = "action_handoffs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    action_type: Mapped[str] = mapped_column(
        String(20)
    )  # hotel|flight|train|site_ticket
    channel: Mapped[str] = mapped_column(
        String(20)
    )  # ctrip|meituan|qunar|amap|rail12306
    deeplink: Mapped[str] = mapped_column(Text)
    h5_fallback: Mapped[str | None] = mapped_column(Text)
    # v2.4 state machine: opened -> user_confirmed (user backfills order_ref)
    # -> alliance_verified (affiliate order-sync match) -> settled (commission
    # payout); returned is the refund reverse path.
    status: Mapped[str | None] = mapped_column(
        String(20), server_default=text("'opened'")
    )
    order_ref: Mapped[str | None] = mapped_column(String(100))
    # v2.4: surface that issued this handoff (chat|wishlist|booking_cards).
    source_channel: Mapped[str | None] = mapped_column(String(20))
    # Snapshot of the refund rules shown to the user before handoff.
    refund_policy: Mapped[dict | None] = mapped_column(JSONB)
    refund_deadline: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class TripItem(Base):
    # v2.4 §4: user-owned trip card — the agent's read/write source of truth;
    # status lifecycle wishlist -> scheduled -> booked.
    __tablename__ = "trip_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(50))
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(20), server_default=text("'wishlist'")
    )  # wishlist|scheduled|booked
    source: Mapped[str] = mapped_column(String(20))  # manual|chat|paste|agent_recommend
    poi_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pois.id")
    )
    day: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[float | None] = mapped_column(Float)
    # v2.4.3: display fields kept from the plan (product rule 2026-10-19).
    address: Mapped[str | None] = mapped_column(String(200))
    opening_hours: Mapped[str | None] = mapped_column(String(200))
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("action_handoffs.id")
    )
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class UserProfile(Base):
    # v2.4 §4: per-user preference memory backing the trip-center agent.
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    profile: Mapped[dict] = mapped_column(JSONB)
    # Production schema is pgvector vector(1024); shipped as a JSONB float-array
    # placeholder because 0001 provisions only postgis and we add no extension
    # here (see 0003 migration column comment).
    embedding: Mapped[list[float] | None] = mapped_column(JSONB)
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class LinkHistory(Base):
    # v2.4 §4: every user-pasted / agent-recommended link and its parse outcome.
    __tablename__ = "link_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id")
    )
    url: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20))  # user_paste|agent_recommend
    origin: Mapped[str | None] = mapped_column(
        String(20)
    )  # chat|wishlist_boost|booking_cards
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    extract_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str | None] = mapped_column(
        String(20), server_default=text("'pending'")
    )  # pending|parsed|failed
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )


class Payment(Base):
    # 2026-10-25 客户付款层（DESIGN/PAYMENTS_PROGRESS.md）: company<->client
    # collection layer — pay_now checkout + save_method vault (tokenised;
    # raw card data never touches this server). Iron rule 22 channel handoff
    # stays untouched; iron rule 23 refund_summary always carried.
    # id is the service id "pay_<hex>" (String, not UUID) — the SQLite
    # write-through store (app/services/payments.py) is the hot path.
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(100))
    username: Mapped[str | None] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20))  # pay_now|save_method
    amount_yuan: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(8), server_default=text("'cny'"))
    description: Mapped[str | None] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(String(254))
    refund_summary: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(
        String(20), server_default=text("'pending'")
    )  # pending|succeeded|canceled|refunded|method_saved
    provider: Mapped[str | None] = mapped_column(
        String(20), server_default=text("'mock'")
    )  # mock|stripe
    provider_ref: Mapped[str | None] = mapped_column(String(255))
    charge_ref: Mapped[str | None] = mapped_column(String(255))
    customer_ref: Mapped[str | None] = mapped_column(String(255))
    payment_method_ref: Mapped[str | None] = mapped_column(String(255))
    saved_method_label: Mapped[str | None] = mapped_column(String(60))
    handoff_id: Mapped[str | None] = mapped_column(String(128))
    trip_item_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )
    paid_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
