@echo off
setlocal

set BASE=C:\Users\Zohair\Desktop\Zohair\OfficePilot AI\quotation-agent
set PYTHON=%BASE%\venv\Scripts\python.exe
set SCRIPT=%BASE%\run_prod.py
set LOGFILE=%BASE%\startup.log

cd /d "%BASE%"

echo. >> "%LOGFILE%"
echo ===================================================== >> "%LOGFILE%"
echo Started: %date% %time% >> "%LOGFILE%"
echo ===================================================== >> "%LOGFILE%"

:: Guard: skip if already running on port 8000
netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (
    echo Already running on port 8000 -- skipping. >> "%LOGFILE%"
    exit /b 0
)

:: Verify venv Python exists
if not exist "%PYTHON%" (
    echo ERROR: venv Python not found: %PYTHON% >> "%LOGFILE%"
    exit /b 1
)

:: Verify run_prod.py exists
if not exist "%SCRIPT%" (
    echo ERROR: Script not found: %SCRIPT% >> "%LOGFILE%"
    exit /b 1
)

echo Python: %PYTHON% >> "%LOGFILE%"
echo Script: %SCRIPT% >> "%LOGFILE%"
echo. >> "%LOGFILE%"

:: Run — stdout + stderr go to startup.log
"%PYTHON%" "%SCRIPT%" >> "%LOGFILE%" 2>&1

echo. >> "%LOGFILE%"
echo Exit code: %errorlevel% at %date% %time% >> "%LOGFILE%"
