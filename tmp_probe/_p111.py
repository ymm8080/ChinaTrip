# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), "")
    new = new.replace(chr(13), "")
    c = t.count(old)
    assert c == n, (c, old[:100])
    t = t.replace(old, new)

# 6) sync_trip_rows at_save gate
sub('''    def sync_trip_rows(self, session: PlanSession) -> None:
        """行程↔看板对账入口（2026-11-13 用户报「陕历博在行程里被安排，却没从
        心愿单翻到已排期」）：打开/保存/载入行程都跑一遍——心愿单里已被本行程
        落排的点翻已排期，已排期里本行程已经没有的点回心愿单。Best-effort，
        绝不阻塞请求。"""
        try:
            self._sync_wish_rows(session)
            self._sync_planned_rows(session)
''', '''    def sync_trip_rows(self, session: PlanSession, *, at_save: bool = False) -> None:
        """行程↔看板对账（2026-11-15 用户拍板「心愿单只在 保存新行程/保存
        修改/删除 时进数据库」）：只在保存行程时对账——规划回合内不再写
        心愿行（不落库、不复制、不缓存），看板保持「最后一次保存」的状态。
        Best-effort，绝不阻塞请求。"""
        if not at_save:
            return
        try:
            self._sync_wish_rows(session, at_save=True)
            self._sync_planned_rows(session, at_save=True)
''')

# 7) _sync_wish_rows at_save gate
sub('''    def _sync_wish_rows(self, session: PlanSession) -> None:
''', '''    def _sync_wish_rows(self, session: PlanSession, *, at_save: bool = False) -> None:
''')
sub('''        挂。Best-effort，绝不阻塞规划回合。"""
        if self._trip_items is None or session.plan is None:
            return
        itin = session.plan.itinerary_id
''', '''        挂。2026-11-15 用户拍板「心愿单只在保存/删除时进数据库」：只在
        保存行程的对账里跑（at_save=True）。Best-effort。"""
        if not at_save or self._trip_items is None or session.plan is None:
            return
        itin = session.plan.itinerary_id
''')

# 8) _sync_planned_rows at_save gate + planned relaxation
sub('''    def _sync_planned_rows(self, session: PlanSession) -> None:
''', '''    def _sync_planned_rows(self, session: PlanSession, *, at_save: bool = False) -> None:
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
sub('''            if isinstance(item, VisitItem)
            and item.start_time is not None
            and item.poi_id
            and ((item.category or "") != "food" or _is_show_banquet_item(item))
            and (item.category or "") != "hotel"
''', '''            if isinstance(item, VisitItem)
            and item.start_time is not None
            and ((item.category or "") != "food" or _is_show_banquet_item(item))
            and (item.category or "") != "hotel"
''')

# 9) sync_removals -> avoid_sites
start = t.index("    def sync_removals_to_trip_items(\n")
end = t.index("    @staticmethod\n    def _coerce_wishes(raw: object) -> list[str]:\n")
new_block = NL.join([
'    def sync_removals_to_trip_items(',
'        self,',
'        plan_before: ItineraryPlan,',
'        diffs: list[DiffOp],',
'        *,',
'        session: "PlanSession | None" = None,',
'    ) -> None:',
'        """Chat/button deletes (2026-10-20): each removed visit stops the',
'        wishlist from re-suggesting it. 2026-11-15 用户拍板「心愿单只在',
'        保存/删除时进数据库」：规划期间不写排除行——记入会话',
'        avoid_sites（选点闸即时生效），保存行程物化时打 EXCLUSION 落库。',
'        Call only after the diffs applied successfully."""',
'        if session is None:',
'            return',
'        by_id = {',
'            i.item_id: i',
'            for d in plan_before.days',
'            for i in d.items',
'            if isinstance(i, VisitItem)',
'        }',
'        removed: list[str] = list(session.avoid_sites or [])',
'        for op in diffs:',
'            if op.op != "remove" or not op.item_id:',
'                continue',
'            item = by_id.get(op.item_id)',
'            if item is None or not (item.name or "").strip():',
'                continue',
'            if not any(_same_site(item.name, n) for n in removed):',
'                removed.append(item.name)',
'        session.avoid_sites = removed',
'',
'',
])
t = t[:start] + new_block + t[end:]

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("batch B ok")
