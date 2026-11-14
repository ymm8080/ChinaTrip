import uuid
from datetime import date, datetime, time

from geoalchemy2 import Geography, WKBElement
from sqlalchemy import (
    ARRAY,
    TIME,
    TIMESTAMP,
    BigInteger,
    Boolean,
    Date,
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
    tags: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    tags_source: Mapped[str | None] = mapped_column(String(20))
    intro: Mapped[str | None] = mapped_column(Text)
    intro_source: Mapped[str | None] = mapped_column(String(20))
    # 双语 P1（DESIGN language_dual_system §5.2）：*_en 只填空，NULL 回退中文
    intro_en: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    photos_source: Mapped[str | None] = mapped_column(String(20))
    # 照片回源元数据（DESIGN poi_photos_functional_design §3-F2/F4，
    # 0020）：fetched_at 是 24h 点击冷却键——尝试即落戳（拉空也落），
    # photos 本体仍只填空；fetch_fail 由死图上报端点累加。
    photos_fetched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    photos_fetch_fail: Mapped[int] = mapped_column(Integer, server_default=text("0"))
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
    review_tags: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    review_tags_source: Mapped[str | None] = mapped_column(String(20))
    review_tags_en: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    ticket_price_min: Mapped[int | None] = mapped_column(Integer)
    ticket_price_max: Mapped[int | None] = mapped_column(Integer)
    ticket_source: Mapped[str | None] = mapped_column(String(20))
    district: Mapped[str | None] = mapped_column(String(50))
    business_area: Mapped[str | None] = mapped_column(String(50))
    indoor: Mapped[str | None] = mapped_column(String(10))  # yes/no/partial
    rain_ok: Mapped[str | None] = mapped_column(String(10))  # yes/no/partial
    name_aliases: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
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
    # 用户可选二级标签（DESIGN user_tag_two_level_2026-11-10 §一，w12_0022）：
    # 一级 7 族 × 二级 25 组受控词表。映射唯一来源
    # app/services/poi_tag_selector.py（规则级联 + review 粗词碰撞消解；
    # 类目命中恒保留封顶、定族优先），由 app/jobs/backfill_poi_user_tags.py
    # 只填空回填；hotel/food/transport/category=None 服务类行恒空，
    # 未命中不猜（留空）。
    user_family: Mapped[str | None] = mapped_column(String(50))
    user_groups: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    # v2.6 TripAdvisor (Terra) 富化列（2026-11-14，w12_0032）：1000 次免费
    # 配额 = 1000 次 GET /locations/{id} 详情调用，一次拿全一个地点的 TA
    # 反馈。ta_location_id 映射走免费通道（搜索引擎解析公开 URL 的 d(\d+)，
    # 已用故宫 d319086 验证）。全部只填空；时间敏感字段真相仍归高德/携程
    # 回源链——ta_opening_hours / ta_suggested_duration_min 只做校验/补空/
    # 展示参考，绝不回写主列；ta_rating 与主 rating 分列避免互踩。
    ta_location_id: Mapped[str | None] = mapped_column(String(20))
    ta_geo_id: Mapped[str | None] = mapped_column(String(20))
    ta_status: Mapped[str | None] = mapped_column(String(20))  # OPEN / CLOSED
    ta_url: Mapped[str | None] = mapped_column(String(500))
    ta_rating: Mapped[float | None] = mapped_column(Numeric(3, 1))
    ta_opening_hours: Mapped[str | None] = mapped_column(String(500))
    ta_suggested_duration_min: Mapped[int | None] = mapped_column(Integer)
    # TA 英文简介（descriptions 默认 locale，TA 数据全取英文）——
    # intro_en 只填空来源之一
    ta_intro_en: Mapped[str | None] = mapped_column(Text)
    # 详情拉取时间——配额记账键（每 POI 一次 /locations/{id}）
    ta_fetched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
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
    payload: Mapped[dict] = mapped_column(JSONB(none_as_null=True))


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
    # 用户可选二级标签（DESIGN user_tag_two_level_2026-11-10 §二）：
    # cuisine 575 原值粗化 → family(6)/group(21)，推导列，原值列不动。
    # 映射唯一来源 app/services/cuisine_taxonomy.py，回填走
    # app/jobs/backfill_cuisine_group.py（fill-empty-only）。
    cuisine_family: Mapped[str | None] = mapped_column(String(50))
    cuisine_group: Mapped[str | None] = mapped_column(String(50))
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
    tags: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    tags_source: Mapped[str | None] = mapped_column(String(20))
    intro: Mapped[str | None] = mapped_column(Text)
    intro_source: Mapped[str | None] = mapped_column(String(20))
    intro_en: Mapped[str | None] = mapped_column(Text)
    photos: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    photos_source: Mapped[str | None] = mapped_column(String(20))
    # 同 pois（0020）：回源冷却戳 + 死图计数，语义见 Poi 侧注释。
    photos_fetched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    photos_fetch_fail: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    origin: Mapped[str | None] = mapped_column(String(20))
    # v2.6 TripAdvisor (Terra) 富化列（2026-11-14，w12_0034）：与 pois.ta_*
    # 完全同款 9 列（语义见 Poi 侧注释），餐厅独立底库同批走猫途鹰免费
    # 映射 + 详情拉取。全部只填空；时间敏感真相仍归高德/携程回源链。
    ta_location_id: Mapped[str | None] = mapped_column(String(20))
    ta_geo_id: Mapped[str | None] = mapped_column(String(20))
    ta_status: Mapped[str | None] = mapped_column(String(20))  # OPEN / CLOSED
    ta_url: Mapped[str | None] = mapped_column(String(500))
    ta_rating: Mapped[float | None] = mapped_column(Numeric(3, 1))
    ta_intro_en: Mapped[str | None] = mapped_column(Text)
    ta_opening_hours: Mapped[str | None] = mapped_column(String(500))
    ta_suggested_duration_min: Mapped[int | None] = mapped_column(Integer)
    # 详情拉取时间——配额记账键（每餐厅一次 /locations/{id}）
    ta_fetched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    # 规划引擎升级 0009：restaurants 专属富化列（C 组 + 评论域）。
    rating_count: Mapped[int | None] = mapped_column(Integer)
    review_tags: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    review_tags_source: Mapped[str | None] = mapped_column(String(20))
    review_tags_en: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    signature_dishes: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    signature_dishes_en: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    taste_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    env_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    service_score: Mapped[float | None] = mapped_column(Numeric(3, 1))
    price_level: Mapped[str | None] = mapped_column(String(10))  # <=50/50-100/...
    # 早茶/正餐/夜宵
    meal_periods: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    district: Mapped[str | None] = mapped_column(String(50))
    business_area: Mapped[str | None] = mapped_column(String(50))
    name_aliases: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
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
    # 人多/出片/外卡支付...
    tags: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
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


class TripadvisorLocation(Base):
    """TripAdvisor (Terra) 地点详情原始镜像（2026-11-14 定调，w12_0033）。

    1000 次免费配额 = 1000 次 GET /locations/{id}（默认 locale 全英文）。
    响应整条入 payload（JSONB 留档，与 trip_items.payload 同惯例），常用
    字段提取成列便于查询。映射关系：pois.ta_location_id 正向引用本表
    location_id；本表 poi_id 反向引用（补数据/核对用）。纯镜像表——
    规划侧只读 pois.ta_*，本表不回填任何主列。
    """

    __tablename__ = "tripadvisor_locations"
    __table_args__ = (
        Index("idx_ta_locations_poi", "poi_id"),
        Index("idx_ta_locations_geo", "geo_id"),
    )

    # TA 地点 ID（公开 URL d(\d+)，如故宫 319086）——自然主键
    location_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # 反向映射：已归属的 POI（未映射为 NULL）
    poi_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pois.id")
    )
    # 整条 API 响应留档（names/descriptions/addresses/urls/opening_hours/
    # traveler_ratings 全量，含 breakdowns、language_counts 等未提列字段）
    payload: Mapped[dict] = mapped_column(JSONB)

    # --- 提取列（payload 的查询友好投影） -------------------------------
    geo_id: Mapped[int | None] = mapped_column(BigInteger)
    geo: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str | None] = mapped_column(String(20))  # OPEN / CLOSED
    name_en: Mapped[str | None] = mapped_column(String(200))
    intro_en: Mapped[str | None] = mapped_column(Text)
    address_en: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    phone: Mapped[str | None] = mapped_column(String(50))
    website_official: Mapped[str | None] = mapped_column(String(300))
    rating: Mapped[float | None] = mapped_column(Numeric(3, 1))
    rating_count: Mapped[int | None] = mapped_column(Integer)
    photos_total_count: Mapped[int | None] = mapped_column(Integer)
    opening_hours_formatted: Mapped[str | None] = mapped_column(String(500))
    # TA 原始值（单位：小时）；换算分钟在读取侧做
    recommended_visit_length: Mapped[int | None] = mapped_column(Integer)

    # fetched_at 配额记账（每 POI 一次）；updated_at latest-wins 更新戳
    fetched_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
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
    payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
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
    # v2.5.2（2026-10-25）：H5 行程状态落 PG——plan 是 ItineraryRecord 整体
    # 文档（ItineraryPlan + snapshots 分存 snapshots 表）；cities 列喂
    # weather.trip_cities，owner/share 列喂设备/账号归属与分享查询。
    plan: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    owner_device_id: Mapped[str | None] = mapped_column(String(100), index=True)
    # 账号名字符串（SQLite accounts 域），不是 users.id 外键——账号仍留 SQLite。
    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)
    share_enabled: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false")
    )
    share_token: Mapped[str | None] = mapped_column(String(64))
    # 2026-11-13（用户拍板 trip HEADER：CREATION DATE / CREATOR / DELETION
    # FLAG / TRIP ID / TRIP NAME / LAST CHANGE DATE+TIME）：软删标记、创建人、
    # 最后变更时刻。title=行程名，created_at=创建日期，owner_*=归属。
    is_deleted: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    deleted_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    creator_name: Mapped[str | None] = mapped_column(String(100))
    last_changed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True))
    # 2026-11-13（用户拍板 HEADER 列）：起始/结束城市、旅行城市一/二
    # 与各自天数、旅行开始日期。
    start_city: Mapped[str | None] = mapped_column(String(50))
    end_city: Mapped[str | None] = mapped_column(String(50))
    dest_city_1: Mapped[str | None] = mapped_column(String(50))
    dest_days_1: Mapped[int | None] = mapped_column(Integer)
    dest_city_2: Mapped[str | None] = mapped_column(String(50))
    dest_days_2: Mapped[int | None] = mapped_column(Integer)
    travel_start_date: Mapped[date | None] = mapped_column(Date)


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
    # 快照冻结的完整 ItineraryPlan 文档（restore 的数据源）
    plan: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


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
    # 2026-11-13（用户拍板「TRIP 详情数据库：EACH DATE AND TIME AND SITES,
    # ALTERNATIVE INFORMATION」）：点位名/城/类别/地址/备选一并落库。
    name: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(50))
    category: Mapped[str | None] = mapped_column(String(40))
    address: Mapped[str | None] = mapped_column(String(200))
    alternatives: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    # 2026-11-13（用户拍板明细列：DURATION / SCHEDULE DATE /
    # ALTERNATIVE 1-3）：时长、具体日期、备选名单独成列，方便查询。
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    schedule_date: Mapped[date | None] = mapped_column(Date)
    alt1: Mapped[str | None] = mapped_column(String(200))
    alt2: Mapped[str | None] = mapped_column(String(200))
    alt3: Mapped[str | None] = mapped_column(String(200))
    # 2026-11-13（用户「先想清楚还缺什么」）：可回溯列——plan item_id /
    # POI 业务号 / 行种类 / 城际段起止城与班次（transfer 行没有 name）。
    item_ref: Mapped[str | None] = mapped_column(String(64))
    poi_ref: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str | None] = mapped_column(String(20))
    from_city: Mapped[str | None] = mapped_column(String(50))
    to_city: Mapped[str | None] = mapped_column(String(50))
    transport_no: Mapped[str | None] = mapped_column(String(32))
    # 2026-11-13：VisitItem/酒店/交通/餐卡全量留档（整条 item dump）
    payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    pinned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    must_visit: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    tier: Mapped[int | None] = mapped_column(SmallInteger)
    site_rank: Mapped[int | None] = mapped_column(SmallInteger)
    note: Mapped[str | None] = mapped_column(Text)
    seq: Mapped[int | None] = mapped_column(Integer)
    # 2026-11-13（用户「VisitItem/酒店/交通/餐卡都要在详情表里」）：
    # 各类实体自己的业务字段（卡片文案之外的真身）。
    meal_slot: Mapped[str | None] = mapped_column(String(16))
    transport_mode: Mapped[str | None] = mapped_column(String(16))
    hotel_name: Mapped[str | None] = mapped_column(String(200))
    placeholder: Mapped[bool | None] = mapped_column(
        Boolean, server_default=text("false")
    )


