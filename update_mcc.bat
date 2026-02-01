@echo off
REM Update MCC ID Script
REM Updates login_customer_id in google-ads.yaml

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

REM Run update script
venv\Scripts\python.exe update_mcc_id.py

pause
