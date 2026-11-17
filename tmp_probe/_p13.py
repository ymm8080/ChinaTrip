# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\state_persist.py"
t = io.open(p, encoding="utf-8", newline="").read()
old = '''    def delete(self, item_id: str) -> None:\r
        super().delete(item_id)\r
        self._backend.delete_trip_item(item_id)\r
'''
new = '''    def delete(self, item_id: str, *, actor: str | None = None) -> None:\r
        super().delete(item_id, actor=actor)\r
        self._backend.delete_trip_item(item_id)\r
'''
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("ok")
