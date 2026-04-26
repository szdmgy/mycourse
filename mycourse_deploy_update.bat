@echo off
setlocal EnableDelayedExpansion
chcp 65001 >nul

REM ====== 固定配置（按你的仓库修改）======
set "REPO_URL=https://github.com/szdmgy/mycourse.git"
set "BRANCH=master"
set "PROJECT_NAME=mycourse"
set "PY_CMD=py -3"
REM Django 代码与 manage.py 相对仓库根目录的路径（本仓库为双层 mycourse）
set "DJANGO_SUBPATH=mycourse\mycourse"
REM 虚拟环境目录名（与 run_local.bat / start_server.bat 一致）
set "VENV_NAME=venv"
REM 若服务器无 py 启动器，可改为：set "PY_CMD=python"
REM =====================================

set "SCRIPT_DIR=%~dp0"

set "MODE="
set "PROJECT_DIR="
set "SCRIPT_REPO_DIR=%SCRIPT_DIR%"
set "CHILD_REPO_DIR=%SCRIPT_DIR%\%PROJECT_NAME%"

REM 模式判定：Git 根目录含 .git，且存在 manage.py（本仓库在子目录）
if exist "%SCRIPT_REPO_DIR%\.git" (
  if exist "%SCRIPT_REPO_DIR%\%DJANGO_SUBPATH%\manage.py" (
    set "MODE=UPDATE"
    set "PROJECT_DIR=%SCRIPT_REPO_DIR%"
  )
)

if not defined MODE (
  if exist "%CHILD_REPO_DIR%\.git" (
    if exist "%CHILD_REPO_DIR%\%DJANGO_SUBPATH%\manage.py" (
      set "MODE=UPDATE"
      set "PROJECT_DIR=%CHILD_REPO_DIR%"
    )
  )
)

if not defined MODE (
  set "MODE=FIRST_DEPLOY"
  set "PROJECT_DIR=%CHILD_REPO_DIR%"
)

set "DJANGO_DIR=%PROJECT_DIR%\%DJANGO_SUBPATH%"

echo.
echo ======================================
echo 脚本名称: mycourse_deploy_update.bat
echo 仓库地址: %REPO_URL%
echo 目标分支: %BRANCH%
echo Git 根目录: %PROJECT_DIR%
echo Django 目录: %DJANGO_DIR%
echo 执行模式: %MODE%
echo ======================================
echo.
set /p "USER_CONFIRM=确认继续执行？输入 Y 继续，其它任意键退出: "
if /I not "!USER_CONFIRM!"=="Y" (
  echo 已取消执行。
  exit /b 0
)

if /I "%MODE%"=="FIRST_DEPLOY" (
  call :first_deploy
  exit /b %ERRORLEVEL%
) else (
  call :update_deploy
  exit /b %ERRORLEVEL%
)

:first_deploy
echo.
echo [1/6] 首次部署：检查 Git...
where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 未找到 git，请先安装并加入 PATH。
  exit /b 1
)

echo [2/6] 首次部署：检查 Python...
%PY_CMD% --version >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 不可用，请检查 PY_CMD 配置：%PY_CMD%
  exit /b 1
)

echo [3/6] 首次部署：克隆仓库...
if not exist "%PROJECT_DIR%" mkdir "%PROJECT_DIR%"
git clone -b %BRANCH% %REPO_URL% "%PROJECT_DIR%"
if errorlevel 1 (
  echo [ERROR] git clone 失败。
  exit /b 1
)

if not exist "%DJANGO_DIR%\manage.py" (
  echo [ERROR] 克隆后未找到 manage.py：%DJANGO_DIR%
  exit /b 1
)

cd /d "%DJANGO_DIR%"
echo [4/6] 首次部署：创建虚拟环境（%VENV_NAME%）...
%PY_CMD% -m venv %VENV_NAME%
if errorlevel 1 (
  echo [ERROR] 创建虚拟环境失败。
  exit /b 1
)

call "%VENV_NAME%\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] 激活虚拟环境失败。
  exit /b 1
)

echo [5/6] 首次部署：安装依赖...
python -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] 升级 pip 失败。
  exit /b 1
)
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] 安装 requirements 失败。
  exit /b 1
)

