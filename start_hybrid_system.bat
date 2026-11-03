@echo off
REM Hybrid Jenny System Launcher
REM Starts both Python Jenny bot and Node.js voice service

cd /d "%~dp0"

echo ====================================
echo Starting Hybrid Jenny System
echo ====================================
echo.

REM Check if Python API server is accessible
echo [1/3] Checking Python API server...
curl -s http://127.0.0.1:8000/health >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python API server not running!
    echo Please start Jenny bot first:
    echo   .venv\Scripts\python.exe Jenny\Jenny-Bot.py
    pause
    exit /b 1
)
echo [OK] Python API server is running
echo.

REM Start Node.js voice service
echo [2/3] Starting Node.js voice service...
if not exist voice_service\node_modules (
    echo Installing Node.js dependencies...
    cd voice_service
    call npm.cmd install
    cd ..
)
cd voice_service
start "Jenny Voice Service" /D "%~dp0voice_service" cmd /k "node index.js"
cd ..
echo [OK] Voice service started in new window
echo.

echo [3/3] System startup complete!
echo.
echo ====================================
echo Hybrid Jenny System Running
echo ====================================
echo.
echo Windows running:
echo 1. Jenny Bot (Python) - with RAG integration
echo 2. Voice Service (Node.js) - handles voice capture and speech output
echo.
echo Voice commands:
echo - /joinvc and /leavevc control server voice connections
echo - Mention Jenny or say her name to get a voice reply
echo.
echo Press any key to exit this launcher (bots will continue running)
pause >nul

