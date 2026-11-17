# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\services\agent\plan.py"
t = io.open(p, encoding="utf-8", newline=None).read()

def sub(old, new, n=1):
    global t
    old = old.replace(chr(13), ""); new = new.replace(chr(13), "")
    c = t.count(old); assert c == n, (c, old[:90])
    t = t.replace(old, new)

sub('''            core = _wish_core(name)
            if any(_name_dup(core, c) or _name_dup(name, c) for c in covered):
                continue
            missing.append(name)
            rows[name] = it
        if not missing:
''', '''            core = _wish_core(name)
            if any(_name_dup(core, c) or _name_dup(name, c) for c in covered):
                continue
            missing.append(name)
            rows[name] = it
        # 2026-11-15 用户拍板「心愿单只在保存/删除时进数据库」：规划期的心愿
        # 只在会话里（wish_sources），覆盖检查必须一并看会话，否则本轮刚说
        # 的愿望永远补不进行程。
        for name, meta in (session.wish_sources or {}).items():
            name = (name or "").strip()
            if not name or meta.get("dropped"):
                continue
            if any(_name_dup(name, n) for n in missing):
                continue
            city = (session.site_cities.get(name) or meta.get("city") or "").strip()
            city = city.removesuffix("市")
            if city and city not in trip_cities:
                continue
            if not city:
                hint = _wish_city_hint(name)
                if hint:
                    if hint not in trip_cities:
                        continue
                    session.site_cities.setdefault(name, hint)
                elif _category_search_keyword(name) is None and len(trip_cities) > 1:
                    continue
            core = _wish_core(name)
            if any(_name_dup(core, c) or _name_dup(name, c) for c in covered):
                continue
            missing.append(name)
            rows[name] = {"name": name, "city": city or None}
        if not missing:
''')
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("ok")
