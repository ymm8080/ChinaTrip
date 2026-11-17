# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:80])
    t = t.replace(old, new)

sub("    def _sync_planned_rows(self, session: PlanSession, *, at_save: bool = False) -> None:\n",
    "    def _sync_planned_rows(\n        self, session: PlanSession, *, at_save: bool = False\n    ) -> None:\n")
sub('''                                    f"{wish} saved to your wishlist ({city}, not part of this trip)",
''', '''                                    f"{wish} saved to your wishlist "
                                    f"({city}, not part of this trip)",
''')
sub('''        2026-11-15：城市读会话（site_cities/绑定），不再读行。""";
''', '''        2026-11-15：城市读会话（site_cities/绑定），不再读行。"""
''')
sub('''                _bound = (session.wish_bindings or {}).get(wish) or self._wish_bindings.get(
                    wish,
                )
''', '''                _bound = (session.wish_bindings or {}).get(
                    wish
                ) or self._wish_bindings.get(wish)
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("fix2 ok")
