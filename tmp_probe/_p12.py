# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline="").read()

def sub(old, new, n=1):
    global t
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

# add _persist helper right before link_itinerary
sub('''    def link_itinerary(\r
''', '''    def _persist(self, item_id: str) -> None:\r
        """行落库钩子（2026-11-14）：基类按 `_write_through` 约定（PG 子类\r
        实现）；SQLite 子类覆写为整行 JSON 落盘。无钩子 = 纯内存。"""\r
        hook = getattr(self, "_write_through", None)\r
        if callable(hook):\r
            hook(item_id)\r
\r
    def link_itinerary(\r
''')

# link_itinerary / unbind_itinerary: use _persist
sub('''        item["itinerary_id"] = itinerary_id\r
        item["updated_at"] = _iso_now(None)\r
        hook = getattr(self, "_write_through", None)\r
        if callable(hook):\r
            hook(item_id)\r
        return dict(item)\r
''', '''        item["itinerary_id"] = itinerary_id\r
        item["updated_at"] = _iso_now(None)\r
        self._persist(item_id)\r
        return dict(item)\r
''')
sub('''        item["itinerary_id"] = None\r
        item["updated_at"] = _iso_now(now)\r
        hook = getattr(self, "_write_through", None)\r
        if callable(hook):\r
            hook(item_id)\r
        return dict(item)\r
''', '''        item["itinerary_id"] = None\r
        item["updated_at"] = _iso_now(now)\r
        self._persist(item_id)\r
        return dict(item)\r
''')

# commit_drafts: use _persist
sub('''        committed = 0\r
        hook = getattr(self, "_write_through", None)\r
        for item in list(self._items.values()):\r
''', '''        committed = 0\r
        for item in list(self._items.values()):\r
''')
sub('''            committed += 1\r
            if callable(hook):\r
                hook(item["id"])\r
''', '''            committed += 1\r
            self._persist(item["id"])\r
''')

io.open(p, "w", encoding="utf-8", newline="").write(t)
print("trip_items persist ok")

p2 = r"D:\CHINATRIP\CHINATRIP CODES\app\services\state_persist.py"
t2 = io.open(p2, encoding="utf-8", newline="").read()
old2 = '''    def update(self, item_id: str, **kwargs) -> dict:\r
        item = super().update(item_id, **kwargs)\r
        self._backend.save_trip_item(item_id, json.dumps(item, ensure_ascii=False))\r
        return item\r
'''
new2 = old2 + '''\r
    def _persist(self, item_id: str) -> None:\r
        # 2026-11-14：草稿转正/挂行程/解绑都不走 update()，落盘走同一钩子\r
        item = self._items.get(item_id)\r
        if item is None:\r
            return\r
        self._backend.save_trip_item(item_id, json.dumps(item, ensure_ascii=False))\r
'''
assert t2.count(old2) == 1
t2 = t2.replace(old2, new2, 1)
io.open(p2, "w", encoding="utf-8", newline="").write(t2)
print("state_persist ok")
