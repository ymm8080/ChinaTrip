@echo off
rem ===== Register POI/weather scheduled tasks (one-shot; run as current user) =====
rem Cadence per DESIGN/database_design.md matrix (v1.18, 2026-10-28):
rem   02:00 backsource refresh (30d window: each row refreshed ~monthly)
rem   / 06:30 OSM daily / SUN 03:30 backfill drip
rem   / 7th 04:00 michelin / 2nd 04:30 blackpearl check / quarter-start 03:00 intro full
rem   / 08:10 weather daily (once a day, full 40 cities)
rem Interactive tasks (run only when user logged in). Missed runs self-heal:
rem refresh rotates by city, OSM resumes by watermark, backfills are fill-empty /
rem only-upgrade — all idempotent.
rem NOTE: ASCII-only file; cmd parses UTF-8 Chinese comments as GBK and breaks.

set "OPS=D:\CHINATRIP\CHINATRIP CODES\ops"

schtasks /Create /F /TN "ChinaTrip\POI refresh daily"   /TR "\"%OPS%\poi_refresh_daily.cmd\"" /SC DAILY   /ST 02:00
schtasks /Create /F /TN "ChinaTrip\POI osm daily"       /TR "\"%OPS%\poi_daily.cmd\""         /SC DAILY   /ST 06:30
schtasks /Create /F /TN "ChinaTrip\POI weekly backfill" /TR "\"%OPS%\poi_weekly.cmd\""        /SC WEEKLY  /D SUN /ST 03:30
schtasks /Create /F /TN "ChinaTrip\POI monthly tags"    /TR "\"%OPS%\poi_monthly.cmd\""       /SC MONTHLY /MO 1 /D 7 /ST 04:00
schtasks /Create /F /TN "ChinaTrip\POI blackpearl check" /TR "\"%OPS%\poi_blackpearl.cmd\""   /SC MONTHLY /MO 1 /D 2 /ST 04:30
schtasks /Create /F /TN "ChinaTrip\POI quarterly intro" /TR "\"%OPS%\poi_quarterly.cmd\""     /SC MONTHLY /M JAN,APR,JUL,OCT /D 1 /ST 03:00
schtasks /Create /F /TN "ChinaTrip\POI intro monthly"   /TR "\"%OPS%\poi_intro_monthly.cmd\"" /SC MONTHLY /MO 1 /D 1 /ST 05:10
rem poi_stats aggregate: full rebuild from trip_items + feedback, idempotent
schtasks /Create /F /TN "ChinaTrip\POI stats nightly"   /TR "\"%OPS%\poi_stats_nightly.cmd\"" /SC DAILY   /ST 03:40
rem _en translation: nightly fill-empty batch (bilingual P1)
schtasks /Create /F /TN "ChinaTrip\POI en nightly"      /TR "\"%OPS%\poi_en_nightly.cmd\"" /SC DAILY   /ST 04:10

rem ===== Weather (amap/baidu weather API; upstream CMA; 08/11/18 forecasts) =====
rem 2026-10-28 cadence decision: weather refreshes ONCE daily; 08:10 right
rem after the ~08:00 CST morning forecast update, FULL 40-city coverage so any
rem new trip city reads overnight TABLE data. POST /api/weather/sync is a pure
rem DB read — this pipeline is the only place that calls weather APIs.
schtasks /Create /F /TN "ChinaTrip\Weather daily"   /TR "\"%OPS%\weather_fetch.cmd\"" /SC DAILY /ST 08:10

schtasks /Query /TN "ChinaTrip\POI refresh daily"
echo Done. Remove with: schtasks /Delete /TN "ChinaTrip\..." /F
