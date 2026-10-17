"""w12 initial schema: users, geo pois, itineraries, paywall

Revision ID: w12_0001
Revises:
Create Date: 2026-10-17

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute(
        """
        CREATE TABLE users (
            id UUID PRIMARY KEY,
            region VARCHAR(10) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE pois (
            id UUID PRIMARY KEY,
            source VARCHAR(20) NOT NULL,
            source_poi_id VARCHAR(100) NOT NULL,
            city VARCHAR(50) NOT NULL,
            name_zh VARCHAR(200),
            name_en VARCHAR(200),
            category VARCHAR(50),
            status VARCHAR(20) DEFAULT 'active',
            location GEOGRAPHY(POINT, 4326),
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE (source, source_poi_id)
        )
        """
    )
    op.execute("CREATE INDEX idx_pois_location ON pois USING GIST (location)")
    op.execute("CREATE INDEX idx_pois_city ON pois (city)")
    op.execute(
        """
        CREATE TABLE poi_hours (
            id UUID PRIMARY KEY,
            poi_id UUID REFERENCES pois(id),
            rule_type VARCHAR(20) NOT NULL,
            payload JSONB NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE itineraries (
            id UUID PRIMARY KEY,
            user_id UUID REFERENCES users(id),
            cities TEXT[] NOT NULL,
            title VARCHAR(200),
            working_sync_version INT NOT NULL DEFAULT 1,
            active_snapshot_id UUID,
            status VARCHAR(20) DEFAULT 'draft',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE itinerary_snapshots (
            id UUID PRIMARY KEY,
            itinerary_id UUID REFERENCES itineraries(id),
            name VARCHAR(100),
            note TEXT,
            sync_version INT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE itinerary_days (
            id UUID PRIMARY KEY,
            itinerary_id UUID REFERENCES itineraries(id),
            snapshot_id UUID REFERENCES itinerary_snapshots(id),
            day INT NOT NULL,
            base_city VARCHAR(50) NOT NULL,
            UNIQUE (itinerary_id, day, snapshot_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE intercity_transfers (
            id UUID PRIMARY KEY,
            itinerary_id UUID REFERENCES itineraries(id),
            snapshot_id UUID REFERENCES itinerary_snapshots(id),
            day INT NOT NULL,
            seq INT NOT NULL DEFAULT 1,
            from_city VARCHAR(50),
            to_city VARCHAR(50),
            mode VARCHAR(20),
            UNIQUE (itinerary_id, day, seq, snapshot_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE itinerary_items (
            id UUID PRIMARY KEY,
            itinerary_id UUID REFERENCES itineraries(id),
            snapshot_id UUID REFERENCES itinerary_snapshots(id),
            day INT NOT NULL,
            poi_id UUID REFERENCES pois(id),
            position FLOAT NOT NULL,
            start_time TIME,
            end_time TIME,
            draft BOOLEAN DEFAULT TRUE
        )
        """
    )
    # PG requires the partition key (ts) inside the PK of a partitioned table.
    op.execute(
        """
        CREATE TABLE execution_events (
            id UUID NOT NULL,
            itinerary_id UUID REFERENCES itineraries(id),
            ts TIMESTAMP NOT NULL,
            type VARCHAR(40) NOT NULL,
            payload JSONB,
            PRIMARY KEY (id, ts)
        ) PARTITION BY RANGE (ts)
        """
    )
    op.execute(
        """
        CREATE TABLE execution_events_2026_10 PARTITION OF execution_events
            FOR VALUES FROM ('2026-10-01') TO ('2026-11-01')
        """
    )
    op.execute(
        """
        CREATE TABLE entitlements (
            id UUID PRIMARY KEY,
            user_id UUID REFERENCES users(id),
            itinerary_id UUID REFERENCES itineraries(id),
            product_id VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL,
            source VARCHAR(20) NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE iap_transactions (
            id UUID PRIMARY KEY,
            entitlement_id UUID REFERENCES entitlements(id),
            platform VARCHAR(10) NOT NULL,
            transaction_id VARCHAR(100) NOT NULL UNIQUE,
            receipt_payload JSONB,
            verified_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE paywall_rules (
            id UUID PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            enabled BOOLEAN DEFAULT FALSE,
            priority INT DEFAULT 100,
            trigger_event VARCHAR(40) NOT NULL,
            conditions JSONB,
            offer JSONB NOT NULL,
            caps JSONB,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE execution_events_2026_10")
    op.execute("DROP TABLE execution_events")
    op.execute("DROP TABLE paywall_rules")
    op.execute("DROP TABLE iap_transactions")
    op.execute("DROP TABLE entitlements")
    op.execute("DROP TABLE itinerary_items")
    op.execute("DROP TABLE intercity_transfers")
    op.execute("DROP TABLE itinerary_days")
    op.execute("DROP TABLE itinerary_snapshots")
    op.execute("DROP TABLE itineraries")
    op.execute("DROP TABLE poi_hours")
    op.execute("DROP TABLE pois")
    op.execute("DROP TABLE users")
    op.execute("DROP EXTENSION IF EXISTS postgis")
