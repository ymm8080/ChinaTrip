# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

# gate _sync_wish_rows / _sync_planned_rows behind at_save
sub('''    def _sync_wish_rows(self, session: PlanSession) -> None:
        """心愿行收口（2026-10-30 拍板「行程中心已排期写清楚」）：已绑定
''', '''    def _sync_wish_rows(self, session: PlanSession, *, at_save: bool = False) -> None:
        """心愿行收口（2026-10-30 拍板「行程中心已排期写清楚」）：已绑定
''')
sub('''        itinerary_id：本会话挂过的旧 id 记在 session.linked_itins，允许重
        挂。Best-effort，绝不阻塞规划回合。"""
        if self._trip_items is None or session.plan is None:
            return
''', '''        itinerary_id：本会话挂过的旧 id 记在 session.linked_itins，允许重
        挂。2026-11-15 用户拍板「心愿单只在保存/删除时进数据库」：本函数
        只在保存行程的对账里跑（at_save=True），规划回合内一律不写行。
        Best-effort，绝不阻塞规划回合。"""
        if not at_save or self._trip_items is None or session.plan is None:
            return
''')

sub('''    def _sync_planned_rows(self, session: PlanSession) -> None:
        """行程中心「已安排」分区对齐心愿单（2026-11-13 拍板：已排期只放
''', '''    def _sync_planned_rows(self, session: PlanSession, *, at_save: bool = False) -> None:
        """行程中心「已安排」分区对齐心愿单（2026-11-13 拍板：已排期只放
''')
sub('''        例外。行按名字全局去重、跟随当前行程——与 _sync_wish_rows 同语义。
        Best-effort。"""
        if self._trip_items is None or session.plan is None:
            return
''', '''        例外。行按名字全局去重、跟随当前行程——与 _sync_wish_rows 同语义。
        2026-11-15 用户拍板：只在保存行程的对账里跑（at_save=True）。
        Best-effort。"""
        if not at_save or self._trip_items is None or session.plan is None:
            return
''')

# sync_trip_rows passes at_save down
sub('''        if not at_save:
            return
        try:
            self._sync_wish_rows(session)
            self._sync_planned_rows(session)
''', '''        if not at_save:
            return
        try:
            self._sync_wish_rows(session, at_save=True)
            self._sync_planned_rows(session, at_save=True)
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("gates ok")
