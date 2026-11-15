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

# coverage city write-back -> session only
sub('''        for name in missing:
            resolved = (session.site_cities.get(name) or "").strip()
            row = rows.get(name)
            if not resolved or row is None or (row.get("city") or "").strip():
                continue
            if not row.get("id"):
                continue
            try:
                self._trip_items.update(row["id"], city=resolved)
            except Exception:
                logger.warning("plan: wishlist city write-back failed for %s", name)
        return note
''', '''        for name in missing:
            resolved = (session.site_cities.get(name) or "").strip()
            row = rows.get(name)
            if not resolved or row is None or (row.get("city") or "").strip():
                continue
            # 2026-11-15 用户拍板：规划期间不写心愿行——城市记会话
            # （site_cities），保存行程物化时随行落库。
            session.site_cities[name] = resolved
        return note
''')

# materialize: dropped wish -> unwanted row
sub('''            meta = (session.wish_sources or {}).get(name) or {}
            source = str(meta.get("source") or "chat")
            note = str(meta.get("note") or "") or L("来自聊天", "From chat")
''', '''            meta = (session.wish_sources or {}).get(name) or {}
            source = str(meta.get("source") or "chat")
            note = str(meta.get("note") or "") or L("来自聊天", "From chat")
            dropped = bool(meta.get("dropped"))
''')
sub('''            if off_trip or target is None or target.start_time is None:
                continue
            when = _wish_when_text(session, target)
''', '''            if dropped:
                # 用户在追问轮撤掉的心愿：物化成 unwanted 行（心愿单移除留痕）
                try:
                    self._trip_items.update(
                        row["id"], status=STATUS_UNWANTED, note=note
                    )
                except Exception:
                    logger.warning(
                        "plan: wish materialize unwanted failed %s", name
                    )
                continue
            if off_trip or target is None or target.start_time is None:
                continue
            when = _wish_when_text(session, target)
''')
sub('''                    poi_id=str((bound or {}).get("source_poi_id") or "") or None,
                    raw_command=name,
                    must_visit=name in (session.must_visits or []),
''', '''                    poi_id=str((bound or {}).get("source_poi_id") or "") or None,
                    raw_command=name,
                    must_visit=(
                        name in (session.must_visits or []) and not dropped
                    ),
''')

io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
