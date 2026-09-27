@echo off
REM Starts Study Buddy and opens it in your browser (http://127.0.0.1:8765).
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m studybuddy.server
pause
