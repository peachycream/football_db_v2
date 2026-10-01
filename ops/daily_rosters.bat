@echo off
rem football_db v2 daily roster refresh, MFL and Sleeper (Turon 2026-09-30/10-01: ownership pools
rem show the latest moves). Run by Task Scheduler "FootballDB v2 Rosters": daily 06:00, HEADLESS
rem (conhost --headless), StartWhenAvailable. Each run is a new snapshot per league (raw kept
rem newest-per-day); /ownership/ reads the latest. Exit is non-zero if EITHER platform failed.
rem The 3.13 interpreter BY FULL PATH (bare python is 3.14, no Flask). Log: data\logs\rosters.log
setlocal
set PY="C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe"
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
echo ==================== %DATE% %TIME% ==================== >> data\logs\rosters.log
%PY% -m fdb update mfl.rosters --apply >> data\logs\rosters.log 2>&1
set RC_MFL=%ERRORLEVEL%
%PY% -m fdb update sleeper.rosters --apply >> data\logs\rosters.log 2>&1
set RC_SLP=%ERRORLEVEL%
set RC=0
if not "%RC_MFL%"=="0" set RC=1
if not "%RC_SLP%"=="0" set RC=1
echo exit=%RC% (mfl=%RC_MFL% sleeper=%RC_SLP%) >> data\logs\rosters.log
exit /b %RC%
