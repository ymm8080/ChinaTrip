# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\models.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old_lines, new_lines, n=1):
    global t
    old = NL.join(old_lines)
    new = NL.join(new_lines)
    c = t.count(old)
    assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub([
'    # 2026-11-14（用户拍板「TRIP HEADER/ITEM/心愿单/预订都要 USER ID 列，',
'    # 打开页面按 USER ID 出内容」）：明细行冗余归属键——不 JOIN 头表也能按',
'    # 用户直查；值由保存路径从头表带下来。',
'    owner_device_id: Mapped[str | None] = mapped_column(String(100))',
'    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)',
], [
'    # 2026-11-14（用户拍板「TRIP ITEM 也要 USER ID 列，打开页面按 USER ID',
'    # 出内容；不需要设备列」）：明细行冗余用户键——不 JOIN 头表也能按用户',
'    # 直查；值由保存路径从头表带下来。',
'    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)',
])

sub([
'    # 2026-11-14（用户拍板「预订/代订埋点也要 USER ID 列」）：归属键用与本',
'    # 系统一致的字符串账号（owner_account_id=登录名/邮箱）+ 设备号；',
'    # users.id 外键留空（users 表非账号真源）。',
'    owner_device_id: Mapped[str | None] = mapped_column(String(100), index=True)',
'    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)',
], [
'    # 2026-11-14（用户拍板「预订/代订埋点也要 USER ID 列，不需要设备列」）：',
'    # 归属键 = 登录账号字符串（owner_account_id=用户名/邮箱，与行程头同源）；',
'    # users.id 外键留空（users 表非账号真源）。',
'    owner_account_id: Mapped[str | None] = mapped_column(String(100), index=True)',
])

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("models ok")
