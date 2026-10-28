@echo off
setlocal
cd /d "%~dp0"
if exist .venv\Scripts\python.exe goto install
py -3.10 -m venv .venv
if not errorlevel 1 goto install
python -c "import sys; assert (3,10) <= sys.version_info[:2] < (3,14)"
if errorlevel 1 goto failed
python -m venv .venv
if errorlevel 1 goto failed
:install
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Open http://127.0.0.1:8000 in your browser. Keep this window running.
.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port 8000
if errorlevel 1 goto failed
exit /b 0
:failed
echo Setup or startup failed. Python 3.10-3.13 is required. Check the error above.
pause
exit /b 1
