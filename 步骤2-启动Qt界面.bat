@echo off
chcp 936 >nul
setlocal EnableDelayedExpansion

REM 设置 PYTHONUTF8=1 避免conda编码错误
set "PYTHONUTF8=1"

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

REM 尝试获取实际的Miniconda路径（处理system32情况）
for /f "delims=" %%i in ('conda info --base 2^>nul') do set "MINICONDA_ROOT=%%i"

REM 检查环境是否存在（优先命名环境）
call conda info --envs 2>nul | findstr /C:"%CONDA_ENV_NAME%" >nul 2>&1
if %ERRORLEVEL% == 0 (
    echo [INFO] 检测到命名环境: %CONDA_ENV_NAME%
    goto :env_check_ok
)

REM 检查旧版本路径环境
if exist "%CONDA_ENV_PATH%\python.exe" (
    echo [INFO] 检测到路径环境（旧版本）
    goto :env_check_ok
)

REM 没有任何环境
echo [ERROR] 未检测到Conda环境
echo 请先运行 步骤1-首次安装.bat 创建环境
pause
exit /b 1

:env_check_ok

REM 激活conda环境（兼容命名环境和路径环境）
REM 优先尝试命名环境
call conda activate "%CONDA_ENV_NAME%" 2>nul
if %ERRORLEVEL% == 0 (
    echo [INFO] 已激活命名环境: %CONDA_ENV_NAME%
    goto :activated_ok
)

REM 尝试路径环境（旧版本兼容）
if exist "%CONDA_ENV_PATH%\python.exe" (
    echo [INFO] 激活路径环境（旧版本）...
    set "PATH=%CONDA_ENV_PATH%;%CONDA_ENV_PATH%\Library\mingw-w64\bin;%CONDA_ENV_PATH%\Library\usr\bin;%CONDA_ENV_PATH%\Library\bin;%CONDA_ENV_PATH%\Scripts;%CONDA_ENV_PATH%\bin;%PATH%"
    set "CONDA_PREFIX=%CONDA_ENV_PATH%"
    set "CONDA_DEFAULT_ENV=%CONDA_ENV_PATH%"
    "%CONDA_ENV_PATH%\python.exe" --version >nul 2>&1
    if %ERRORLEVEL% == 0 (
        goto :activated_ok
    )
)

echo [ERROR] 无法激活环境
pause
exit /b 1

:activated_ok

REM 检查是否有便携版 Git
if exist "PortableGit\cmd\git.exe" (
    set "PATH=%SCRIPT_DIR%\PortableGit\cmd;%PATH%"
)

REM 切换到项目根目录(确保Python能正确找到模块)
cd /d "%~dp0"

REM 直接启动 Qt 界面
python desktop_qt_ui\main.py
pause
