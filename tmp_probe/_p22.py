# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\trip_items.py"
t = io.open(p, encoding="utf-8", newline="").read()

def sub(old, new, n=1):
    global t
    c = t.count(old)
    assert c == n, (c, old[:110])
    t = t.replace(old, new)

anchor = '''    def purge_itinerary(
'''
new_methods = '''    def dedupe_itinerary_rows(\r
        self,\r
        itinerary_id: str,\r
        *,\r
        actor: str | None = None,\r
    ) -> int:\r
        """同一行程里同名心愿行只留一行（2026-11-14 用户报「已排期里同一个\r
        心愿出现两三条」的自愈）：历史版本按名字跨会话/跨行程吸收 + 每次\r
        重新规划新建一行，导致同 wish 在已排期滚出多行。保留序 = 已排期\r
        （有 day）优先 → created_at 最早；多余行软删留档（booked 真实订单\r
        不参与）。返回软删行数。"""\r
        if not itinerary_id:\r
            return 0\r
        rows = [\r
            item\r
            for item in self._items.values()\r
            if item.get("itinerary_id") == itinerary_id\r
            and item.get("status") != STATUS_BOOKED\r
        ]\r
        rows.sort(\r
            key=lambda r: (\r
                r.get("status") != STATUS_SCHEDULED,\r
                str(r.get("created_at") or ""),\r
            )\r
        )\r
        seen: set[str] = set()\r
        removed = 0\r
        for item in rows:\r
            key = _wish_key(str(item.get("name") or ""))\r
            if key not in seen:\r
                seen.add(key)\r
                continue\r
            try:\r
                self.delete(item["id"], actor=actor or "wish-dedupe")\r
            except (InvalidTransitionError, NotFoundError):\r
                continue\r
            removed += 1\r
            logger.info(\r
                "trip_item_deduped_in_trip itinerary=%s name=%s id=%s",\r
                itinerary_id,\r
                item.get("name"),\r
                item["id"],\r
            )\r
        return removed\r
\r
    def purge_itinerary(
'''
sub(anchor, new_methods)

io.open(p, "w", encoding="utf-8", newline="").write(t)
print("ok")
