@echo off
rem football_db v2 game-day alert watcher (Phase 13). NOT scheduled yet: register it only when Turon says so.
rem Polls ESPN every 2 min inside each game's window (2 h before kickoff until kickoff), pushes status changes and the
rem 15-minute "NOT CONFIRMED" check through ntfy, and exits by itself when no window opens within 14 h. So a DAILY start
rem (say 06:00, StartWhenAvailable, headless like ops\daily_rosters.bat) covers Thursday, Sunday and Monday and does
rem nothing on a day without games. A second copy refuses to start (alerts_watch.lock next to the database).
rem Needs NTFY_TOPIC in .env and a recorded baseline (python -m fdb alerts --seed). Log: data\logs\alerts_watch.log
setlocal
set PY="C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe"
set PYTHONIOENCODING=utf-8
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
echo ==================== %DATE% %TIME% ==================== >> data\logs\alerts_watch.log
%PY% -m fdb alerts --watch --send >> data\logs\alerts_watch.log 2>&1
set RC=%ERRORLEVEL%
echo exit=%RC% >> data\logs\alerts_watch.log
exit /b %RC%
