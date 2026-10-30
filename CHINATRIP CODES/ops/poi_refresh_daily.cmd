@echo off
rem 每日 02:00 回源刷新（定稿时机）：地址/营业时间，链序携程先-高德V5详情-高德搜索兜底
rem --rotate 按 weekday 城轮转（每天约 1/7 城市负载，防风控）；--match 骨架行先高德回源升级
rem 日志: devlogs\poi_refresh_daily.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_refresh_daily.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === refresh daily start === >> "%LOG%"
"%PY%" -m app.jobs.refresh_pois --match --limit 2500 >> "%LOG%" 2>&1
echo [%date% %time%] === refresh daily done rc=%errorlevel% === >> "%LOG%"
