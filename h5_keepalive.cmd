@echo off
rem ---- 8000: port down -> start; port up but /health fails or times out (15s) -> frozen, kill tree and restart ----
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if errorlevel 1 goto start8000
curl.exe -sf --max-time 15 -o NUL http://127.0.0.1:8000/health
if not errorlevel 1 goto check8443
echo [%date% %time%] 8000 health check failed, killing frozen tree >> D:\chinatrip\keepalive.log
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /F /T /PID %%p >nul 2>&1
timeout /t 3 /nobreak >nul
:start8000
schtasks /run /tn chinatrip_h5_8000
:check8443
rem ---- 8443: port check only (TLS instance, no health kill) ----
netstat -ano | findstr ":8443" | findstr "LISTENING" >nul
if errorlevel 1 schtasks /run /tn chinatrip_h5_tls
