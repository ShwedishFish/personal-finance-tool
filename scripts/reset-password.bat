@echo off
rem Remove the app password if you forget it (your data is not encrypted with it, so nothing is lost).
setlocal
cd /d "%~dp0.."
set PYTHONPATH=backend
.venv\Scripts\python.exe -m app.auth reset
pause
