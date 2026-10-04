@echo off
rem football_db v2 mid-week status alerts (Phase 13). NOT scheduled yet: register it only when Turon says so.
rem One refresh of all three injury feeds (NFL report file, MFL, ESPN) and one push of whatever changed since the last
rem run: practice reports Wed-Fri, Friday designations, news that moves a status. Intended hourly (not every 2 minutes);
rem ops\alerts_watch.bat takes over inside game windows. Needs NTFY_TOPIC in .env and a baseline (alerts --seed).
rem Log: data\logs\alerts_midweek.log
setlocal
set PY="C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe"
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
echo ==================== %DATE% %TIME% ==================== >> data\logs\alerts_midweek.log
%PY% -m fdb alerts --refresh --send >> data\logs\alerts_midweek.log 2>&1
set RC=%ERRORLEVEL%
echo exit=%RC% >> data\logs\alerts_midweek.log
exit /b %RC%
