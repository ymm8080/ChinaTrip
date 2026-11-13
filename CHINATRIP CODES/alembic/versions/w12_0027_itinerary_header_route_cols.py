"""itineraries 头补充：起始/结束城市、目的地城市与天数、旅行开始日期。

「TRIP HEADER 还要有 start date 起始城市 结束城市 旅行城市一，日期数，
旅行城市二，日期数，旅行开始日期。」

Revision ID: w12_0027
Revises: w12_0026
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "w12_0027"
down_revision: str | None = "w12_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for col in ("start_city", "end_city", "dest_city_1", "dest_city_2"):
        op.add_column("itineraries", sa.Column(col, sa.String(50), nullable=True))
    for col in ("dest_days_1", "dest_days_2"):
        op.add_column("itineraries", sa.Column(col, sa.Integer(), nullable=True))
    op.add_column(
        "itineraries", sa.Column("travel_start_date", sa.Date(), nullable=True)
    )


def downgrade() -> None:
    for col in (
        "travel_start_date",
        "dest_days_2",
        "dest_days_1",
        "dest_city_2",
        "dest_city_1",
        "end_city",
        "start_city",
    ):
        op.drop_column("itineraries", col)
