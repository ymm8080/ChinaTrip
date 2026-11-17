# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()
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
print("removals ok")
