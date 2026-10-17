"""Structural checks on ORM metadata and the initial migration DDL."""

from pathlib import Path

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
]

MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0001_w12_initial.py"
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
        "updated_at",
    }


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


def test_migration_downgrade_drops_all_tables():
    sql = MIGRATION_PATH.read_text(encoding="utf-8")
    downgrade_sql = sql.split("def downgrade", 1)[1]
    for name in TABLE_NAMES:
        assert f"DROP TABLE {name}" in downgrade_sql, name
