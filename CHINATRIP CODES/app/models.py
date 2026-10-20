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
    opening_hours: Mapped[str | None] = mapped_column(String(500))
    hours_source: Mapped[str | None] = mapped_column(String(20))
    hours_updated_at: Mapped[datetime | None] = mapped_column(TIMESTAMP)
    # v1.7: WGS84 twin of `location` (GCJ-02), written in pairs at ingest;
    # overseas map rendering (Phase 2) reads this to avoid GCJ-02 drift.
    wgs84_location: Mapped[WKBElement | None] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, nullable=True)
    )
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
