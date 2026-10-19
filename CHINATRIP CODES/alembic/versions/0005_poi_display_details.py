"""v2.4.4 §4: pois display details — address + opening hours.

用户拍板 2026-10-19: enrichment results are persisted in the pois table
and refreshed by the daily job (app.jobs.refresh_pois); planning reads
the store instead of fetching live.

Revision ID: w12_0005
Revises: w12_0004
Create Date: 2026-10-19

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0005"
down_revision: str | None = "w12_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pois ADD COLUMN address VARCHAR(200)")
    op.execute("ALTER TABLE pois ADD COLUMN opening_hours VARCHAR(500)")
    op.execute("ALTER TABLE pois ADD COLUMN hours_source VARCHAR(20)")
    op.execute("ALTER TABLE pois ADD COLUMN hours_updated_at TIMESTAMP")


def downgrade() -> None:
    op.execute("ALTER TABLE pois DROP COLUMN hours_updated_at")
    op.execute("ALTER TABLE pois DROP COLUMN hours_source")
    op.execute("ALTER TABLE pois DROP COLUMN opening_hours")
    op.execute("ALTER TABLE pois DROP COLUMN address")
