@echo off
REM Ads Report Fetcher - Launcher (no console; only app window in taskbar)
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
call venv\Scripts\activate.bat 2>nul
start "" venv\Scripts\pythonw.exe main.py
