@echo off
setlocal
cd /d "%~dp0"

rem Reuse an already running instance instead of starting a second server.
curl.exe --silent --show-error --fail --max-time 2 http://127.0.0.1:8000/api/config >nul 2>&1
if not errorlevel 1 (
  echo Tender checker is already running at http://127.0.0.1:8000
  exit /b 0
)

if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv
  if errorlevel 1 python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
