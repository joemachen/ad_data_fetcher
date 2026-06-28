@echo off
REM Reddit Ads - re-authentication launcher. Opens a console so the user can log in
REM and paste the callback URL. Run from source (venv required).
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
call venv\Scripts\activate.bat 2>nul
venv\Scripts\python.exe setup_reddit_auth.py
echo.
pause
