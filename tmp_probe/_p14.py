# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline="").read()
old = '''        if source not in SOURCES:\r
            raise InvalidSourceError(f"invalid_source:{source}")\r
        duplicate = self._find_duplicate(\r
            name,\r
            source=source,\r
            itinerary_id=itinerary_id,\r
            city=city,\r
            poi_id=poi_id,\r
            owner_device_id=owner_device_id,\r
        )\r
'''
new = '''        if source not in SOURCES:\r
            raise InvalidSourceError(f"invalid_source:{source}")\r
        # 2026-11-14：草稿行只在本会话内参与查重——别的未保存会话留下的\r
        # 草稿不能把新会话的心愿「吸」成一条看不见的行（本会话重说一遍\r
        # 仍要命中自己的草稿，防重复建行）。\r
        known = [\r
            i\r
            for i in self._items.values()\r
            if not i.get("draft_session_id")\r
            or i.get("draft_session_id") == draft_session_id\r
        ]\r
        duplicate = self._find_duplicate(\r
            name,\r
            source=source,\r
            itinerary_id=itinerary_id,\r
            city=city,\r
            poi_id=poi_id,\r
            owner_device_id=owner_device_id,\r
            items=known,\r
        )\r
'''
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("ok")
