# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = '''            matched = match_names is None or any(
                _name_dup(name, n) for n in match_names
            )
'''
new = '''            matched = match_names is None or any(
                _wish_match(_wish_key(name), _wish_key(n)) for n in match_names
            )
'''
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
