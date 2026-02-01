@echo off
REM Ads Report Fetcher - Debug launcher (console stays open, shows log and errors)
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
call venv\Scripts\activate.bat 2>nul
echo Launching Ads Report Fetcher (debug - console will show log)...
venv\Scripts\python.exe main.py
if errorlevel 1 echo. & echo Application exited with an error.
echo.
pause
