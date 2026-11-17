# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
text = io.open(p, encoding="utf-8", newline=None).read()  # CRLF -> \n

def sub(old, new, n=1):
    global text
    c = text.count(old)
    assert c == n, (c, old[:100])
    text = text.replace(old, new)

sub('''    def sync_removals_to_trip_items(
        self,
        plan_before: ItineraryPlan,
        diffs: list[DiffOp],
        *,
        draft_session_id: str | None = None,
    ) -> None:
''', '''    def sync_removals_to_trip_items(
        self,
        plan_before: ItineraryPlan,
        diffs: list[DiffOp],
        *,
        session: "PlanSession | None" = None,
    ) -> None:
''')
sub('''            try:
                # 2026-11-13 用户拍板：删站点 = 回心愿单 + 排除标记
                # （不再塞进「不想去」分区；心愿单里仍可见）
                self._trip_items.mark_excluded(
                    item.name,
                    itinerary_id=plan_before.itinerary_id,
                    city=item.city,
                    draft_session_id=draft_session_id,
                )
''', '''            try:
                # 2026-11-13 用户拍板：删站点 = 回心愿单 + 排除标记
                # （不再塞进「不想去」分区；心愿单里仍可见）
                self._trip_items.mark_excluded(
                    item.name,
                    itinerary_id=plan_before.itinerary_id,
                    city=item.city,
                    # 2026-11-14：未保存行程里新建的排除行同样是草稿
                    draft_session_id=(
                        self._wish_draft_session(session)
                        if session is not None
                        else None
                    ),
                )
''')
sub('''            if any(op.op == "remove" for op in diffs):
                self.sync_removals_to_trip_items(
                    plan_before, diffs, draft_session_id=self._wish_draft_session(session)
                )
''', '''            if any(op.op == "remove" for op in diffs):
                self.sync_removals_to_trip_items(plan_before, diffs, session=session)
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(text)
print("ok", len(text))
