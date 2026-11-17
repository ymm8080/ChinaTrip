# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\models.py"
t = io.open(p, encoding="utf-8", newline="").read()

def sub(old, new, n=1):
    global t
    c = t.count(old)
    assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub('''    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(\r
        UUID(as_uuid=True), ForeignKey("itinerary_snapshots.id")\r
    )\r
    day: Mapped[int] = mapped_column(Integer)\r
    poi_id: Mapped[uuid.UUID | None] = mapped_column(\r
''', '''    # 2026-11-14（用户拍板「TRIP HEADER/ITEM/心愿单/预订都要 USER ID 列，\r
    # 打开页面按 USER ID 出内容」）：明细行冗余归属键——不 JOIN 头表也能按\r
    # 用户直查；值由保存路径从头表带下来。\r
    owner_device_id: Mapped[str | None] = mapped_column(String(100))\r
    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)\r
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(\r
        UUID(as_uuid=True), ForeignKey("itinerary_snapshots.id")\r
    )\r
    day: Mapped[int] = mapped_column(Integer)\r
    poi_id: Mapped[uuid.UUID | None] = mapped_column(\r
''')

sub('''    user_id: Mapped[uuid.UUID | None] = mapped_column(\r
        UUID(as_uuid=True), ForeignKey("users.id")\r
    )\r
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(\r
        UUID(as_uuid=True), ForeignKey("itineraries.id")\r
    )\r
    action_type: Mapped[str] = mapped_column(\r
''', '''    user_id: Mapped[uuid.UUID | None] = mapped_column(\r
        UUID(as_uuid=True), ForeignKey("users.id")\r
    )\r
    # 2026-11-14（用户拍板「预订/代订埋点也要 USER ID 列」）：归属键用与本\r
    # 系统一致的字符串账号（owner_account_id=登录名/邮箱）+ 设备号；\r
    # users.id 外键留空（users 表非账号真源）。\r
    owner_device_id: Mapped[str | None] = mapped_column(String(100), index=True)\r
    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)\r
    itinerary_id: Mapped[uuid.UUID | None] = mapped_column(\r
        UUID(as_uuid=True), ForeignKey("itineraries.id")\r
    )\r
    action_type: Mapped[str] = mapped_column(\r
''')

sub('''    draft_session_id: Mapped[str | None] = mapped_column(String(64), index=True)\r
    user_id: Mapped[uuid.UUID | None] = mapped_column(\r
''', '''    draft_session_id: Mapped[str | None] = mapped_column(String(64), index=True)\r
    # 2026-11-14（用户拍板「心愿单/已排期也是 USER ID 的数据」）：登录账号\r
    # （用户名/邮箱字符串，与行程头 owner_account_id 同源）——打开行程中心\r
    # 按设备或账号出本用户的内容，换设备登录也能看到。\r
    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)\r
    user_id: Mapped[uuid.UUID | None] = mapped_column(\r
''')

io.open(p, "w", encoding="utf-8", newline="").write(t)
print("models ok")
