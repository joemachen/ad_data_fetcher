@echo off
REM Google Ads API Setup Script
REM Runs the authentication setup tool

setlocal

REM Get the directory where this batch file is located
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Check if virtual environment exists
if not exist "venv" (
    echo Error: Virtual environment not found. Please run run.bat first to create it.
    pause
    exit /b 1
)

REM Activate virtual environment
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo Error: Failed to activate virtual environment
    pause
    exit /b 1
)

REM Check if requirements are installed
echo Checking dependencies...
pip show google-ads >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo Error: Failed to install dependencies
        pause
        exit /b 1
    )
)

REM Run setup script (using python.exe so user can see output)
echo.
echo Running Google Ads API Setup...
echo.
venv\Scripts\python.exe setup_auth.py

pause
