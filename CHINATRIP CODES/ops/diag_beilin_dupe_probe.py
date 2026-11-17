# -*- coding: utf-8 -*-
"""diag: session be915838 day4 双卡复现——碑林博物馆(m1) vs 城墙·碑林(5a_304 族卡)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.services.agent.plan import _dedupe_visit_keepers, _same_visit
from app.services.itinerary.models import GeoPoint, VisitItem

museum = VisitItem(
    item_id="vm",
    name="西安碑林博物馆",
    poi_id="m1_1c7b3030b03e",
    category="museum",
    city="西安",
    location=GeoPoint(lon=108.9527, lat=34.2539),
    day=4,
)
fam = VisitItem(
    item_id="vf",
    name="城墙·碑林历史文化景区",
    poi_id="5a_304",
    category="attraction",
    city="西安",
    location=GeoPoint(lon=108.94052490245161, lat=34.25687582300908),
    day=4,
    pinned=True,
    must=True,
)

print("same_visit(museum, fam):", _same_visit(museum, fam), flush=True)
keepers, dropped = _dedupe_visit_keepers([museum, fam])
print("keepers:", [k.name for k in keepers], flush=True)
print("dropped:", dropped, flush=True)

# 反向序（并卡族卡先入册的顺序）也测一遍
keepers2, dropped2 = _dedupe_visit_keepers([fam, museum])
print("keepers(rev):", [k.name for k in keepers2], flush=True)
print("dropped(rev):", dropped2, flush=True)

# 弱化族卡（无 must/pinned，纯选点序）第三遍
fam_plain = VisitItem(
    item_id="vf2",
    name="城墙·碑林历史文化景区",
    poi_id="5a_304",
    category="attraction",
    city="西安",
    location=GeoPoint(lon=108.94052490245161, lat=34.25687582300908),
    day=4,
)
print("same_visit(museum, fam_plain):", _same_visit(museum, fam_plain), flush=True)
keepers3, dropped3 = _dedupe_visit_keepers([museum, fam_plain])
print("keepers(plain):", [k.name for k in keepers3], flush=True)
print("dropped(plain):", dropped3, flush=True)
