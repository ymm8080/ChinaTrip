@echo off
rem baidu geocode 日配额重置后坐标续跑（2026-11-03 排程，一次性）：
rem 清台账（先备份）→ 主轮（规划池）→ extras（池外）→ 残留计数写日志
rem Log: devlogs\coords_round4.log
cd /d "D:\CHINATRIP\CHINATRIP CODES"
set "PY=%~dp0..\.venv\Scripts\python.exe"
call "%~dp0db_up.cmd"
set "LOG=devlogs\coords_round4.log"
if not exist devlogs mkdir devlogs
echo [%date% %time%] === coords round4 start === >> "%LOG%"
copy /y ops\backfill_coords_missed.txt ops\backfill_coords_missed.txt.bak-20261104 >nul
type nul > ops\backfill_coords_missed.txt
"%PY%" ops\backfill_coords_driver.py --limit 10000 >> "%LOG%" 2>&1
"%PY%" ops\backfill_coords_driver.py --limit 10000 --extras >> "%LOG%" 2>&1
"%PY%" -c "import psycopg;c=psycopg.connect('postgresql://chinatrip:chinatrip@localhost:5432/chinatrip',connect_timeout=10);cur=c.cursor();cur.execute(\"select count(*) from pois where status='active' and location is null\");print('active location NULL:',cur.fetchone()[0])" >> "%LOG%" 2>&1
echo [%date% %time%] === coords round4 done === >> "%LOG%"
