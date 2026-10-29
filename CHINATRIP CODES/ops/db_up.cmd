@echo off
rem Ensure DB reachable: wake WSL VM (systemd auto-starts postgresql), wait up to ~40s
rem WSL: Ubuntu 26.04 + PostgreSQL 18 + PostGIS 3.6; Windows reaches it via localhost:5432
wsl.exe -d Ubuntu -e true 2>nul
set /a DBUP_I=0
:waitpg
wsl.exe -d Ubuntu -e pg_isready -q 2>nul
if not errorlevel 1 goto :ok
set /a DBUP_I+=1
if %DBUP_I% lss 20 (
  timeout /t 2 /nobreak >nul
  goto :waitpg
)
echo [%date% %time%] WARN: postgres not ready after %DBUP_I% tries >> "%DB_LOGFILE%"
:ok
exit /b 0
