@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

cd /d "%~dp0mycourse\mycourse"

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] venv not found. Please run: python -m venv venv
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo.
echo [INFO] Cleaning residual processes on port 9900 ...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":9900 " ^| findstr "LISTENING"') do (
    echo   Killing PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
)

venv\Scripts\python.exe show_routes.py 9900

echo [INFO] Starting Django development server on port 9900 ...
echo.
python manage.py runserver 0.0.0.0:9900
pause
