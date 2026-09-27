@echo off
REM One-time setup: creates a virtual environment and installs dependencies.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
%PY% -m venv .venv || goto :err
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :err
if not exist .env copy .env.example .env >nul
echo.
echo Setup done. Open .env and paste your OpenAI API key, then run run.bat
pause
exit /b 0
:err
echo Setup failed - see the error above.
pause
exit /b 1
