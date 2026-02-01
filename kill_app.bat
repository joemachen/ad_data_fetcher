@echo off
REM Ads Report Fetcher - Force Kill All Instances
REM This script forcefully kills all Python processes

setlocal

echo.
echo ========================================
echo Force Killing Ads Report Fetcher...
echo ========================================
echo.

REM Kill pythonw.exe (GUI version - no console window)
taskkill /F /IM pythonw.exe >NUL 2>&1
if errorlevel 1 (
    echo No pythonw.exe processes found or unable to kill.
) else (
    echo Killed pythonw.exe processes.
)

REM Kill python.exe (console version)
taskkill /F /IM python.exe >NUL 2>&1
if errorlevel 1 (
    echo No python.exe processes found or unable to kill.
) else (
    echo Killed python.exe processes.
)

echo.
echo ========================================
echo Done. All Python processes terminated.
echo ========================================
echo.

timeout /t 1 >NUL
