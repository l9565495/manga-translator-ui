@echo off
chcp 936 >nul
setlocal EnableDelayedExpansion

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
    set "PATH=%CD%\PortableGit\cmd;%PATH%"
)

REM 切换到项目根目录(确保Python能正确找到模块)
cd /d "%~dp0"

REM 直接启动 Qt 界面
python "%CD%\desktop_qt_ui\main.py"
pause
