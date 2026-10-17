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
