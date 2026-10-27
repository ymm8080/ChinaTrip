@echo off
rem Weather dual-track fetch (DESIGN/database_design.md S6.2 matrix row):
rem   short track follows MAP_PROVIDER (baidu since 2026-10-28: live + 7d fc;
rem   was amap in the same slot) + Open-Meteo 14d daily (keyless)
rem Runs ONCE daily 08:10, right after the CMA morning forecast update (~08:00 CST)
rem No args = trip cities only (quota-safe); latest-wins, idempotent
rem Log: devlogs\weather_fetch.log  (keep comments ASCII: cmd.exe reads GBK)
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
set "LOG=devlogs\weather_fetch.log"
if not exist devlogs mkdir devlogs
rem Keep the WSL VM alive for the job: WSL2 idles out the VM (~60s) with no
rem wsl.exe process running, which stops PG mid-job ("administrator command"
rem shutdown in PG log). A live wsl.exe sleep holds it for the whole run.
start "wx-keepalive" /min cmd /c "wsl.exe -d Ubuntu -e sleep 420"
echo [%date% %time%] === weather fetch start === >> "%LOG%"
call "%~dp0db_up.cmd"
"%PY%" -m app.jobs.fetch_weather >> "%LOG%" 2>&1
echo [%date% %time%] === weather fetch done (exit %errorlevel%) === >> "%LOG%"
