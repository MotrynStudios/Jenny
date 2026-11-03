@echo off
REM Start Jenny using the repository virtual environment when present.
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "Jenny\Jenny-Bot.py"
) else (
    py -3.10 "Jenny\Jenny-Bot.py"
)
pause

