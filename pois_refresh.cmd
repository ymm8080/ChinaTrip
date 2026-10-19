@echo off
rem Daily POI address/opening-hours refresh (v2.4.4: ctrip first, amap v5 last).
cd /d "D:\chinatrip\CHINATRIP CODES"
"D:\chinatrip\CHINATRIP CODES\.venv\Scripts\python.exe" -m app.jobs.refresh_pois >> D:\chinatrip\pois_refresh.log 2>&1
