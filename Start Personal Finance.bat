@echo off
rem Double-click to start the app and open it in your browser. Close this window to stop it.
setlocal
cd /d "%~dp0"
if "%PFT_PORT%"=="" set PFT_PORT=8020
set URL=http://127.0.0.1:%PFT_PORT%/

if not exist .venv\Scripts\python.exe (
  py -3 -m venv .venv 2>nul || python -m venv .venv
  if errorlevel 1 (
    echo Python 3.11 or newer is required: https://www.python.org/downloads/
    pause
    exit /b 1
  )
)
.venv\Scripts\python.exe -m pip install --quiet --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Installing requirements failed.
  pause
  exit /b 1
)

start "" powershell -NoProfile -WindowStyle Hidden -Command "for ($i=0; $i -lt 60; $i++) { try { Invoke-WebRequest -UseBasicParsing '%URL%api/health' | Out-Null; Start-Process '%URL%'; break } catch { Start-Sleep -Milliseconds 500 } }"
echo Personal Finance Tool is running at %URL%. Your data stays on this computer.
echo Close this window to stop it.
.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port %PFT_PORT%
