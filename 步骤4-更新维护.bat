@echo off
chcp 936 >nul
setlocal EnableDelayedExpansion

REM 设置 PYTHONUTF8=1 避免conda编码错误
set "PYTHONUTF8=1"

echo.
echo ========================================
echo 漫画翻译器 - 更新维护工具
echo Manga Translator UI - Update Tool
echo ========================================
echo.

REM 修复管理员模式下%CD%变成system32的问题
REM 使用脚本所在目录作为工作目录
cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

REM 检查conda环境（兼容命名环境和路径环境）
set CONDA_ENV_NAME=manga-env
set CONDA_ENV_PATH=%SCRIPT_DIR%\conda_env
set MINICONDA_ROOT=%SCRIPT_DIR%\Miniconda3

REM 检测路径是否包含非ASCII字符（中文等）
REM 使用PowerShell进行更可靠的检测
set "TEMP_CHECK_PATH=%SCRIPT_DIR%"
powershell -Command "$path = '%TEMP_CHECK_PATH%'; if ($path -match '[^\x00-\x7F]') { exit 1 } else { exit 0 }" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    REM 路径包含中文，使用磁盘根目录的Miniconda
    set MINICONDA_ROOT=%~d0\Miniconda3
)

where conda >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] 未检测到 Conda
    echo 请先运行 步骤1-首次安装.bat 安装 Miniconda
    pause
    exit /b 1
)

if not exist "%CONDA_ENV_PATH%\python.exe" (
    echo [ERROR] Conda环境不存在
    echo 请先运行 步骤1-首次安装.bat 创建环境
    pause
    exit /b 1
)

REM 激活conda环境
REM 使用MINICONDA_ROOT变量，支持中文路径
if exist "%MINICONDA_ROOT%\Scripts\activate.bat" (
    echo 正在激活环境...
    call "%MINICONDA_ROOT%\Scripts\activate.bat" "%CONDA_ENV_PATH%" 2>nul
    if %ERRORLEVEL% neq 0 (
        REM 尝试使用conda activate作为备用
        call conda activate "%CONDA_ENV_PATH%" 2>nul
    )
) else (
    REM 如果没有本地Miniconda，使用系统conda
    call conda activate "%CONDA_ENV_PATH%" 2>nul
)

if %ERRORLEVEL% neq 0 (
    echo [ERROR] 无法激活环境
    echo 环境路径: %CONDA_ENV_PATH%
    echo Miniconda路径: %MINICONDA_ROOT%
    echo 请检查Conda是否正确安装或重新运行 步骤1-首次安装.bat
    pause
    exit /b 1
)

REM 检查是否有便携版 Git
if exist "PortableGit\cmd\git.exe" (
    set "GIT=%SCRIPT_DIR%\PortableGit\cmd\git.exe"
    set "PATH=%SCRIPT_DIR%\PortableGit\cmd;%PATH%"
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

REM 检查版本信息 (在菜单显示前) - 使用Python脚本
:check_version
echo.
echo 正在检查版本...
echo ========================================

REM 使用Python脚本检查版本（避免批处理冒号问题）
python packaging\check_version.py

REM 获取版本信息供后续使用
for /f "tokens=1,2 delims==" %%a in ('python packaging\check_version.py --export-vars') do (
    if "%%a"=="CURRENT_VERSION" set CURRENT_VERSION=%%b
    if "%%a"=="REMOTE_VERSION" set REMOTE_VERSION=%%b
)

echo.
echo ========================================

REM 菜单
:menu
echo.
echo 请选择操作:
echo [1] 更新代码 (强制同步)
echo [2] 更新/安装依赖
echo [3] 完整更新 (代码+依赖)
echo [4] 重新检查版本
echo [5] 退出
echo.
set /p choice="请选择 (1/2/3/4/5): "

if "%choice%"=="1" goto update_code
if "%choice%"=="2" goto update_deps
if "%choice%"=="3" goto full_update
if "%choice%"=="4" (
    REM 重新检查版本,需要跳转到脚本开始的版本检查部分
    cls
    echo.
    echo ========================================
    echo 漫画翻译器 - 更新维护工具
    echo Manga Translator UI - Update Tool
    echo ========================================
    goto check_version
)
if "%choice%"=="5" goto end

echo 无效选项
goto menu

:update_code
echo.
echo ========================================
echo 更新代码 (强制同步)
echo ========================================
echo.

echo [警告] 将强制同步到远程分支,本地修改将被覆盖
set /p confirm="是否继续更新? (y/n): "
if /i not "!confirm!"=="y" (
    echo 取消更新
    goto menu
)

echo.
echo 正在强制同步到远程分支...
"%GIT%" reset --hard origin/main

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

REM 检测当前环境的 PyTorch 类型
echo 正在检测 PyTorch 版本类型...
python packaging\detect_torch_type.py >nul 2>&1
if %ERRORLEVEL% == 0 (
    REM 检测成功,获取对应的 requirements 文件
    for /f "delims=" %%i in ('python packaging\detect_torch_type.py --file-only') do set REQ_FILE=%%i
    echo 检测到 PyTorch 类型,使用: !REQ_FILE!
    echo.
    python packaging\launch.py --install-deps-only --requirements !REQ_FILE!
) else (
    REM 检测失败(未安装PyTorch),让 launch.py 自动选择
    echo 未检测到 PyTorch,将进行首次安装...
    echo.
    python packaging\launch.py --install-deps-only
)

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
"%GIT%" fetch origin

echo.
echo 正在强制同步到远程分支...
"%GIT%" reset --hard origin/main

if %ERRORLEVEL% neq 0 (
    echo [ERROR] 代码更新失败
    pause
    goto menu
)
echo [OK] 代码更新完成

echo.
echo [2/2] 更新依赖...

REM 检测当前环境的 PyTorch 类型
echo 正在检测 PyTorch 版本类型...
python packaging\detect_torch_type.py >nul 2>&1
if %ERRORLEVEL% == 0 (
    REM 检测成功,获取对应的 requirements 文件
    for /f "delims=" %%i in ('python packaging\detect_torch_type.py --file-only') do set REQ_FILE=%%i
    echo 检测到 PyTorch 类型,使用: !REQ_FILE!
    echo.
    python packaging\launch.py --install-deps-only --requirements !REQ_FILE!
) else (
    REM 检测失败(未安装PyTorch),让 launch.py 自动选择
    echo 未检测到 PyTorch,将进行首次安装...
    echo.
    python packaging\launch.py --install-deps-only
)

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
