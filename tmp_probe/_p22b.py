# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    c = t.count(old)
    assert c == n, (c, old[:110])
    t = t.replace(old, new)

anchor = "    def purge_itinerary(\n"
new_methods = '''    def dedupe_itinerary_rows(
        self,
        itinerary_id: str,
        *,
        actor: str | None = None,
    ) -> int:
        """同一行程里同名心愿行只留一行（2026-11-14 用户报「已排期里同一个
        心愿出现两三条」的自愈）：历史版本按名字跨会话/跨行程吸收 + 每次
        重新规划新建一行，导致同一 wish 在已排期滚出多行。保留序 = 已排期
        （有 day）优先 → created_at 最早；多余行软删留档（booked 真实订单
        不参与）。返回软删行数。"""
        if not itinerary_id:
            return 0
        rows = [
            item
            for item in self._items.values()
            if item.get("itinerary_id") == itinerary_id
            and item.get("status") != STATUS_BOOKED
        ]
        rows.sort(
            key=lambda r: (
                r.get("status") != STATUS_SCHEDULED,
                str(r.get("created_at") or ""),
            )
        )
        seen: set[str] = set()
        removed = 0
        for item in rows:
            key = _wish_key(str(item.get("name") or ""))
            if key not in seen:
                seen.add(key)
                continue
            try:
                self.delete(item["id"], actor=actor or "wish-dedupe")
            except (InvalidTransitionError, NotFoundError):
                continue
            removed += 1
            logger.info(
                "trip_item_deduped_in_trip itinerary=%s name=%s id=%s",
                itinerary_id,
                item.get("name"),
                item["id"],
            )
        return removed

''' + anchor
sub(anchor, new_methods)

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
