# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

old = '''    def _backfill_wish_city(self, name: str, city: str) -> None:
        """心愿城市记录（2026-11-15 用户拍板「心愿单只在保存/删除时进
        数据库」）：规划期间不再写心愿行——城市随绑定/会话状态走
        （wish_bindings[name]["city"] / session.site_cities），保存行程
        物化成行时一并落库。保留入口只为兼容既有调用。"""
        return
'''.replace(chr(13), "")
new = '''    def _backfill_wish_city(self, name: str, city: str) -> None:
        """已存心愿行的城市回填（2026-11-15 口径调整）：规划期间不**新建**
        心愿行（不复制/不缓存），但用户自己已经在心愿单里的行，解析出城市
        后就地补空城——只改已存行，绝不建行。新愿望的城市随会话走
        （session.site_cities / wish_sources），保存行程时物化进库。"""
        if self._trip_items is None or not (city or "").strip():
            return
        try:
            groups = self._trip_items.list_groups(None)
        except Exception:
            return
        for zone in ("wishlist", "scheduled"):
            for row in groups.get(zone, []) or []:
                if not _same_wish_name(str(row.get("name") or ""), name):
                    continue
                if str(row.get("city") or "").strip():
                    continue
                try:
                    self._trip_items.update(row["id"], city=city)
                except Exception:
                    logger.warning(
                        "plan: wish city backfill failed id=%s", row.get("id")
                    )
'''.replace(chr(13), "")
assert t.count(old) == 1
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t.replace(old, new))
print("ok")
