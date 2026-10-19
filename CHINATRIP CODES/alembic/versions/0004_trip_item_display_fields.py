"""v2.4.3 §4: trip_items display fields — address + opening_hours.

Every VisitItem already carries its concrete address and opening hours
(product rule 2026-10-19); the trip center must keep them when a planned
stop becomes a wishlist item, and the manual form may supply them.

Revision ID: w12_0004
Revises: w12_0003
Create Date: 2026-10-19

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0004"
down_revision: str | None = "w12_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE trip_items ADD COLUMN address VARCHAR(200)")
    op.execute("ALTER TABLE trip_items ADD COLUMN opening_hours VARCHAR(200)")


def downgrade() -> None:
    op.execute("ALTER TABLE trip_items DROP COLUMN opening_hours")
    op.execute("ALTER TABLE trip_items DROP COLUMN address")
