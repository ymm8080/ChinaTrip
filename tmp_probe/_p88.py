# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()
old = NL.join([
'                        if readd_note:',
'                            readd_notes.append(readd_note)',
'        # 2026-11-15 用户拍板「心愿单只在 保存新行程/保存修改/删除 时进',
])
new = NL.join([
'                        if readd_note:',
'                            readd_notes.append(readd_note)',
'        except Exception:',
'            logger.warning("plan: wish sync-time bind failed", exc_info=True)',
'        # 2026-11-15 用户拍板「心愿单只在 保存新行程/保存修改/删除 时进',
])
assert t.count(old) == 1, t.count(old)
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("try closed")
