"""v2.4 §4 (design v2.4): trip center agent — trip_items, user_profiles, link_history

Revision ID: w12_0003
Revises: w12_0002
Create Date: 2026-10-18

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0003"
down_revision: str | None = "w12_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE trip_items (
            id UUID PRIMARY KEY,
            itinerary_id UUID REFERENCES itineraries(id),
            user_id UUID REFERENCES users(id),
            name VARCHAR(200) NOT NULL,
            city VARCHAR(50),
            note TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'wishlist',
            source VARCHAR(20) NOT NULL,
            poi_id UUID REFERENCES pois(id),
            day INT,
            position FLOAT,
            booking_id UUID REFERENCES action_handoffs(id),
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE user_profiles (
            user_id UUID PRIMARY KEY REFERENCES users(id),
            profile JSONB NOT NULL,
            embedding JSONB,
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    # Production schema uses pgvector vector(1024); shipped as a JSONB
    # float-array placeholder because 0001 provisions only postgis and this
    # migration adds no extension dependency (mirrors how 0001 documented the
    # GCJ-02/WGS84 geometry twins — special types explained at the DDL site).
    op.execute(
        "COMMENT ON COLUMN user_profiles.embedding IS "
        "'pgvector vector(1024) in production; JSONB placeholder until the "
        "pgvector extension is provisioned'"
    )
    op.execute(
        """
        CREATE TABLE link_history (
            id UUID PRIMARY KEY,
            user_id UUID REFERENCES users(id),
            url TEXT NOT NULL,
            source VARCHAR(20) NOT NULL,
            origin VARCHAR(20),
            itinerary_id UUID REFERENCES itineraries(id),
            extract_id UUID,
            status VARCHAR(20) DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT NOW()
        )
        """
    )
    op.execute("ALTER TABLE action_handoffs ADD COLUMN source_channel VARCHAR(20)")
    op.execute(
        "COMMENT ON COLUMN action_handoffs.status IS "
        "'opened -> user_confirmed (user backfill) -> alliance_verified "
        "(affiliate order-sync match) -> settled (commission); "
        "returned (refund reverse)'"
    )


def downgrade() -> None:
    op.execute("COMMENT ON COLUMN action_handoffs.status IS NULL")
    op.execute("ALTER TABLE action_handoffs DROP COLUMN source_channel")
    op.execute("DROP TABLE link_history")
    op.execute("DROP TABLE user_profiles")
    op.execute("DROP TABLE trip_items")
