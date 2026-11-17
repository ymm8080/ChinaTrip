# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\alembic\versions\w12_0036_user_id_keying.py"
raw = io.open(p, encoding="utf-8", newline="").read()
lines = raw.splitlines()
out = []
skip_next_addcol = None
for line in lines:
    if '本系统的用户键 = 登录账号字符串（owner_account_id=用户名/邮箱，与行程头' in line:
        out.append('本系统的用户键 = 登录账号字符串（owner_account_id=用户名/邮箱，与行程头')
        continue
    if '同源）+ 浏览器设备号（owner_device_id）；users.id 外键留空（users 表不是' in line:
        out.append('同源）；不加设备列（users.id 外键留空，users 表不是账号真源）。')
        continue
    if line.strip() == '* itinerary_items（TRIP ITEM 明细）：+ owner_device_id / owner_account_id':
        out.append('* itinerary_items（TRIP ITEM 明细）：+ owner_account_id')
        continue
    if line.strip() == '* action_handoffs（BOOKING/预订埋点）：+ owner_device_id / owner_account_id':
        out.append('* action_handoffs（BOOKING/预订埋点）：+ owner_account_id')
        continue
    if line.strip() == '# 头表 owner_* 是权威。':
        out.append('# 头表 owner_account_id 是权威）。')
        continue
    if line.strip() == 'sa.Column("owner_device_id", sa.String(100), nullable=True),':
        # drop this add_column call together with its wrapper lines
        # remove previous line if it is 'op.add_column(' and next line is ')'
        if out and out[-1].strip() == 'op.add_column(':
            out.pop()
        skip_next_addcol = True
        continue
    if skip_next_addcol and line.strip() == ')':
        skip_next_addcol = False
        continue
    if line.strip() == 'SET owner_device_id = i.owner_device_id,':
        continue
    if line.strip() == 'AND (i.owner_account_id IS NOT NULL OR i.owner_device_id IS NOT NULL)':
        out.append('           AND i.owner_account_id IS NOT NULL')
        continue
    if line.strip() == 'op.drop_column("action_handoffs", "owner_device_id")':
        continue
    if line.strip() == 'op.drop_column("itinerary_items", "owner_device_id")':
        continue
    out.append(line)
# fix comment line 71-72 (归属从头表带下来)
new = "\r\n".join(out) + "\r\n"
io.open(p, "w", encoding="utf-8", newline="").write(new)
print("migration edited")
