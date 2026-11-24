@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run: creating virtual environment and installing packages...
    python -m venv .venv
    if errorlevel 1 goto fail
    ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
    if errorlevel 1 goto fail
)

".venv\Scripts\python.exe" gui.py
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo Something went wrong - see the messages above.
pause
exit /b 1
