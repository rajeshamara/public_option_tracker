@echo off
cd /d "%~dp0backend"
if exist "..\.venv\Scripts\python.exe" (
  "..\.venv\Scripts\python.exe" run.py
) else (
  python run.py
)
pause
