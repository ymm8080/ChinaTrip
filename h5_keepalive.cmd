@echo off
rem ---- chinatrip H5 keepalive (hardened 2026-11-13, "network error" incident) ----
rem OLD: /health not answering within 15s -> taskkill the whole tree at once.
rem Planning blocks the event loop in bursts (measured: /health up to 8s slow during a
rem 39s plan/start; heavier loads longer), so one slow burst read as "frozen" -> tree
rem killed -> browser showed "Network error: cannot reach the API".
rem NEW: (1) /health timeout 20s; (2) two consecutive failures required (checks run
rem once a minute); (3) a failing check is excused while the process still burns CPU
rem (busy != frozen); (4) strike count persisted, reset on success / kill.
rem NOTE: plain goto flow, no parenthesised if-blocks - ")" inside echo text used to
rem close the block early and abort the script with "- was unexpected at this time".
setlocal enabledelayedexpansion
if "%PORT%"=="" set PORT=8000
if "%TASK%"=="" set TASK=chinatrip_h5_8000
if "%STRIKES%"=="" set STRIKES=D:\chinatrip\keepalive_strikes.txt
if "%KLOG%"=="" set KLOG=D:\chinatrip\keepalive.log
if "%HEALTH_WAIT%"=="" set HEALTH_WAIT=20
if "%MAX_STRIKES%"=="" set MAX_STRIKES=2

set STRIKE=0
if exist "%STRIKES%" set /p STRIKE=<"%STRIKES%"
if "!STRIKE!"=="" set STRIKE=0

netstat -ano | findstr ":%PORT%" | findstr "LISTENING" >nul
if errorlevel 1 goto startport

curl.exe -sf --max-time %HEALTH_WAIT% -o NUL http://127.0.0.1:%PORT%/health
if not errorlevel 1 goto healthok

set PID=
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do set PID=%%p

set BUSY=1
if "!PID!"=="" goto afterbusy
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p=Get-Process -Id !PID! -ErrorAction SilentlyContinue; if($p -ne $null){$a=$p.TotalProcessorTime.TotalMilliseconds; Start-Sleep -Milliseconds 900; $p.Refresh(); $b=$p.TotalProcessorTime.TotalMilliseconds; if(($b-$a) -gt 120){exit 0}}; exit 1" >nul 2>&1
if not errorlevel 1 set BUSY=0
:afterbusy

if "!BUSY!"=="0" goto busyexempt

set /a STRIKE=STRIKE+1
if !STRIKE! LSS %MAX_STRIKES% goto strike1

>>"%KLOG%" echo [%date% %time%] port %PORT% health check failed %MAX_STRIKES% times - killing frozen tree, pid !PID!
if not "!PID!"=="" taskkill /F /T /PID !PID! >nul 2>&1
>"%STRIKES%" echo 0
ping -n 4 127.0.0.1 >nul
goto startport

:strike1
>>"%KLOG%" echo [%date% %time%] port %PORT% health check failed, strike !STRIKE! of %MAX_STRIKES% - not killing yet
>"%STRIKES%" echo !STRIKE!
goto checkother

:busyexempt
>>"%KLOG%" echo [%date% %time%] port %PORT% health slow but pid !PID! is burning CPU - busy, not frozen; strike reset
>"%STRIKES%" echo 0
goto checkother

:healthok
>"%STRIKES%" echo 0
goto checkother

:startport
schtasks /run /tn %TASK%

:checkother
rem ---- 8443: port check only (TLS instance, no health kill) ----
netstat -ano | findstr ":8443" | findstr "LISTENING" >nul
if errorlevel 1 schtasks /run /tn chinatrip_h5_tls
