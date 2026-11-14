"""itinerary_items 区分实体类型：酒店 / 交通 / 餐卡 / 演出 / 景点。

「VisitItem/酒店/交通/餐卡 WE ALSO NEED TO HV THEM IN TRIP 详情 TABLE」

现状：四类都已入库（kind 列），但只能看到卡片文案，缺各自的业务字段：
  * 酒店：卡片名是「🏨 酒店入住（放行李·休整）」，真正的酒店名没有单独列；
  * 交通：只有 transport_no，没有 transport_mode（flight/train）；
  * 餐卡：分不出早/午/下午茶/晚，也分不出「自由安排」占位卡；
  * 占位卡（无 POI 的空壳）需要一个显式标记，详情页才能灰显。

Revision ID: w12_0030
Revises: w12_0029
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "w12_0030"
down_revision: str | None = "w12_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("itinerary_items", sa.Column("meal_slot", sa.String(16), nullable=True))
    op.add_column(
        "itinerary_items", sa.Column("transport_mode", sa.String(16), nullable=True)
    )
    op.add_column(
        "itinerary_items", sa.Column("hotel_name", sa.String(200), nullable=True)
    )
    op.add_column(
        "itinerary_items",
        sa.Column("placeholder", sa.Boolean(), server_default=sa.text("false")),
    )


def downgrade() -> None:
    for col in ("placeholder", "hotel_name", "transport_mode", "meal_slot"):
        op.drop_column("itinerary_items", col)
