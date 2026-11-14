@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python not found. Install Python 3.11+ and try again.
  pause
  exit /b 1
)
py -m pip install -r requirements.txt
if errorlevel 1 (
  echo Unable to install dependencies.
  pause
  exit /b 1
)
start "" "http://127.0.0.1:8000"
echo Local app: http://127.0.0.1:8000
py -m uvicorn main:app --host 127.0.0.1 --port 8000
pause
