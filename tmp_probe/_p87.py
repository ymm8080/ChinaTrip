# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = NL.join([
'                            notes.append(',
'                                L(',
'                                    f"「{wish}」已记入心愿单（{city}，本次行程未含{city}）",',
'                                    f\\"{wish}\\" saved to your wishlist ({city}, not \\".',
'                                )',
'                            )',
])
new = NL.join([
'                            notes.append(',
'                                L(',
'                                    f"「{wish}」已记入心愿单（{city}，本次行程未含{city}）",',
'                                    f"「{wish}」saved to your wishlist ({city}, not part of this trip)",',
'                                )',
'                            )',
])
assert t.count(old) == 1, t.count(old)
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("fixed")
