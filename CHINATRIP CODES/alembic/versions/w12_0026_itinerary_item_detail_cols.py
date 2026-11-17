"""itinerary_items 明细补齐：时长 / 日程日期 / 备选 1-3（2026-11-13 用户拍板）。

「TRIP 还需要有详情数据库，WHICH STORED EACH DATE AND TIME AND SITES NAME,
DURATION, SCHEDULE DATE, SCHEDULE TIME, ALTERNATIVE 1, ALTERNATIVE2,
ALTERNATIVE3.」

* duration_minutes：该点位停留时长
* schedule_date：落到具体日期（plan.start_date + day-1）
* alt1/alt2/alt3：同级备选名（alternatives JSONB 仍保留全量细节）

Revision ID: w12_0026
Revises: w12_0025
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "w12_0026"
down_revision: str | None = "w12_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "itinerary_items", sa.Column("duration_minutes", sa.Integer(), nullable=True)
    )
    op.add_column("itinerary_items", sa.Column("schedule_date", sa.Date(), nullable=True))
    for col in ("alt1", "alt2", "alt3"):
        op.add_column("itinerary_items", sa.Column(col, sa.String(200), nullable=True))


def downgrade() -> None:
    for col in ("alt3", "alt2", "alt1", "schedule_date", "duration_minutes"):
        op.drop_column("itinerary_items", col)
