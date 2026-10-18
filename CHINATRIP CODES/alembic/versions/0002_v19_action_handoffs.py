"""v1.9 (design v2.0): action_handoffs — booking deeplink handoff trail

Revision ID: w12_0002
Revises: w12_0001
Create Date: 2026-10-18

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0002"
down_revision: str | None = "w12_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE action_handoffs (
            id UUID PRIMARY KEY,
            user_id UUID REFERENCES users(id),
            itinerary_id UUID REFERENCES itineraries(id),
            action_type VARCHAR(20) NOT NULL,
            channel VARCHAR(20) NOT NULL,
            deeplink TEXT NOT NULL,
            h5_fallback TEXT,
            status VARCHAR(20) DEFAULT 'opened',
            order_ref VARCHAR(100),
            refund_policy JSONB,
            refund_deadline TIMESTAMPTZ,
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE action_handoffs")
