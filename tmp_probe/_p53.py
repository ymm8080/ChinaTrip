# -*- coding: utf-8 -*-
import io
p = r"D:\CHINATRIP\CHINATRIP CODES\app\api\backfill.py"
t = io.open(p, encoding="utf-8", newline=None).read()
bad = "from fastapi import APIRouter, Depends, HTTPException, Queryfrom app.api.itineraries import _account_from_auth\n"
good = "from fastapi import APIRouter, Depends, HTTPException, Query\nfrom app.api.itineraries import _account_from_auth\n"
assert t.count(bad) == 1
t = t.replace(bad, good, 1)
io.open(p, "w", encoding="utf-8", newline="\r\n").write(t)
print("fixed")
