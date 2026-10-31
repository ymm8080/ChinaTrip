@echo off
cd /d "D:\chinatrip\CHINATRIP CODES"
rem auto DB migrate before uvicorn (alembic upgrade head; never blocks boot) - deploy with zero memory, 2026-11-01
"D:\CHINATRIP\CHINATRIP CODES\.venv\Scripts\python.exe" "D:\CHINATRIP\CHINATRIP CODES\ops\auto_migrate.py" >> "D:\chinatrip\uv_h5.log" 2>&1
"C:\Users\91454\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> "D:\chinatrip\uv_h5.log" 2>&1
