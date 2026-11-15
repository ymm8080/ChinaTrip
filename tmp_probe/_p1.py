# -*- coding: utf-8 -*-
import io, os, re
base = r"D:\CHINATRIP\CHINATRIP CODES"
p = os.path.join(base, "alembic", "versions", "w12_0035_trip_item_drafts.py")
src = '''"""心愿单随行程走：未保存行程的心愿行是草稿（2026-11-14 用户拍板）。

ISSUE1：删行程 → 名下心愿单一并删除（不再退回心愿单）。
ISSUE2：行程没点「💾 保存行程」→ 心愿单不落库、不可见（行程中心与
wish_items 视图都不返回草稿行）。

* trip_items.draft_session_id：规划会话建行时写入的会话号；非空 = 草稿。
  保存行程（POST /plan/{sid}/save）时清空转正；删行程时按 itinerary_ref
  一并软删。
* 存量回填：itinerary_ref 指向不存在行程的行（历史未保存会话建的）标为
  legacy 草稿——看板/视图立刻干净，保留期后由清理任务物理删除。
* wish_items 视图过滤草稿行（视图口径 = 已保存行程的心愿单）。

Revision ID: w12_0035
Revises: w12_0034
Create Date: 2026-11-14
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "w12_0035"
down_revision: str | None = "w12_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEW_WITH_DRAFT_FILTER = """
        CREATE VIEW wish_items AS
        SELECT
            COALESCE(t.itinerary_ref, t.payload->>'itinerary_id') AS trip_id,
            COALESCE(t.payload->>'id', t.id::text) AS wish_id,
            t.name AS wish_name,
            t.created_at AS created_on,
            COALESCE(t.created_by, t.owner_device_id) AS created_by,
            COALESCE(
                i.title,
                array_to_string(i.cities, ' → '),
                t.payload->>'trip_name'
            )::varchar(200) AS trip_name,
            t.arranged AS arranged,
            CASE
                WHEN t.source IN ('chat', 'conversation') THEN 'conversation'
                WHEN t.source IN ('manual', 'paste') THEN 'manual'
                ELSE t.source
            END AS source,
            t.deletion_flag AS deletion_flag,
            t.deletion_date AS deletion_date,
            t.deletion_time AS deletion_time,
            t.deleted_by AS deleted_by,
            t.exclusion_flag AS exclusion_flag,
            t.kind AS kind,
            t.duration_minutes AS duration_minutes,
            t.must_visit AS must_visit,
            t.pinned AS pinned,
            t.tier AS tier,
            t.site_rank AS site_rank,
            t.latitude AS latitude,
            t.longitude AS longitude,
            t.rain_ok AS rain_ok,
            t.planned_date AS planned_date,
            t.start_time AS start_time,
            t.end_time AS end_time,
            t.raw_command AS raw_command
        FROM trip_items t
        LEFT JOIN itineraries i ON i.id = t.itinerary_id
        WHERE t.draft_session_id IS NULL
"""

VIEW_PLAIN = VIEW_WITH_DRAFT_FILTER.replace(
    "        WHERE t.draft_session_id IS NULL\n", ""
)


def upgrade() -> None:
    op.add_column(
        "trip_items", sa.Column("draft_session_id", sa.String(64), nullable=True)
    )
    op.create_index(
        "ix_trip_items_draft_session_id", "trip_items", ["draft_session_id"]
    )
    # 存量：挂在不存在的行程上的行 = 历史「没保存行程」留在库里的心愿行。
    # booked 例外（真实订单不是草稿）；软删行不动（审计已在）。
    op.execute(
        """
        UPDATE trip_items t
           SET draft_session_id = 'legacy:' || t.itinerary_ref
         WHERE t.itinerary_ref IS NOT NULL
           AND t.deletion_flag = false
           AND t.status <> 'booked'
           AND NOT EXISTS (
               SELECT 1 FROM itineraries i
                WHERE i.plan->>'itinerary_id' = t.itinerary_ref
           )
        """
    )
    op.execute("DROP VIEW IF EXISTS wish_items")
    op.execute(VIEW_WITH_DRAFT_FILTER)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS wish_items")
    op.execute(VIEW_PLAIN)
    op.drop_index("ix_trip_items_draft_session_id", table_name="trip_items")
    op.drop_column("trip_items", "draft_session_id")
'''
with io.open(p, "w", encoding="utf-8", newline="\n") as f:
    f.write(src)
print("wrote", p, len(src))

# models.py: add column after itinerary_id FK block
mp = os.path.join(base, "app", "models.py")
text = io.open(mp, encoding="utf-8", newline="").read()
old = '''    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(\r
        UUID(as_uuid=True), ForeignKey("itineraries.id")\r
    )\r
'''
new = old + '''    # 2026-11-14（用户拍板「没保存行程，心愿单就不该保存」）：规划会话建行\r
    # 时写入会话号——非空 = 草稿，看板/心愿单视图不返回；点「💾 保存行程」\r
    # 时清空转正，删行程时按 itinerary_ref 一并软删。\r
    draft_session_id: Mapped[str | None] = mapped_column(String(64), index=True)\r
'''
assert text.count(old) == 1, text.count(old)
text = text.replace(old, new, 1)
io.open(mp, "w", encoding="utf-8", newline="").write(text)
print("models patched")
