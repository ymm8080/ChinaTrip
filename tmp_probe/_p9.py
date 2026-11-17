# -*- coding: utf-8 -*-
import io

p = r"D:\CHINATRIP\CHINATRIP CODES\app\static\index.html"
t = io.open(p, encoding="utf-8", newline=None).read()
old = "）？将连同它的全部快照一起删除，已排期心愿自动回到心愿单，操作不可恢复。"
new = "）？将连同它的全部快照、以及这条行程关联的心愿单一并删除（已订订单保留），操作不可恢复。"
assert t.count(old) == 1
t = t.replace(old, new)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("index patched")

p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\static\i18n.js"
t2 = io.open(p2, encoding="utf-8", newline=None).read()
old2 = '")? All its snapshots will be deleted too; scheduled wishes return to the wishlist — this cannot be undone.",'
new2 = '")? All its snapshots and its wishlist will be deleted too (booked orders are kept) — this cannot be undone.",'
assert t2.count(old2) == 1, t2.count(old2)
t2 = t2.replace(old2, new2)
io.open(p2, "w", encoding="utf-8", newline="\r\n").write(t2)
print("i18n patched")
