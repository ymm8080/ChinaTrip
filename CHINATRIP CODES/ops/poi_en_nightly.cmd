@echo off
rem _en nightly translation (DESIGN language_dual_system SS5.3): translate
rem existing zh text into *_en columns, fill-empty-only, idempotent.
rem Timing: 04:10 daily (after stats 03:40, off the hour)
rem Log: devlogs\poi_en_nightly.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
set "LOG=devlogs\poi_en_nightly.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === en backfill start === >> "%LOG%"
"%PY%" -m app.jobs.backfill_en_columns --table pois --limit 500 --concurrency 6 >> "%LOG%" 2>&1
"%PY%" -m app.jobs.backfill_en_columns --table restaurants --limit 500 --concurrency 6 >> "%LOG%" 2>&1
echo [%date% %time%] === en backfill done === >> "%LOG%"
