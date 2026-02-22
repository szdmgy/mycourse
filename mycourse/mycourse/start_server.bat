@echo off
chcp 65001 >nul 2>&1

set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] venv not found. Please run: python -m venv venv
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo [INFO] Cleaning residual processes on port 8001 ...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8001 " ^| findstr "LISTENING"') do (
    echo   Killing PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
)

venv\Scripts\python.exe show_routes.py 8001

echo [INFO] Starting Waitress production server on port 8001 ...
echo.
waitress-serve --host=0.0.0.0 --port=8001 mycourse.wsgi:application
pause
