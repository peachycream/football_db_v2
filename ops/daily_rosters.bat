@echo off
rem football_db v2 daily MFL roster refresh (Turon 2026-09-30: ownership pools show the latest moves).
rem Run by Task Scheduler "FootballDB v2 Rosters": daily 06:00, HEADLESS (conhost --headless), StartWhenAvailable.
rem Each run is a new mfl.rosters snapshot (raw kept newest-per-day); /ownership/ reads the latest one.
rem The 3.13 interpreter BY FULL PATH (bare python is 3.14, no Flask). Log: data\logs\rosters.log
setlocal
set PY="C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe"
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
echo ==================== %DATE% %TIME% ==================== >> data\logs\rosters.log
%PY% -m fdb update mfl.rosters --apply >> data\logs\rosters.log 2>&1
set RC=%ERRORLEVEL%
echo exit=%RC% >> data\logs\rosters.log
exit /b %RC%
