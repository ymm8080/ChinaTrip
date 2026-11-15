# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

sub('''            # 草稿行转正：行程没了，「保存行程」不会再发生——按用户口径
            # 退回心愿单（清 draft 标记 + 摘行程绑定）
            if item.get("draft_session_id"):
                item["draft_session_id"] = None
                self._persist(item_id)
''', '''            # 草稿行转正：行程没了，「保存行程」不会再发生——按用户口径
            # 退回心愿单（清 draft 标记 + 摘行程绑定）。注意改存储行本体，
            # 不是上面的 dict 拷贝。
            stored = self._items.get(item_id)
            if stored is not None and stored.get("draft_session_id"):
                stored["draft_session_id"] = None
                self._persist(item_id)
''')

sub('''        for item in list(self._items.values()):
            if item.get("itinerary_id") == itinerary_id:
                self.unbind_itinerary(item["id"], now=now)
        logger.info(
            "trip_itinerary_released itinerary=%s rows=%d actor=%s",
''', '''        for item in list(self._items.values()):
            if item.get("itinerary_id") == itinerary_id:
                self.unbind_itinerary(item["id"], now=now)
        # 返回按最新状态重取（update/unbind 都可能改过行）
        released = [self.get(r["id"]) or r for r in released]
        logger.info(
            "trip_itinerary_released itinerary=%s rows=%d actor=%s",
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("release fixed")
