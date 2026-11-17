@echo off
rem ===== Restaurant photos race at amap daily-pool reset (00:00, 2026-11-14) =====
rem One-shot: grab the fresh amap quota before the parallel hourly jobs burn it.
rem Day-2 evidence: pool resets at 00:00 but is drained within minutes by
rem fill_hours_rating_driver (every 3 min) + pois backfill lanes.
rem Job semantics: fill-empty-only + 24h cooldown stamp + quota fuse (exit 2).
rem Ledger: ops\p1_data_tasks_progress.md  Log: ops\rest_photos_race.log
rem ASCII-only file (cmd parses UTF-8 Chinese comments as GBK and breaks).

cd /d "D:\CHINATRIP\CHINATRIP CODES"

echo ===== %date% %time% race start ===== >> ops\rest_photos_race.log

.venv\Scripts\python.exe ops\db_fingerprint.py > nul 2>&1
if errorlevel 1 (
  echo %date% %time% fingerprint FAIL - no writes >> ops\rest_photos_race.log
  echo %date% %time% rest photos race: fingerprint FAIL, skipped >> ops\p1_data_tasks_progress.md
  exit /b 1
)

rem Cooldown is source-blind: today's Commons grind stamped all photo-less
rem rows, blocking the fresh amap pool. Clear stamps on CJK-named rows only
rem (the only ones around can name-match); English rows stay stamped.
.venv\Scripts\python.exe ops\rest_photos_race_prep.py >> ops\rest_photos_race.log 2>&1

.venv\Scripts\python.exe -m app.jobs.backfill_restaurant_photos --limit 3000 --concurrency 2 >> ops\rest_photos_race.log 2>&1
set RC=%ERRORLEVEL%

echo %date% %time% race done rc=%RC% (stats json above) >> ops\rest_photos_race.log
echo %date% %time% rest photos race: amap pool grab rc=%RC%, stats in ops\rest_photos_race.log >> ops\p1_data_tasks_progress.md
exit /b %RC%
