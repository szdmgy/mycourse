@echo off
setlocal
chcp 65001 >nul
set PROJECT_NAME=mycourse
set PORT=8001

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
echo [INFO] Cleaning residual processes on port %PORT% ...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    echo   Killing PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
)

venv\Scripts\python.exe show_routes.py %PORT%

echo [INFO] Starting Waitress production server on port %PORT% ...
echo.
waitress-serve --host=0.0.0.0 --port=%PORT% mycourse.wsgi:application
