# -*- coding: utf-8 -*-
import io
wp = r"D:\tmp_ct_wishdup\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(wp, encoding="utf-8", newline=None).read()
old_sync = '''        try:
            self._sync_wish_rows(session)
            self._sync_planned_rows(session)
            # 2026-11-14（用户报「已排期里同一个心愿出现两三条」）：对账收尾
            # 顺手去重——同一行程里同名心愿行只留一行（已排期优先、最早建
            # 的留任），多余行软删留档自愈。
            hook = getattr(self._trip_items, "dedupe_itinerary_rows", None)
            if session.plan is not None and callable(hook):
                hook(session.plan.itinerary_id, actor=session.device_id)
        except Exception:
            logger.warning("plan: trip row sync failed", exc_info=True)
'''
new_sync = '''        try:
            self._sync_wish_rows(session)
            self._sync_planned_rows(session)
        except Exception:
            logger.warning("plan: trip row sync failed", exc_info=True)
'''
assert t.count(old_sync) == 1
t = t.replace(old_sync, new_sync, 1)
io.open(wp, "w", encoding="utf-8", newline="\r\n").write(t)
print("reverted (d) in worktree")
