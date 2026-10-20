@echo off
setlocal
set OPTIONTRACKER_DEMO=1
cd /d "%~dp0backend"
if exist "..\.venv\Scripts\python.exe" (
  "..\.venv\Scripts\python.exe" run.py
) else (
  python run.py
)
pause
