@echo off
rem ============ ONE-COMMAND DEPLOY (the only command to remember) ============
rem git pull -> kill old processes -> restart via schtasks (start scripts run
rem DB migration automatically) -> health check. Run this after code is pushed.
cd /d %~dp0
echo [1/4] git pull --ff-only ...
git pull --ff-only
if errorlevel 1 (
  echo GIT_PULL_FAILED - stash or commit local changes first
  exit /b 1
)
echo [2/4] restart services (migration runs inside start scripts) ...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /F /T /PID %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8443" ^| findstr "LISTENING"') do taskkill /F /T /PID %%p >nul 2>&1
schtasks /run /tn chinatrip_h5_8000 >nul
schtasks /run /tn chinatrip_h5_tls >nul
echo [3/4] waiting for boot (incl. auto migrate) ...
ping.exe -n 13 127.0.0.1 >nul
echo [4/4] health check ...
curl.exe -sf --max-time 20 http://127.0.0.1:8000/health >nul
if errorlevel 1 (
  echo 8000 HEALTH_FAIL - see D:\chinatrip\uvicorn_h5_1018e.log
  exit /b 1
)
echo   8000 OK
curl.exe -skf --max-time 20 https://127.0.0.1:8443/health >nul
if errorlevel 1 (
  echo 8443 HEALTH_FAIL - see D:\chinatrip\uvicorn_h5_1018e_tls.log
  exit /b 1
)
echo   8443 OK
echo DEPLOY_DONE - frontend sw version auto-updates on users next visit
