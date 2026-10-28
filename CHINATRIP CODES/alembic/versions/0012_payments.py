"""客户付款层 payments 表（DESIGN/PAYMENTS_PROGRESS.md，2026-10-25）.

公司↔客户收款：pay_now 结账 + save_method 存卡（token 化，原始卡号不落
库）。铁律 22 渠道 handoff 不变；铁律 23 refund_summary 恒有。业务热路径
是 SQLite write-through（app/services/payments.py PaymentStore），本迁移
保持 PG schema 对齐（换 PG 时同一套 ORM 可迁移）。

Revision ID: w12_0012
Revises: w12_0011
Create Date: 2026-10-25

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "w12_0012"
down_revision: str | None = "w12_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS payments (
            id VARCHAR(40) PRIMARY KEY,
            device_id VARCHAR(100) NOT NULL,
            username VARCHAR(100),
            kind VARCHAR(20) NOT NULL,
            amount_yuan NUMERIC(12,2),
            currency VARCHAR(8) NOT NULL DEFAULT 'cny',
            description TEXT,
            email VARCHAR(254),
            refund_summary TEXT,
            status VARCHAR(20) NOT NULL DEFAULT 'pending',
            provider VARCHAR(20) NOT NULL DEFAULT 'mock',
            provider_ref VARCHAR(255),
            charge_ref VARCHAR(255),
            customer_ref VARCHAR(255),
            payment_method_ref VARCHAR(255),
            saved_method_label VARCHAR(60),
            handoff_id VARCHAR(128),
            trip_item_id VARCHAR(128),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            paid_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_payments_device ON payments (device_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS payments")
