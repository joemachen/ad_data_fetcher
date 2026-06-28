@echo off
REM Meta Ads - re-authentication launcher. Opens a console so the user can paste a new
REM access token. Run from source (venv required).
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"
call venv\Scripts\activate.bat 2>nul
venv\Scripts\python.exe setup_meta_auth.py
echo.
pause