class ItineraryChangeLog(Base):
    """每次「💾 保存行程」的变更日志（2026-11-13 用户拍板）。

    USER / USER NAME / CHANGES ——设备、账号、变更人与逐条 diff 全落库，
    供行程中心审计与回放。"""

    __tablename__ = "itinerary_change_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    itinerary_ref: Mapped[str | None] = mapped_column(String(64))
    owner_device_id: Mapped[str | None] = mapped_column(String(100))
    owner_account_id: Mapped[str | None] = mapped_column(String(100))
    actor_name: Mapped[str | None] = mapped_column(String(100))
    changed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True), server_default=text("NOW()")
    )
    sync_version: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    changes: Mapped[list | None] = mapped_column(JSONB(none_as_null=True))
    snapshot_id: Mapped[str | None] = mapped_column(String(64))


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
    payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


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
    receipt_payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
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
    conditions: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    offer: Mapped[dict] = mapped_column(JSONB(none_as_null=True))
    caps: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
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
    refund_policy: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
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
    # 2026-11-13（用户拍板「心愿单/已排期/不想去/已订 都应该是数据库的
    # 数据」）：行归属设备 + 业务行程号原样入库（itinerary_id 是 uuid
    # 外键，未保存的工作行程没有对应行，FK 落不了；ref 列让挂靠/无挂靠
    # 在库里可查、可 JOIN）。
    owner_device_id: Mapped[str | None] = mapped_column(String(64), index=True)
    itinerary_ref: Mapped[str | None] = mapped_column(String(64), index=True)
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
    # 心愿单数据库化（2026-11-13 用户拍板）：CREATED BY / ARRANGED /
    # 删除审计 / EXCLUSION 都是数据库事实（wish_items 视图直接可查）。
    created_by: Mapped[str | None] = mapped_column(String(64))
    arranged: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    exclusion_flag: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    deletion_flag: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    deletion_date: Mapped[date | None] = mapped_column(Date)
    deletion_time: Mapped[time | None] = mapped_column(TIME)
    deleted_by: Mapped[str | None] = mapped_column(String(64))
    # 规划字段（2026-11-13）：点位类型/时长/必去/钉住/名录档/坐标/具体
    # 日期时刻/雨天属性/用户原话——都是规划器 VisitItem 上的决策输入。
    kind: Mapped[str | None] = mapped_column(String(20))
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    must_visit: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    pinned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    tier: Mapped[int | None] = mapped_column(SmallInteger)
    site_rank: Mapped[int | None] = mapped_column(SmallInteger)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    planned_date: Mapped[date | None] = mapped_column(Date)
    start_time: Mapped[time | None] = mapped_column(TIME)
    end_time: Mapped[time | None] = mapped_column(TIME)
    raw_command: Mapped[str | None] = mapped_column(String(1000))
    # rain_ok 来自 POIS（室内/露天），天气本身每日刷新不入库
    rain_ok: Mapped[str | None] = mapped_column(String(10))
    # 心愿单条目全量文档（dict 原样，含自由字符串 id）；列化的字段只是
    # 给 PG 侧查询用的投影（trip_cities 按 city 扫）
    payload: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))


