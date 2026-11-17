import sys, re
sys.path.insert(0, r"D:\chinatrip\CHINATRIP CODES")
from app.services.poi_names import place_core_en, place_core, latin_typo_prefix
from app.services.poi_details import PoiDetailStore

BRIEF = ("SHANGHAI 2DAY'S TRIP INCLUDING THE BUND, SHANGHAI MUSEUM, "
         "ORITAL TOWER, CURISE, YUGARDEN ZHUJIAZUI")
spaced = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", BRIEF.lower())
words = spaced.split()
print("words:", words)
print("prefix vs lujiazui:", [(w, latin_typo_prefix(w, "lujiazui")) for w in words if latin_typo_prefix(w, "lujiazui") is not None])

store = PoiDetailStore()
# replicate best_score manually for the row
name_zh, name_en, aliases, category = "陆家嘴", "Lujiazui", ["陆家嘴金融贸易区", "陆家嘴金融城"], "other"
probe = BRIEF.strip()
positions = {}
for idx, w in enumerate(words):
    positions.setdefault(w, []).append(idx)
variants = [name_zh, name_en] + list(aliases or [])
for v in variants:
    v = v.strip()
    if store._TEXT_CJK_RE.search(v):
        print("CJK", v, "in probe:", v in probe)
        continue
    core = place_core_en(v)
    print("latin", v, "| core_en:", core, "| core==v:", core == v, "| core toks:", core.split())
    toks = core.split()
    if len(toks) == 1:
        ft = toks[0].lower()
        print("   fuzzy hits:", [(t, latin_typo_prefix(t, ft)) for t in positions if latin_typo_prefix(t, ft) is not None])
core_zh = place_core(name_zh)
print("place_core(name_zh):", core_zh, "in probe:", core_zh in probe)
