@echo off
REM Ads Report Fetcher - One Click Launcher
REM This script sets up the Python environment and launches the application

setlocal

REM Get the directory where this batch file is located
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

REM Check if virtual environment exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo Error: Failed to create virtual environment
        echo Please ensure Python is installed and in your PATH
        pause
        exit /b 1
    )
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
pip show customtkinter >nul 2>&1
if errorlevel 1 (
    echo Installing/updating dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo Error: Failed to install dependencies
        pause
        exit /b 1
    )
    echo Dependencies installed successfully.
) else (
    REM Also check for facebook-business (Meta Ads support)
    pip show facebook-business >nul 2>&1
    if errorlevel 1 (
        echo Installing missing dependencies...
        pip install -r requirements.txt
        if errorlevel 1 (
            echo Error: Failed to install dependencies
            pause
            exit /b 1
        )
    )
)

REM Launch application with pythonw (no console window - runs silently)
echo Launching Ads Report Fetcher...
start "" venv\Scripts\pythonw.exe main.py
exit /b 0