class ItineraryImport(Base):
    # 行程导入流水（2026-10-31，行程页 📥 上传生成行程单）：id = 文件ID
    # （imp_<hex> 的 UUID 本体，每次导入全新、同一文件重复导入不共用）。
    # audit/排障用——app 无读路径，写入失败只告警不阻断导入主流程。
    __tablename__ = "itinerary_imports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("itineraries.id")
    )
    file_name: Mapped[str | None] = mapped_column(String(255))
    ext: Mapped[str | None] = mapped_column(String(20))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    text_chars: Mapped[int | None] = mapped_column(Integer)
    # previewed | confirmed | failed
    status: Mapped[str] = mapped_column(String(20), server_default=text("'previewed'"))
    error: Mapped[str | None] = mapped_column(Text)
    text_preview: Mapped[str | None] = mapped_column(Text)
    owner_device_id: Mapped[str | None] = mapped_column(String(100))
    owner_account_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP, server_default=text("NOW()")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)


class UserProfile(Base):
    # v2.4 §4: per-user preference memory backing the trip-center agent.
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    profile: Mapped[dict] = mapped_column(JSONB(none_as_null=True))
    # Production schema is pgvector vector(1024); shipped as a JSONB float-array
    # placeholder because 0001 provisions only postgis and we add no extension
    # here (see 0003 migration column comment).
    embedding: Mapped[list[float] | None] = mapped_column(JSONB(none_as_null=True))
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
