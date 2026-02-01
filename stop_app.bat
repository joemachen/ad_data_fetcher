@echo off
REM Ads Report Fetcher - Stop All Running Instances
REM This script kills all running Python processes for the application

setlocal

echo.
echo ========================================
echo Stopping Ads Report Fetcher...
echo ========================================
echo.

REM Check for pythonw.exe processes (GUI version)
tasklist /FI "IMAGENAME eq pythonw.exe" 2>NUL | find /I /N "pythonw.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Found pythonw.exe processes. Killing...
    taskkill /F /IM pythonw.exe >NUL 2>&1
    if errorlevel 1 (
        echo Warning: Failed to kill some pythonw.exe processes (may require admin rights)
    ) else (
        echo Successfully stopped pythonw.exe processes.
    )
) else (
    echo No pythonw.exe processes found.
)

REM Also check for python.exe processes (debug/console version)
tasklist /FI "IMAGENAME eq python.exe" 2>NUL | find /I /N "python.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo Found python.exe processes. Checking if they're running main.py...
    REM Try to kill python.exe processes - user can choose to skip if needed
    echo Killing python.exe processes...
    taskkill /F /IM python.exe >NUL 2>&1
    if errorlevel 1 (
        echo Warning: Failed to kill some python.exe processes (may require admin rights)
    ) else (
        echo Successfully stopped python.exe processes.
    )
) else (
    echo No python.exe processes found.
)

echo.
echo ========================================
echo Done.
echo ========================================
echo.

timeout /t 2 >NUL
