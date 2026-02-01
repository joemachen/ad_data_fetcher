@echo off
REM Microsoft Ads OAuth Setup – generate refresh token
REM Run this to get a refresh_token for microsoft-ads.yaml (opens a console)

setlocal

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if not exist "venv" (
    echo Error: Virtual environment not found. Please run run.bat first to create it.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
if errorlevel 1 (
    echo Error: Failed to activate virtual environment
    pause
    exit /b 1
)

pip show bingads >nul 2>&1
if errorlevel 1 (
    echo Installing bingads...
    pip install bingads
    if errorlevel 1 (
        echo Error: Failed to install bingads
        pause
        exit /b 1
    )
)

echo.
echo Running Microsoft Ads OAuth setup...
echo.
venv\Scripts\python.exe setup_ms_auth.py

pause
