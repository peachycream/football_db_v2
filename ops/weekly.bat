@echo off
rem football_db v2 weekly job (REBUILD_DESIGN section 7). Run by Task Scheduler "FootballDB v2 Weekly":
rem HEADLESS (conhost --headless), Wednesday 05:00, StartWhenAvailable (Turon 2026-09-30: MNF weeks settle ~Wed 00:15 ET). The 3.13 interpreter BY FULL PATH (bare python is 3.14, no Flask).
rem Output appends to data\logs\weekly.log; the result is also in PIPELINE_STATUS.json and the Discord alert.
setlocal
set PY="C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe"
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
echo ==================== %DATE% %TIME% ==================== >> data\logs\weekly.log
%PY% -m fdb weekly >> data\logs\weekly.log 2>&1
set RC=%ERRORLEVEL%
echo exit=%RC% >> data\logs\weekly.log
exit /b %RC%
