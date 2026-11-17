# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\pg_state.py"
t = io.open(p, encoding="utf-8", newline="").read()
old = '            logger.info("pg_state: 心愿草稿过期清理 %d 行（>%d 天未保存）", purged, days)\r\n'
new = '            logger.info(\r\n                "pg_state: 心愿草稿过期清理 %d 行（>%d 天未保存）", purged, days\r\n            )\r\n'
assert t.count(old) == 1
t = t.replace(old, new, 1)
io.open(p, "w", encoding="utf-8", newline="").write(t)
print("ok")