echo [6/6] 首次部署完成（等待你复制运行所需文件）...
echo.
echo 请手动复制以下文件到 Django 目录：
echo   %DJANGO_DIR%
echo   1^) .env（可从同目录的 .env.example 复制后按需填写；仅占位可建空文件）
echo   2^) db.sqlite3（你现有的数据库；代码里若有新迁移，下一步会自动升级库结构）
echo.
echo ────────────────────────────────────────
echo 下一步：请再次双击本脚本并输入 Y。
echo   · 将进入「升级模式」：git pull + 依赖更新
echo   · 然后对本目录下的 db.sqlite3 执行 migrate（把表结构升到当前代码版本）
echo   · 最后 collectstatic
echo 仅克隆代码、尚未复制数据库时，请勿第二次执行（会因缺少 db.sqlite3 而中止）。
echo ────────────────────────────────────────
exit /b 0

:update_deploy
cd /d "%PROJECT_DIR%"

echo.
echo [1/9] 升级：检查 Git...
where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] 未找到 git，请先安装并加入 PATH。
  exit /b 1
)

echo [2/9] 升级：检查 Python...
%PY_CMD% --version >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python 不可用，请检查 PY_CMD 配置：%PY_CMD%
  exit /b 1
)

echo [3/9] 升级：校验仓库状态...
if not exist ".git" (
  echo [ERROR] 当前目录不是 Git 仓库：%PROJECT_DIR%
  exit /b 1
)
if not exist "%DJANGO_SUBPATH%\manage.py" (
  echo [ERROR] 缺少 manage.py：%PROJECT_DIR%\%DJANGO_SUBPATH%
  exit /b 1
)

echo [4/9] 升级：拉取最新代码...
git fetch origin
if errorlevel 1 (
  echo [ERROR] git fetch 失败。
  exit /b 1
)
git checkout %BRANCH%
if errorlevel 1 (
  echo [ERROR] 无法切换到分支 %BRANCH%。
  exit /b 1
)
git pull --ff-only origin %BRANCH%
if errorlevel 1 (
  echo [ERROR] git pull 失败（可能有本地改动或分叉提交）。
  echo 请先处理后再重试：git status
  exit /b 1
)

cd /d "%DJANGO_DIR%"

echo [5/9] 升级：检查/创建虚拟环境...
if not exist "%VENV_NAME%\Scripts\python.exe" (
  echo 未检测到 %VENV_NAME%，正在创建...
  %PY_CMD% -m venv %VENV_NAME%
  if errorlevel 1 (
    echo [ERROR] 创建虚拟环境失败。
    exit /b 1
  )
)
call "%VENV_NAME%\Scripts\activate.bat"
if errorlevel 1 (
  echo [ERROR] 激活虚拟环境失败。
  exit /b 1
)

echo [6/9] 升级：更新依赖...
python -m pip install --upgrade pip
if errorlevel 1 (
  echo [ERROR] 升级 pip 失败。
  exit /b 1
)
pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] 安装 requirements 失败。
  exit /b 1
)

echo [7/9] 升级：严格检查 .env 与 db.sqlite3...
if not exist ".env" (
  if exist ".env.example" (
    echo [HINT] 未找到 .env，从 .env.example 复制...
    copy /y ".env.example" ".env" >nul
  )
)
if not exist ".env" (
  echo [ERROR] 缺少 .env，已停止升级。
  echo 请在 %DJANGO_DIR% 下创建 .env，或复制 .env.example 为 .env。
  exit /b 1
)
if not exist "db.sqlite3" (
  echo [ERROR] 缺少 db.sqlite3，已停止升级。
  exit /b 1
)

echo [8/9] 升级：执行数据库迁移...
python manage.py migrate --noinput
if errorlevel 1 (
  echo [ERROR] migrate 执行失败。
  exit /b 1
)

echo [9/9] 升级：收集静态资源...
python manage.py collectstatic --noinput
if errorlevel 1 (
  echo [ERROR] collectstatic 执行失败。
  exit /b 1
)

echo.
echo ======================================
echo 部署升级完成。
echo 已同步最新代码并完成 Django 更新步骤。
echo Django 目录：%DJANGO_DIR%
echo 启动服务：仓库根目录 run_local.bat 或本目录 start_server.bat
echo ======================================
exit /b 0
