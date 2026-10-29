@echo off
cd /d "D:\chinatrip\CHINATRIP CODES"
"C:\Users\91454\AppData\Local\Programs\Python\Python312\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile D:\chinatrip\h5key.pem --ssl-certfile D:\chinatrip\h5cert.pem >> D:\chinatrip\uvicorn_h5_1018e_tls.log 2>&1
