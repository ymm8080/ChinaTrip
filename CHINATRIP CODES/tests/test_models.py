"""Structural checks on ORM metadata and the initial migration DDL."""

from pathlib import Path

from geoalchemy2 import Geography
from sqlalchemy import ARRAY, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from app.models import Base

TABLE_NAMES = [
    "users",
    "pois",
    "poi_hours",
    "itineraries",
    "itinerary_snapshots",
    "itinerary_days",
    "intercity_transfers",
    "itinerary_items",
    "execution_events",
    "entitlements",
    "iap_transactions",
    "paywall_rules",
    "action_handoffs",
    "trip_items",
    "user_profiles",
    "link_history",
]

W12_TABLE_NAMES = TABLE_NAMES[:12]  # 0001 created 12; action_handoffs arrives in 0002

# 0003 (design v2.4 §4): trip center agent tables.
V24_TABLE_NAMES = TABLE_NAMES[-3:]

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0001_w12_initial.py"
)

MIGRATION_0002_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0002_v19_action_handoffs.py"
)

MIGRATION_0003_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0003_v24_trip_center_tables.py"
)


def unique_column_sets(table):
    return {
        frozenset(col.name for col in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_all_tables_present():
    assert set(TABLE_NAMES).issubset(Base.metadata.tables)


def test_pois_columns_exact():
    pois = Base.metadata.tables["pois"]
    assert set(pois.columns.keys()) == {
        "id",
        "source",
        "source_poi_id",
        "city",
        "name_zh",
        "name_en",
        "category",
        "status",
        "location",
        "wgs84_location",
        "updated_at",
    }


def test_pois_dual_coordinates_are_geography():
    pois = Base.metadata.tables["pois"]
    for col in ("location", "wgs84_location"):
        assert isinstance(pois.columns[col].type, Geography), col


def test_users_region_is_varchar_10():
    region = Base.metadata.tables["users"].columns["region"]
    assert isinstance(region.type, String)
    assert region.type.length == 10


def test_itineraries_cities_is_text_array():
    cities = Base.metadata.tables["itineraries"].columns["cities"]
    assert isinstance(cities.type, ARRAY)
    assert cities.nullable is False


def test_paywall_rules_offer_is_jsonb_not_null():
    offer = Base.metadata.tables["paywall_rules"].columns["offer"]
    assert isinstance(offer.type, JSONB)
    assert offer.nullable is False


def test_action_handoffs_columns_exact():
    handoffs = Base.metadata.tables["action_handoffs"]
    assert set(handoffs.columns.keys()) == {
        "id",
        "user_id",
        "itinerary_id",
        "action_type",
        "channel",
        "deeplink",
        "h5_fallback",
        "status",
        "order_ref",
        "source_channel",
        "refund_policy",
        "refund_deadline",
        "created_at",
        "updated_at",
    }


def test_action_handoffs_required_columns_not_null():
    handoffs = Base.metadata.tables["action_handoffs"]
    for col in ("action_type", "channel", "deeplink"):
        assert handoffs.columns[col].nullable is False, col


def test_action_handoffs_refund_policy_is_jsonb():
    refund_policy = Base.metadata.tables["action_handoffs"].columns["refund_policy"]
    assert isinstance(refund_policy.type, JSONB)
    assert refund_policy.nullable is True


def test_action_handoffs_refund_deadline_is_tz_aware():
    refund_deadline = Base.metadata.tables["action_handoffs"].columns["refund_deadline"]
    assert refund_deadline.type.timezone is True


def test_unique_constraints():
    tables = Base.metadata.tables
    assert frozenset({"source", "source_poi_id"}) in unique_column_sets(tables["pois"])
    assert frozenset({"itinerary_id", "day", "snapshot_id"}) in unique_column_sets(
        tables["itinerary_days"]
    )
    assert frozenset(
        {"itinerary_id", "day", "seq", "snapshot_id"}
    ) in unique_column_sets(tables["intercity_transfers"])
    assert frozenset({"transaction_id"}) in unique_column_sets(
        tables["iap_transactions"]
    )


def test_itinerary_snapshots_are_immutable():
    snapshots = Base.metadata.tables["itinerary_snapshots"]
    assert "created_at" in snapshots.columns
    assert "updated_at" not in snapshots.columns


def test_execution_events_composite_pk():
    events = Base.metadata.tables["execution_events"]
    assert [col.name for col in events.primary_key.columns] == ["id", "ts"]


def test_pois_gist_index():
    pois = Base.metadata.tables["pois"]
    location_indexes = [i for i in pois.indexes if i.name == "idx_pois_location"]
    assert location_indexes
    assert any(
        i.dialect_options["postgresql"]["using"] == "gist" for i in location_indexes
    )


def test_migration_ddl_contains_postgis_and_partitioning():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS postgis" in sql
    assert "PARTITION BY RANGE" in sql
    assert "PARTITION OF execution_events" in sql
    assert "PRIMARY KEY (id, ts)" in sql
    assert "wgs84_location GEOGRAPHY(POINT, 4326)" in sql


def test_migration_downgrade_drops_all_tables():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    downgrade_sql = sql.split("def downgrade", 1)[1]
    for name in W12_TABLE_NAMES:
        assert f"DROP TABLE {name}" in downgrade_sql, name


def test_migration_0002_creates_action_handoffs():
    sql = MIGRATION_0002_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "w12_0002"' in sql
    assert 'down_revision: str | None = "w12_0001"' in sql
    upgrade_sql = sql.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    for fragment in (
        "CREATE TABLE action_handoffs",
        "action_type VARCHAR(20) NOT NULL",
        "channel VARCHAR(20) NOT NULL",
        "deeplink TEXT NOT NULL",
        "status VARCHAR(20) DEFAULT 'opened'",
        "refund_policy JSONB",
        "refund_deadline TIMESTAMPTZ",
    ):
        assert fragment in upgrade_sql, fragment
    downgrade_sql = sql.split("def downgrade", 1)[1]
    assert "DROP TABLE action_handoffs" in downgrade_sql


def test_action_handoffs_source_channel_column():
    source_channel = Base.metadata.tables["action_handoffs"].columns["source_channel"]
    assert isinstance(source_channel.type, String)
    assert source_channel.type.length == 20
    assert source_channel.nullable is True


def test_trip_items_columns_exact():
    trip_items = Base.metadata.tables["trip_items"]
    assert set(trip_items.columns.keys()) == {
        "id",
        "itinerary_id",
        "user_id",
        "name",
        "city",
        "note",
        "status",
        "source",
        "poi_id",
        "day",
        "position",
        "booking_id",
        "created_at",
        "updated_at",
    }


def test_trip_items_status_defaults_to_wishlist():
    status = Base.metadata.tables["trip_items"].columns["status"]
    assert status.nullable is False
    assert status.server_default.arg.text == "'wishlist'"


def test_trip_items_foreign_keys():
    trip_items = Base.metadata.tables["trip_items"]

    def fk_targets(col):
        return {fk.target_fullname for fk in trip_items.columns[col].foreign_keys}

    assert fk_targets("itinerary_id") == {"itineraries.id"}
    assert fk_targets("user_id") == {"users.id"}
    assert fk_targets("poi_id") == {"pois.id"}
    assert fk_targets("booking_id") == {"action_handoffs.id"}


def test_user_profiles_pk_is_user_id_with_users_fk():
    profiles = Base.metadata.tables["user_profiles"]
    assert [col.name for col in profiles.primary_key.columns] == ["user_id"]
    assert {fk.target_fullname for fk in profiles.columns["user_id"].foreign_keys} == {
        "users.id"
    }


def test_user_profiles_profile_is_jsonb_not_null():
    profile = Base.metadata.tables["user_profiles"].columns["profile"]
    assert isinstance(profile.type, JSONB)
    assert profile.nullable is False


def test_user_profiles_embedding_is_jsonb_placeholder():
    embedding = Base.metadata.tables["user_profiles"].columns["embedding"]
    assert isinstance(embedding.type, JSONB)


def test_link_history_columns_exact():
    link_history = Base.metadata.tables["link_history"]
    assert set(link_history.columns.keys()) == {
        "id",
        "user_id",
        "url",
        "source",
        "origin",
        "itinerary_id",
        "extract_id",
        "status",
        "created_at",
    }


def test_link_history_status_defaults_to_pending():
    status = Base.metadata.tables["link_history"].columns["status"]
    assert status.nullable is True
    assert status.server_default.arg.text == "'pending'"


def test_migration_0003_creates_v24_tables():
    sql = MIGRATION_0003_PATH.read_text(encoding="utf-8")
    assert 'revision: str = "w12_0003"' in sql
    assert 'down_revision: str | None = "w12_0002"' in sql
    upgrade_sql = sql.split("def upgrade", 1)[1].split("def downgrade", 1)[0]
    for name in V24_TABLE_NAMES:
        assert f"CREATE TABLE {name}" in upgrade_sql, name
    for fragment in (
        "status VARCHAR(20) NOT NULL DEFAULT 'wishlist'",
        "booking_id UUID REFERENCES action_handoffs(id)",
        "profile JSONB NOT NULL",
        "embedding JSONB",
        "url TEXT NOT NULL",
        "status VARCHAR(20) DEFAULT 'pending'",
        "ALTER TABLE action_handoffs ADD COLUMN source_channel VARCHAR(20)",
    ):
        assert fragment in upgrade_sql, fragment
    downgrade_sql = sql.split("def downgrade", 1)[1]
    for name in reversed(V24_TABLE_NAMES):
        assert f"DROP TABLE {name}" in downgrade_sql, name
    assert "ALTER TABLE action_handoffs DROP COLUMN source_channel" in downgrade_sql


def test_migration_0003_documents_pgvector_placeholder():
    sql = MIGRATION_0003_PATH.read_text(encoding="utf-8")
    assert "pgvector vector(1024)" in sql
    assert "CREATE EXTENSION" not in sql  # no new extension dependency in 0003
