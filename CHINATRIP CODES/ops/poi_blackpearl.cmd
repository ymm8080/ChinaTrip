@echo off
rem Black Pearl monthly check (2nd, 04:30). Fully automated since 2026-10-24:
rem downloads jyb635050-ai/gourmet-map zip via codeload.github.com (no VPN
rem needed), extracts blackpearl.json (geocoded 2026 list, WGS84) and the
rem ungeocoded source list, then runs tag_quality twice -- union tagging;
rem unmatched entries in covered cities are appended as skeleton rows.
rem Download via ops\fetch_url.py (urllib) - curl.exe hangs in cmd/schtasks
rem context on CN network (2026-10-24 live incident).
rem Log: devlogs\poi_blackpearl.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\poi_blackpearl.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === blackpearl check start === >> "%LOG%"
"%PY%" "%~dp0fetch_url.py" "https://codeload.github.com/jyb635050-ai/gourmet-map/zip/refs/heads/main" data\gourmet_map.zip 300 >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [%date% %time%] download failed >> "%LOG%"
  goto :done
)
"%PY%" -c "import zipfile,shutil;z=zipfile.ZipFile('data/gourmet_map.zip');z.extract('gourmet-map-main/data/blackpearl.json','.');z.extract('gourmet-map-main/data/source/blackpearl_ungeocoded.json','.');shutil.move('gourmet-map-main/data/blackpearl.json','data/blackpearl.json');shutil.move('gourmet-map-main/data/source/blackpearl_ungeocoded.json','data/blackpearl_ungeocoded.json');shutil.rmtree('gourmet-map-main')" >> "%LOG%" 2>&1
del data\gourmet_map.zip >nul 2>&1
if not exist data\blackpearl.json (
  echo [%date% %time%] extract failed >> "%LOG%"
  goto :done
)
"%PY%" -m app.jobs.tag_quality --csv data\blackpearl.json --kind black_pearl >> "%LOG%" 2>&1
"%PY%" -m app.jobs.tag_quality --csv data\blackpearl_ungeocoded.json --kind black_pearl >> "%LOG%" 2>&1
:done
echo [%date% %time%] === blackpearl check done === >> "%LOG%"
