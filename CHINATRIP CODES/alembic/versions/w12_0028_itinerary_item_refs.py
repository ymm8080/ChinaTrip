"""itinerary_items 补「可回溯」列（2026-11-13，用户要求先想清楚缺什么）。

现有列已覆盖：日期 / 时段 / 名称 / 城市 / 时长 / 备选 1-3 / 品类 / 地址。
仍会丢的信息（实测）：
  * 点位在 plan 里的 item_id（v12 / hotel-night-3 …）——换点、钉住、删除都按它
    定位，库里没有就无法与 plan 对应；
  * POI 业务号（m1_xxx / 5a_299）——按名字回查 POIS 不稳（同名多地）；
  * TransferItem（航班/火车）没有 name，库里那一行是空的——需要起止城/班次；
  * 行的种类（景点/餐/酒店/演出/城际）只能靠 category 猜。

Revision ID: w12_0028
Revises: w12_0027
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "w12_0028"
down_revision: str | None = "w12_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("itinerary_items", sa.Column("item_ref", sa.String(64), nullable=True))
    op.add_column("itinerary_items", sa.Column("poi_ref", sa.String(64), nullable=True))
    op.add_column("itinerary_items", sa.Column("kind", sa.String(20), nullable=True))
    op.add_column("itinerary_items", sa.Column("from_city", sa.String(50), nullable=True))
    op.add_column("itinerary_items", sa.Column("to_city", sa.String(50), nullable=True))
    op.add_column(
        "itinerary_items", sa.Column("transport_no", sa.String(32), nullable=True)
    )


def downgrade() -> None:
    for col in (
        "transport_no",
        "to_city",
        "from_city",
        "kind",
        "poi_ref",
        "item_ref",
    ):
        op.drop_column("itinerary_items", col)
