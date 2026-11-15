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

# 1) _record_link_sites: record into session.wish_sources (no DB write)
start = t.index("    def _record_link_sites(\n")
end = t.index("    async def _add_must_visits(\n")
new_block = '''    def _record_link_sites(
        self,
        session: PlanSession,
        mandatory: list[str],
        url: str,
        kinds: dict[str, str] | None = None,
        origin: str = "link",
    ) -> None:
        """Product rule 2026-10-20: only the user-picked mandatory sites
        land in the trip-center wishlist. 2026-11-15 用户拍板「心愿单只在
        保存/删除时进数据库」：规划期间不再建行——来源/城市/备注先记在
        会话（wish_sources），保存行程时物化成正式行。"""
        kinds = kinds or {}
        source = "chat" if origin in ("brief", "image") else "paste"
        sources = dict(session.wish_sources or {})
        for site in mandatory:
            label = (
                L("必去·餐饮", "Must-visit · food")
                if kinds.get(site) == "food"
                else L("必去", "Must-visit")
            )
            city = session.site_cities.get(site) or (
                session.cities[0] if len(session.cities) == 1 else None
            )
            if origin == "image":
                note = L(
                    f"来自你发的图片（{label}）",
                    f"From your photo ({label})",
                )
            elif origin == "brief":
                note = L(
                    f"来自你的文字/视频描述（{label}）",
                    f"From your typed brief ({label})",
                )
            else:
                note = L(
                    f"来自链接 {url}（{label}）",
                    f"From a shared link {url} ({label})",
                )
            sources[site] = {"source": source, "note": note, "city": city}
            # §5.3：链接解析按 POI 聚合计数（小红书热度代理，只存统计）
            try:
                from app.services.poi_feedback import get_poi_feedback_store

                get_poi_feedback_store().note_link_mention(site, city)
            except Exception:
                logger.warning("plan: note_link_mention failed", exc_info=True)
        session.wish_sources = sources

'''
t = t[:start] + new_block + t[end:]

# 2) _backfill_wish_city: session state only (no row writes during planning)
sub('''        if self._trip_items is None or not (city or "").strip():
            return
        city = (city or "").strip().removesuffix("市")
        try:
            for group in self._trip_items.list_groups().values():
''', '''        if not (city or "").strip():
            return
        city = (city or "").strip().removesuffix("市")
        # 2026-11-15 用户拍板：规划期间不写心愿行——城市先记在会话的绑定/
        # site_cities 里，保存行程物化时随行落库。
        if not _same_site("", ""):
            pass
        try:
            for group in ():
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("batch2a ok")
