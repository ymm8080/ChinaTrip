"""G1 预约制门票约束（DESIGN §14.3-G1，2026-10-25）.

pois +3 列：reservation_required / reservation_advance_days /
booking_url。名单 v0 人工录入 top 预约制场馆（数十家），携程 sight 页
「需预约」标识回源补量后续接入。

Revision ID: w12_0010
Revises: w12_0009
Create Date: 2026-10-25

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0010"
down_revision: str | None = "w12_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE pois ADD COLUMN reservation_required BOOLEAN")
    op.execute("ALTER TABLE pois ADD COLUMN reservation_advance_days INTEGER")
    op.execute("ALTER TABLE pois ADD COLUMN booking_url VARCHAR(500)")


def downgrade() -> None:
    op.execute("ALTER TABLE pois DROP COLUMN IF EXISTS booking_url")
    op.execute("ALTER TABLE pois DROP COLUMN IF EXISTS reservation_advance_days")
    op.execute("ALTER TABLE pois DROP COLUMN IF EXISTS reservation_required")
