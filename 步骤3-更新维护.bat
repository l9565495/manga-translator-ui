@echo off
chcp 936 >nul
setlocal EnableDelayedExpansion

echo.
echo ========================================
echo 漫画翻译器 - 更新维护工具
echo Manga Translator UI - Update Tool
echo ========================================
echo.

REM 检测虚拟环境有效性
set VENV_VALID=0
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe -c "import sys; sys.exit(0)" >nul 2>&1
    if !ERRORLEVEL! == 0 (
        set VENV_VALID=1
    )
)

if !VENV_VALID! == 0 (
    echo [ERROR] 虚拟环境不存在或已损坏
    echo 请先运行 步骤1-首次安装.bat 创建虚拟环境
    pause
    exit /b 1
)

REM 激活虚拟环境
call venv\Scripts\activate.bat

REM 检查是否有便携版 Git
if exist "PortableGit\cmd\git.exe" (
    set "GIT=%CD%\PortableGit\cmd\git.exe"
    set "PATH=%CD%\PortableGit\cmd;%PATH%"
) else (
    git --version >nul 2>&1
    if %ERRORLEVEL% == 0 (
        set GIT=git
    ) else (
        echo [ERROR] 未找到 Git
        echo 请先安装 Git 或运行 步骤1-首次安装.bat
        pause
        exit /b 1
    )
)

REM 菜单
:menu
echo.
echo 请选择操作:
echo [1] 更新代码 (强制同步)
echo [2] 更新/安装依赖
echo [3] 完整更新 (代码+依赖)
echo [4] 退出
echo.
set /p choice="请选择 (1/2/3/4): "

if "%choice%"=="1" goto update_code
if "%choice%"=="2" goto update_deps
if "%choice%"=="3" goto full_update
if "%choice%"=="4" goto end

echo 无效选项
goto menu

:update_code
echo.
echo ========================================
echo 更新代码 (强制同步)
echo ========================================
echo.

echo [警告] 将强制同步到远程分支,本地修改将被覆盖
set /p confirm="是否继续? (y/n): "
if /i not "!confirm!"=="y" (
    echo 取消更新
    goto menu
)

echo.
echo 获取远程更新...
%GIT% fetch origin

echo.
echo 正在强制同步到远程分支...
%GIT% reset --hard origin/main

if %ERRORLEVEL% == 0 (
    echo [OK] 代码更新完成
) else (
    echo [ERROR] 代码更新失败
)
pause
goto menu

:update_deps
echo.
echo ========================================
echo 更新/安装依赖
echo ========================================
echo.

python launch.py --install-deps-only

if %ERRORLEVEL% == 0 (
    echo [OK] 依赖更新完成
) else (
    echo [ERROR] 依赖更新失败
)
pause
goto menu

:full_update
echo.
echo ========================================
echo 完整更新 (代码+依赖)
echo ========================================
echo.

echo [1/2] 更新代码 (强制同步)...
echo [警告] 将强制同步到远程分支,本地修改将被覆盖
set /p confirm="是否继续? (y/n): "
if /i not "!confirm!"=="y" (
    echo 取消更新
    goto menu
)

echo.
echo 获取远程更新...
%GIT% fetch origin

echo.
echo 正在强制同步到远程分支...
%GIT% reset --hard origin/main

if %ERRORLEVEL% neq 0 (
    echo [ERROR] 代码更新失败
    pause
    goto menu
)
echo [OK] 代码更新完成

echo.
echo [2/2] 更新依赖...
python launch.py --install-deps-only

if %ERRORLEVEL% == 0 (
    echo.
    echo [OK] 完整更新完成
) else (
    echo [ERROR] 依赖更新失败
)
pause
goto menu

:end
echo.
echo 退出更新工具
pause
