@echo off
REM football_db_v2 weekly job. Schedule: Tuesday 05:00, StartWhenAvailable=True.
REM Uses the 3.13 interpreter by full path - bare python is 3.14.
REM ASCII only and no parentheses: cmd.exe mis-tokenizes them even in REM lines.
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
"C:\Users\k-ble\AppData\Local\Programs\Python\Python313\python.exe" -m fdb weekly
exit /b %ERRORLEVEL%
