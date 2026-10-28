@echo off
rem 每日 06:30 OSM 日增增量（定稿实测+1：上游北京 04:20-05:30 发布，06:30 定在窗口后）
rem 下载器按水位文件只取未应用文件，延迟日自动补拉；落库幂等可重跑
rem 日志: devlogs\poi_osm_daily.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_osm_daily.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === osm daily start === >> "%LOG%"

set "FETCHED=%TEMP%\osm_fetched.txt"
"%PY%" -m app.jobs.osm_fetch --dir data\osm --state data\osm_state.json > "%FETCHED%" 2>> "%LOG%"
for /f "usebackq delims=" %%f in (`type "%FETCHED%"`) do (
  if not "%%f"=="NONE" (
    "%PY%" -m app.jobs.osm_diff --osc "%%f" >> "%LOG%" 2>&1
    rem 应用成功即删 osc.gz（水位已推进，D 盘空间紧张；失败保留待下次复用）
    if not errorlevel 1 del "%%f"
  )
)
rem Heuristic sweep: classify rows inserted outside seed_upsert + duration floors
rem (real sources ctrip/qunar may upgrade heuristic values, no fill-only block)
"%PY%" -m app.jobs.enrich_heuristics --with-duration --limit 2000 >> "%LOG%" 2>&1
echo [%date% %time%] === osm daily done === >> "%LOG%"
