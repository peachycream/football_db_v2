@echo off
rem football_db v2 web app on http://127.0.0.1:5000 (Phase 8 cutover: v2 serves :5000).
rem Run at logon by Task Scheduler "FootballDB v2 App", HEADLESS (conhost --headless): there is
rem no window to close by accident (a closed console killed the app on 2026-09-29).
rem If the app ever exits it is restarted after 10 s; to stop it, disable the task.
setlocal
set PY="C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe"
set PYTHONIOENCODING=utf-8
set APP_PORT=5000
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
:loop
echo ==================== %DATE% %TIME% start ==================== >> data\logs\app.log
%PY% -m app >> data\logs\app.log 2>&1
echo ==================== %DATE% %TIME% app exited (code %ERRORLEVEL%); restarting in 10 s ==================== >> data\logs\app.log
timeout /t 10 /nobreak > nul
goto loop
