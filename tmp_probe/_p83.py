# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()
start = t.index("    def _backfill_wish_city(self, name: str, city: str) -> None:\n")
end = t.index("    async def _brief_site_round(\n")
new_block = NL.join([
'    def _backfill_wish_city(self, name: str, city: str) -> None:',
'        """心愿城市记录（2026-11-15 用户拍板「心愿单只在保存/删除时进',
'        数据库」）：规划期间不再写心愿行——城市随绑定/会话状态走',
'        （wish_bindings[name]["city"] / session.site_cities），保存行程',
'        物化成行时一并落库。保留入口只为兼容既有调用。""";',
'        return',
'',
'',
])
t = t[:start] + new_block + t[end:]
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("backfill noop ok")
