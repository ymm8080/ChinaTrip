# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

old = '''        for item in matches:
            raw_note = str(item.get("note") or "")
            base = strip_scheduled_note(raw_note)
            kwargs: dict = {"exclusion_flag": True}
            if base != raw_note:
                kwargs["note"] = base
            return self.update(item["id"], status=STATUS_WISHLIST, **kwargs)
'''.replace(chr(13), "")
new = '''        for item in matches:
            raw_note = str(item.get("note") or "")
            base = strip_scheduled_note(raw_note)
            kwargs: dict = {"exclusion_flag": True}
            if base != raw_note:
                kwargs["note"] = base
            other_trip = bool(
                itinerary_id and item.get("itinerary_id") != itinerary_id
            )
            if other_trip and item.get("status") in (STATUS_SCHEDULED, STATUS_BOOKED):
                # 别趟行程里已排上/已订的同一站：只打排除标，不动它的档期
                return self.update(item["id"], **kwargs)
            return self.update(item["id"], status=STATUS_WISHLIST, **kwargs)
'''.replace(chr(13), "")
assert t.count(old) == 1
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t.replace(old, new))
print("ok")
