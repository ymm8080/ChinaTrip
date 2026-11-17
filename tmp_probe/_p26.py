# -*- coding: utf-8 -*-
import io
wp = r"D:\tmp_ct_wishdup\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(wp, encoding="utf-8", newline=None).read()
old = '''        if session.source_itinerary_id or session.wish_committed:
            return None
        return session.session_id
'''
new = '''        if session.source_itinerary_id or session.wish_committed:
            return None
        return None  # A/B: draft flag off
'''
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(wp, "w", encoding="utf-8", newline="\r\n").write(t)
print("draft flag off")
