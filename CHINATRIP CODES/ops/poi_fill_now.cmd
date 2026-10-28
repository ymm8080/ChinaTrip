@echo off
rem ===== Cold-start one-shot data fill (run manually once; DB = WSL Ubuntu PG18+PostGIS) =====
rem Prereq: WSL keepalive in Startup folder, or ops\db_up.cmd can wake the VM
rem NOTE: keep this file ASCII-only; cmd parses UTF-8 Chinese comments as GBK and breaks.
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_fill_now.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === fill now start === >> "%LOG%"

rem 0. schema (0006: POI base-library columns + restaurants table), idempotent
"%PY%" -m alembic upgrade head >> "%LOG%" 2>&1 || goto :fail

rem 1. ChinaTravel seed (skeleton only: name/coords/category; coord auto-detect GCJ-02/WGS84)
"%PY%" -m app.jobs.import_chinatravel --parquet tmp_t\ct_eval\attractions_zh.parquet --kind attraction --assume auto >> "%LOG%" 2>&1 || goto :fail
"%PY%" -m app.jobs.import_chinatravel --parquet tmp_t\ct_eval\poi_zh.parquet --kind restaurant --assume auto >> "%LOG%" 2>&1 || goto :fail

rem 2. backsource upgrade (amap match + ctrip/amap detail), city loop inside python
rem    (cmd for-loops break on quoted %PY% with spaces + Chinese args); 200/city quota,
rem    leftover rows continue via 02:00 daily rotate task
"%PY%" -c "import subprocess,sys; cities=open(r'data/fill_cities.txt',encoding='utf-8').read().split(); sys.exit(max(subprocess.call([sys.executable,'-m','app.jobs.refresh_pois','--city',c,'--match','--limit','200']) for c in cities))" >> "%LOG%" 2>&1

rem 3. time-window attrs + intro (fill-empty-only, idempotent)
"%PY%" -m app.jobs.backfill_best_visit --stage heuristic --limit 5000 >> "%LOG%" 2>&1
"%PY%" -m app.jobs.backfill_intro --limit 2000 >> "%LOG%" 2>&1

rem 4. quality tags (only if manual black-pearl CSV present)
if exist data\black_pearl.csv "%PY%" -m app.jobs.tag_quality --csv data\black_pearl.csv --kind black_pearl >> "%LOG%" 2>&1

echo [%date% %time%] === fill now OK === >> "%LOG%"
exit /b 0
:fail
echo [%date% %time%] === fill now FAILED (see devlogs\poi_fill_now.log) ===
exit /b 1
