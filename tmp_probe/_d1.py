# -*- coding: utf-8 -*-
import io
NL = chr(10)
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

# 1) 读口：全局看板（不带行程过滤）同一心愿只出一行
sub('''        if itinerary_id is not None:
            items = [i for i in items if i.get("itinerary_id") == itinerary_id]

        def timeline_key(item: dict) -> tuple[int, float]:
''', '''        if itinerary_id is not None:
            items = [i for i in items if i.get("itinerary_id") == itinerary_id]

        if itinerary_id is None:
            # 2026-11-15（用户报「颐和园在心愿单出现两行」）：全局看板是
            # 按用户的，同一条心愿只能出现一次——同名（归一愿望键）行收敛
            # 成一行：已排期/已订优先，其次最早建的那行；被收敛掉的重复行
            # 不在这里删除（写口已加合并闸，历史行由一次性清理收口）。
            def _collapse_key(item: dict) -> tuple[str, str]:
                owner = str(
                    item.get("owner_account_id")
                    or item.get("owner_device_id")
                    or ""
                )
                return (owner, _wish_key(str(item.get("name") or "")))

            def _rank(item: dict) -> tuple[int, str]:
                order = {
                    STATUS_BOOKED: 0,
                    STATUS_SCHEDULED: 1,
                    STATUS_WISHLIST: 2,
                    STATUS_UNWANTED: 3,
                }
                return (
                    order.get(str(item.get("status") or ""), 9),
                    str(item.get("created_at") or ""),
                )

            best: dict[tuple[str, str], dict] = {}
            for item in items:
                key = _collapse_key(item)
                if not key[1]:
                    best[(key[0], str(item.get("id")))] = item
                    continue
                current = best.get(key)
                if current is None or _rank(item) < _rank(current):
                    best[key] = item
            items = list(best.values())

        def timeline_key(item: dict) -> tuple[int, float]:
''')

# 2) 写口：mark_excluded 跨行程认领同一行（不再另建 plan_delete 行）
sub('''        for item in self._items.values():
            if item.get("status") == STATUS_UNWANTED:
                continue
            if itinerary_id and item.get("itinerary_id") != itinerary_id:
                continue
            row_name = _norm(str(item.get("name") or ""))
            if not row_name or row_name != _norm(name):
                continue
''', '''        # 2026-11-15（用户报「颐和园出现两行」）：排除标记要认领**同一个人
        # 的同一条心愿**，不能只看同一行程——否则另一行程里的同名心愿行
        # 和这条 plan_delete 行会并列成两行。命中即就地转排除并改挂本次
        # 行程；同人多行时只留一行（其余软删留档）。
        matches: list[dict] = []
        for item in self._items.values():
            if item.get("status") == STATUS_UNWANTED:
                continue
            row_name = _norm(str(item.get("name") or ""))
            if not row_name or row_name != _norm(name):
                continue
            matches.append(item)
        if len(matches) > 1:
            matches.sort(
                key=lambda i: (
                    i.get("status") != STATUS_SCHEDULED,
                    str(i.get("created_at") or ""),
                )
            )
            for extra in matches[1:]:
                try:
                    self.delete(extra["id"], actor="mark_excluded")
                except Exception:
                    logger.warning(
                        "trip_items: duplicate row drop failed id=%s", extra.get("id")
                    )
            matches = matches[:1]
        for item in matches:
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
