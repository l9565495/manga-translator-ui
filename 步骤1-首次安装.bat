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

echo.
echo ========================================
echo 漫画翻译器 - 一键安装程序
echo Manga Translator UI - Installer
echo ========================================
echo.
echo 本脚本将自动完成以下步骤:
echo [1] 安装 Miniconda (Python环境管理, 如需要)
echo [2] 下载便携版 Git (如需要)
echo [3] 从 GitHub 克隆代码
echo [4] 创建Python环境并安装依赖
echo [5] 完成安装
echo.
pause

REM ===== 步骤1: 检查/安装Miniconda =====
echo.
echo [1/5] 检查 Miniconda (Python环境管理)...
echo ========================================

REM 检查是否已有本地Miniconda安装
set MINICONDA_ROOT=%SCRIPT_DIR%\Miniconda3
set CONDA_INSTALLED=0
set PATH_HAS_CHINESE=0
set ALT_INSTALL_PATH=

REM 检测路径是否包含非ASCII字符（中文等）
REM 使用PowerShell进行更可靠的检测
set "TEMP_CHECK_PATH=%SCRIPT_DIR%"
powershell -Command "$path = '%TEMP_CHECK_PATH%'; if ($path -match '[^\x00-\x7F]') { exit 1 } else { exit 0 }" >nul 2>&1
if errorlevel 1 (
    REM 路径包含中文，使用磁盘根目录
    set MINICONDA_ROOT=%~d0\Miniconda3
    set PATH_HAS_CHINESE=1
)

REM 先检查系统是否已有conda（全局安装）
where conda >nul 2>&1
if %ERRORLEVEL% neq 0 goto :check_local_conda

:found_system_conda
echo [OK] 检测到系统已安装 Conda
echo.
echo [DEBUG] ========== 开始检测Conda路径 ==========

REM 方法1: 从CONDA_EXE环境变量获取（最可靠）
if defined CONDA_EXE (
    echo [DEBUG] 方法1: 从CONDA_EXE环境变量获取...
    echo [DEBUG] CONDA_EXE = %CONDA_EXE%
    REM CONDA_EXE通常指向 D:\Miniconda3\Scripts\conda.exe
    REM 需要向上两级获取根目录
    for %%p in ("%CONDA_EXE%\..\..") do set "MINICONDA_ROOT=%%~fp"
    echo [DEBUG] 从CONDA_EXE解析出: !MINICONDA_ROOT!
)

REM 方法2: 从CONDA_PREFIX环境变量获取
if "!MINICONDA_ROOT!"=="" (
    if defined CONDA_PREFIX (
        echo [DEBUG] 方法2: 从CONDA_PREFIX环境变量获取...
        echo [DEBUG] CONDA_PREFIX = %CONDA_PREFIX%
        set "MINICONDA_ROOT=%CONDA_PREFIX%"
        echo [DEBUG] 使用CONDA_PREFIX: !MINICONDA_ROOT!
    )
)

REM 方法3: 使用 conda info --base（可能失败）
if "!MINICONDA_ROOT!"=="" (
    echo [DEBUG] 方法3: 尝试 conda info --base...
    for /f "delims=" %%i in ('conda info --base 2^>nul') do (
        REM 检查返回值是否是有效路径
        set "TEMP_PATH=%%i"
        if exist "!TEMP_PATH!\Scripts\conda.exe" (
            set "MINICONDA_ROOT=%%i"
            echo [DEBUG] conda info --base 返回有效路径: !MINICONDA_ROOT!
        ) else (
            echo [DEBUG] conda info --base 返回无效内容: %%i
        )
    )
)

REM 方法4: 从 where conda 解析路径
if "!MINICONDA_ROOT!"=="" (
    echo [DEBUG] 方法4: 尝试从 where conda 解析路径...
    for /f "delims=" %%i in ('where conda 2^>nul') do (
        echo [DEBUG] 找到conda: %%i
        REM 只取第一个找到的conda.exe（Scripts目录下的）
        if "!MINICONDA_ROOT!"=="" (
            if "%%~xi"==".exe" (
                for %%p in ("%%~dpi..") do set "MINICONDA_ROOT=%%~fp"
                echo [DEBUG] 解析出的路径: !MINICONDA_ROOT!
            ) else if "%%~xi"==".bat" (
                REM 如果是.bat文件，向上两级
                for %%p in ("%%~dpi..\..") do set "MINICONDA_ROOT=%%~fp"
                echo [DEBUG] 从bat解析出的路径: !MINICONDA_ROOT!
            )
        )
    )
)

REM 显示conda信息（添加错误处理避免闪退）
echo [DEBUG] ========== 最终检测结果 ==========
if not "!MINICONDA_ROOT!"=="" (
    echo [DEBUG] MINICONDA_ROOT = !MINICONDA_ROOT!
    echo 位置: !MINICONDA_ROOT!
    echo [DEBUG] 尝试获取conda版本...
    call conda --version 2>nul
    if !ERRORLEVEL! neq 0 (
        echo [WARNING] 无法获取conda版本信息 (错误码: !ERRORLEVEL!)
    ) else (
        echo [DEBUG] conda版本获取成功
    )
) else (
    echo [WARNING] 无法确定conda安装路径
    echo [DEBUG] 尝试使用系统conda（不设置MINICONDA_ROOT）
    echo [DEBUG] 后续将使用系统conda命令
)

echo [DEBUG] ========== Conda路径检测完成 ==========
echo [DEBUG] 即将跳转到 :check_git
echo.
pause

goto :check_git

:check_local_conda
REM 检查本地Miniconda
if exist "%MINICONDA_ROOT%\Scripts\conda.exe" goto :found_local_conda
goto :install_conda

:found_local_conda
echo [OK] 检测到本地 Miniconda 已安装
echo 位置: %MINICONDA_ROOT%
call "%MINICONDA_ROOT%\Scripts\conda.exe" --version
goto :check_git

:install_conda

REM 提示：需要安装本地Miniconda
echo [INFO] 未检测到本地 Miniconda
echo ========================================
echo.
echo 本项目需要 Python 3.12 环境
echo.

REM 如果路径包含中文，给出说明并使用备用路径
if !PATH_HAS_CHINESE!==1 goto :__PATH_WARNING
goto :__PATH_WARNING_END

:__PATH_WARNING
echo ========================================
echo [警告] 检测到路径包含非英文字符
echo ========================================
echo 当前路径: %SCRIPT_DIR%
echo.
echo Miniconda 对非英文路径的兼容性有限
echo 将自动使用备用安装路径: !MINICONDA_ROOT!
echo (同一磁盘，不同位置)
echo.
echo 建议: 为避免其他潜在问题，可以将项目移动到纯英文路径
echo       例如: D:\manga-translator\
echo.
pause
echo.
goto :__PATH_WARNING_END

:__PATH_WARNING_END
echo.

echo 将安装 Miniconda 到: %MINICONDA_ROOT%
echo.
        echo Miniconda 特点:
        echo   - 体积小 (约50MB)
        echo   - 可管理多个Python版本
        echo   - 环境隔离,互不干扰
        echo   - 自带pip包管理
        echo.
echo 是否安装 Miniconda?
echo [1] 是 (推荐) - 自动下载安装
echo [2] 否 - 手动安装后重新运行脚本
echo [3] 取消安装
echo.
set /p install_conda="请选择 (1/2/3, 默认1): "

if "%install_conda%"=="2" (
    echo.
    echo 请访问以下网址下载安装 Miniconda:
    echo   官方: https://docs.conda.io/en/latest/miniconda.html
    echo   国内: https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/
    echo.
    echo 安装时请勾选 "Add to PATH" 选项
    echo 安装完成后重新运行本脚本
    pause
    exit /b 1
)

if "%install_conda%"=="3" (
    echo 安装已取消
    pause
    exit /b 1
)

REM 下载并安装Miniconda
echo.
echo 正在下载 Miniconda...
echo.

REM Miniconda下载链接（Python 3.12版本）
set MINICONDA_OFFICIAL=https://repo.anaconda.com/miniconda/Miniconda3-py312_25.9.1-1-Windows-x86_64.exe
set MINICONDA_TUNA=https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-py312_25.9.1-1-Windows-x86_64.exe

echo 请选择下载源:
echo [1] 清华大学镜像 (国内推荐, 更快)
echo [2] Anaconda 官方
echo.
set /p conda_source="请选择 (1/2, 默认1): "

if "%conda_source%"=="2" (
    set MINICONDA_URL=%MINICONDA_OFFICIAL%
    echo 使用: Anaconda 官方源
) else (
    set MINICONDA_URL=%MINICONDA_TUNA%
    echo 使用: 清华大学镜像
)

echo.
echo 下载中... (约50MB, 可能需要几分钟)
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Write-Host '正在下载 Miniconda...'; try { Invoke-WebRequest -Uri '%MINICONDA_URL%' -OutFile 'Miniconda3-latest.exe' -UseBasicParsing; Write-Host '[OK] 下载完成'; exit 0 } catch { Write-Host '[ERROR] 下载失败: $_'; exit 1 }}"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] 下载失败,请检查网络连接
    echo.
    echo 你可以:
    echo 1. 手动下载: %MINICONDA_URL%
    echo 2. 保存为: Miniconda3-latest.exe
    echo 3. 放到当前目录后重新运行脚本
    pause
    exit /b 1
)

echo.
echo 正在安装 Miniconda...
echo.
echo 安装选项:
echo   - 安装位置: %MINICONDA_ROOT%
echo   - Python版本: 3.12
echo   - 仅为当前项目使用
echo.
echo 正在静默安装...
timeout /t 2 >nul

        REM 静默安装Miniconda
        start /wait Miniconda3-latest.exe /InstallationType=JustMe /AddToPath=1 /RegisterPython=0 /S /D=%MINICONDA_ROOT%

        if %ERRORLEVEL% neq 0 (
            echo.
            echo [ERROR] Miniconda 安装失败
            echo.
            pause
            exit /b 1
        )

        echo.
        echo [OK] Miniconda 安装完成
        echo.

        REM 清理安装包
        if exist "Miniconda3-latest.exe" (
            echo 正在清理安装包...
            del /f /q "Miniconda3-latest.exe" >nul 2>&1
            if %ERRORLEVEL% == 0 (
                echo [OK] 安装包已清理
            )
        )
        echo.

        REM 初始化conda环境
        echo 正在初始化 conda 环境...
        call "%MINICONDA_ROOT%\Scripts\activate.bat"
        call conda init cmd.exe >nul 2>&1

        echo.
        echo [OK] Miniconda 已安装并配置完成
        echo 安装位置: %MINICONDA_ROOT%
        echo.
        echo 请关闭当前命令窗口,重新运行此脚本
        echo (需要重新加载环境变量)
        pause
        exit /b 0

REM ===== 步骤2: 检查/下载Git =====
:check_git
echo.
echo [2/5] 检查 Git...
echo ========================================
echo [DEBUG] 开始检查Git...
echo [DEBUG] 当前MINICONDA_ROOT = !MINICONDA_ROOT!

git --version >nul 2>&1
if %ERRORLEVEL% == 0 (
    set GIT=git
    echo [OK] 找到系统Git
    echo [DEBUG] 跳转到 :clone_repo
    goto :clone_repo
)

echo [INFO] 未找到 Git
echo [DEBUG] 准备提示用户下载Git...
echo.
echo Git是代码拉取必需的,请选择:
echo [1] 下载便携版 Git (推荐, 约50MB)
echo [2] 退出,手动安装 Git
echo.
set /p git_choice="请选择 (1/2): "

if "%git_choice%"=="2" (
    echo.
    echo 下载地址: https://git-scm.com/downloads
    pause
    exit /b 0
)

if not "%git_choice%"=="1" (
    echo 无效选项
    goto :check_git
)

REM 下载Git
echo.
echo 正在下载 Git 便携版...
echo.
echo 请选择下载源:
echo [1] GitHub 官方
echo [2] gh-proxy.com 镜像 (国内推荐)
echo.
set /p git_source="请选择 (1/2, 默认2): "

set GIT_VERSION=2.43.0
set GIT_ARCH=64-bit

if "%git_source%"=="1" (
    set GIT_URL=https://github.com/git-for-windows/git/releases/download/v%GIT_VERSION%.windows.1/PortableGit-%GIT_VERSION%-%GIT_ARCH%.7z.exe
    echo 使用: GitHub 官方源
) else (
    set GIT_URL=https://gh-proxy.com/https://github.com/git-for-windows/git/releases/download/v%GIT_VERSION%.windows.1/PortableGit-%GIT_VERSION%-%GIT_ARCH%.7z.exe
    echo 使用: gh-proxy.com 镜像
)

echo.
echo 下载中... (约50MB, 可能需要几分钟)
if not exist "tmp" mkdir tmp
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $ProgressPreference = 'SilentlyContinue'; Write-Host '正在下载...'; try { Invoke-WebRequest -Uri '%GIT_URL%' -OutFile 'tmp\PortableGit.7z.exe' -UseBasicParsing; Write-Host '[OK] 下载完成'; exit 0 } catch { Write-Host '[ERROR] 下载失败: $_'; exit 1 }}"

if %ERRORLEVEL% neq 0 (
    echo.
    echo 下载失败,请检查网络连接后重试
    pause
    exit /b 1
)

echo.
echo 正在解压 Git...
tmp\PortableGit.7z.exe -o"PortableGit" -y >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo 解压失败
    pause
    exit /b 1
)

del tmp\PortableGit.7z.exe >nul 2>&1
set GIT=PortableGit\cmd\git.exe
set "PATH=%CD%\PortableGit\cmd;%PATH%"
echo [OK] Git 安装完成
PortableGit\cmd\git.exe --version

REM ===== 步骤3: 克隆/更新仓库 =====
:clone_repo
echo.
echo [3/5] 检查代码仓库...
echo ========================================
echo [DEBUG] 进入 :clone_repo 部分
echo [DEBUG] 当前目录: %SCRIPT_DIR%
echo [DEBUG] 当前GIT变量: %GIT%
echo.

REM 检查是否从压缩包解压（有代码但没有.git）
if not exist ".git" (
    if exist "manga_translator" if exist "desktop_qt_ui" if exist "packaging\VERSION" (
        echo [INFO] 检测到从压缩包解压的代码文件
        echo.
        echo 请选择:
        echo [1] 跳过Git配置,直接安装依赖（无法使用步骤4更新）
        echo [2] 初始化Git仓库并关联远程（可使用步骤4更新）
        echo [3] 退出
        echo.
        set /p zip_choice="请选择 (1/2/3, 默认2): "
        
        if "!zip_choice!"=="3" (
            exit /b 0
        ) else if "!zip_choice!"=="1" (
            echo [OK] 跳过Git配置,直接使用现有代码
            echo.
            goto :create_venv
        ) else (
            echo [INFO] 正在初始化Git仓库...
            git init
            if !ERRORLEVEL! neq 0 (
                echo [ERROR] Git初始化失败
                pause
                exit /b 1
            )
            REM 获取目标仓库地址
            call :get_repo_url
            echo.
            echo 正在添加远程仓库...
            git remote add origin !REPO_URL!
            if !ERRORLEVEL! neq 0 (
                echo [ERROR] 添加远程仓库失败
                pause
                exit /b 1
            )
            echo.
            echo 正在获取远程分支...
            git fetch origin
            if !ERRORLEVEL! neq 0 (
                echo [WARNING] 获取远程分支失败，可能是网络问题
                echo [INFO] 将跳过Git配置，直接使用现有代码
                echo.
                goto :create_venv
            )
            echo.
            echo [OK] Git仓库初始化完成
            echo [INFO] 可以使用步骤4进行更新
            echo.
            goto :create_venv
        )
    )
)

REM 先获取目标仓库地址
call :get_repo_url

REM 检查是否已存在代码仓库
if exist ".git" (
    echo [INFO] 检测到现有Git仓库
    
    REM 获取当前仓库地址
    for /f "delims=" %%i in ('"%GIT%" config --get remote.origin.url 2^>nul') do set CURRENT_REPO=%%i
    
    if defined CURRENT_REPO (
        echo 当前仓库: !CURRENT_REPO!
        echo 目标仓库: !REPO_URL!
        echo.
        
        REM 标准化仓库地址进行比较（去除.git后缀和所有镜像前缀）
        set CURRENT_CLEAN=!CURRENT_REPO:.git=!
        set TARGET_CLEAN=!REPO_URL:.git=!
        
        REM 移除常见镜像前缀，统一标准化为 github.com 地址
        set CURRENT_CLEAN=!CURRENT_CLEAN:https://gh-proxy.com/https://github.com/=https://github.com/!
        set CURRENT_CLEAN=!CURRENT_CLEAN:https://ghproxy.com/https://github.com/=https://github.com/!
        set CURRENT_CLEAN=!CURRENT_CLEAN:https://mirror.ghproxy.com/https://github.com/=https://github.com/!
        set CURRENT_CLEAN=!CURRENT_CLEAN:https://ghfast.top/https://github.com/=https://github.com/!
        set CURRENT_CLEAN=!CURRENT_CLEAN:https://gitproxy.click/https://github.com/=https://github.com/!
        
        set TARGET_CLEAN=!TARGET_CLEAN:https://gh-proxy.com/https://github.com/=https://github.com/!
        set TARGET_CLEAN=!TARGET_CLEAN:https://ghproxy.com/https://github.com/=https://github.com/!
        set TARGET_CLEAN=!TARGET_CLEAN:https://mirror.ghproxy.com/https://github.com/=https://github.com/!
        set TARGET_CLEAN=!TARGET_CLEAN:https://ghfast.top/https://github.com/=https://github.com/!
        set TARGET_CLEAN=!TARGET_CLEAN:https://gitproxy.click/https://github.com/=https://github.com/!
        
        if "!CURRENT_CLEAN!"=="!TARGET_CLEAN!" (
            echo [OK] 仓库地址匹配,正在强制同步到最新版本...
            echo.
            
            echo 获取远程更新...
            "%GIT%" fetch origin
            if !ERRORLEVEL! neq 0 (
                echo [WARNING] 获取更新失败,可能是网络问题
            ) else (
                echo 强制同步到远程主分支...
                "%GIT%" reset --hard origin/main
                if !ERRORLEVEL! == 0 (
                    echo [OK] 代码已更新到最新版本
                    echo.
                    goto :create_venv
                ) else (
                    echo [WARNING] 同步失败,尝试使用 main 分支...
                    "%GIT%" checkout -f main
                    "%GIT%" reset --hard origin/main
                    if !ERRORLEVEL! == 0 (
                        echo [OK] 代码已更新到最新版本
                        echo.
                        goto :create_venv
                    )
                )
            )
            
            echo [WARNING] 自动更新失败,将删除并重新克隆
            echo.
        ) else (
            echo [警告] 仓库地址不匹配
            echo.
            echo 请选择:
            echo [1] 删除现有仓库并克隆新仓库
            echo [2] 保留现有仓库,跳过克隆
            echo [3] 退出安装
            echo.
            set /p mismatch_choice="请选择 (1/2/3): "
            
            if "!mismatch_choice!"=="2" (
                echo [INFO] 保留现有仓库
                goto :create_venv
            ) else if "!mismatch_choice!"=="3" (
                exit /b 0
            )
            
            echo 正在删除现有仓库...
        )
    ) else (
        echo [WARNING] 无法读取仓库信息,将重新克隆
    )
    
    REM 删除现有文件和目录(保留venv、PortableGit、Python-3.12.12、Portable7z)
    echo 正在清理旧文件...
    
    REM 删除目录(保留venv、PortableGit、Python-3.12.12、Portable7z)
    for /d %%d in (*) do (
        if /i not "%%d"=="venv" if /i not "%%d"=="PortableGit" if /i not "%%d"=="Python-3.12.12" if /i not "%%d"=="Portable7z" (
            echo 删除目录: %%d
            rmdir /s /q "%%d" 2>nul
        )
    )
    
    REM 删除文件(保留当前运行的脚本)
    for %%f in (*) do (
        if /i not "%%~nxf"=="步骤1-首次安装.bat" (
            echo 删除文件: %%~nxf
            del /f /q "%%f" 2>nul
        )
    )
    
    REM 删除隐藏的.git目录
    if exist ".git" (
        echo 删除 .git 目录...
        rmdir /s /q ".git" 2>nul
        if exist ".git" (
            echo [ERROR] 无法删除 .git 目录,可能被占用
            echo 请关闭所有相关程序后重试
            pause
            exit /b 1
        )
    )
    
    echo [OK] 已清理旧数据
    echo.
)

echo 仓库地址: !REPO_URL!
echo 安装目录: %SCRIPT_DIR%
echo.
goto :do_clone

:get_repo_url
echo 请选择克隆源:
echo [1] GitHub 官方 (国外推荐)
echo [2] gh-proxy.com 镜像 (国内推荐)
echo [3] 手动输入仓库地址
echo.
set /p repo_choice="请选择 (1/2/3, 默认2): "

if "%repo_choice%"=="1" (
    set REPO_URL=https://github.com/hgmzhn/manga-translator-ui.git
    echo 使用: GitHub官方
) else if "%repo_choice%"=="3" (
    set /p REPO_URL="请输入仓库地址: "
    echo 使用: 自定义地址
) else (
    set REPO_URL=https://gh-proxy.com/https://github.com/hgmzhn/manga-translator-ui.git
    echo 使用: gh-proxy.com镜像
)
echo.
goto :eof

:do_clone

REM 使用临时目录克隆
set TEMP_DIR=manga_translator_temp_%RANDOM%
echo 正在克隆代码到临时目录... (可能需要几分钟)
echo.
"%GIT%" clone !REPO_URL! %TEMP_DIR%

echo.
echo [DEBUG] 检查克隆结果...
echo [DEBUG] 临时目录: %TEMP_DIR%
echo [DEBUG] 完整路径: %SCRIPT_DIR%\%TEMP_DIR%
if exist "%TEMP_DIR%" (
    echo [DEBUG] 临时目录存在
    if exist "%TEMP_DIR%\.git" (
        echo [DEBUG] .git 目录存在 - 克隆成功!
        goto :copy_files
    ) else (
        echo [DEBUG] .git 目录不存在 - 克隆失败!
    )
) else (
    echo [DEBUG] 临时目录不存在 - 克隆失败!
)

REM 如果到这里说明克隆失败
echo.
echo [ERROR] 克隆失败
echo.
echo 可能原因:
echo 1. 网络连接问题
echo 2. 仓库地址错误
echo 3. GitHub访问受限 (请选择GHProxy镜像重试)
echo.
if exist "%TEMP_DIR%" rmdir /s /q "%TEMP_DIR%"
set /p retry="是否重试? (y/n): "
if /i "!retry!"=="y" goto :clone_repo
pause
exit /b 1

:copy_files

echo.
echo [DEBUG] 开始复制文件...
echo [DEBUG] 临时目录: %TEMP_DIR%
echo [DEBUG] 当前目录: %SCRIPT_DIR%
echo.

echo 正在复制目录...
for /d %%i in ("%TEMP_DIR%\*") do (
    if /i not "%%~nxi"=="PortableGit" (
        echo [DEBUG] 复制目录: %%~nxi
        xcopy "%%i" "%SCRIPT_DIR%\%%~nxi\" /E /H /Y /I /Q
        if !ERRORLEVEL! neq 0 echo [ERROR] 复制目录失败: %%~nxi (错误码: !ERRORLEVEL!)
    )
)

echo.
echo 正在复制文件...
for %%i in ("%TEMP_DIR%\*") do (
    if /i not "%%~nxi"=="步骤1-首次安装.bat" (
        echo [DEBUG] 复制文件: %%~nxi
        copy /Y "%%i" "%SCRIPT_DIR%\"
        if !ERRORLEVEL! neq 0 echo [ERROR] 复制文件失败: %%~nxi (错误码: !ERRORLEVEL!)
    )
)

echo.
echo 正在复制隐藏文件...
if exist "%TEMP_DIR%\.git\" (
    echo [DEBUG] 复制 .git 目录...
    xcopy "%TEMP_DIR%\.git" ".git\" /E /H /Y /I /Q
    if !ERRORLEVEL! neq 0 echo [ERROR] 复制.git失败 (错误码: !ERRORLEVEL!)
) else (
    echo [DEBUG] .git 目录不存在
)

if exist "%TEMP_DIR%\.gitignore" (
    echo [DEBUG] 复制 .gitignore 文件...
    copy /Y "%TEMP_DIR%\.gitignore" .
    if !ERRORLEVEL! neq 0 echo [ERROR] 复制.gitignore失败 (错误码: !ERRORLEVEL!)
) else (
    echo [DEBUG] .gitignore 文件不存在
)

echo.
echo [DEBUG] 复制完成，准备清理临时目录...
echo 正在清理临时目录...
rmdir /s /q "%TEMP_DIR%"
if !ERRORLEVEL! neq 0 (
    echo [ERROR] 清理临时目录失败 (错误码: !ERRORLEVEL!)
) else (
    echo [DEBUG] 临时目录已清理
)

echo.
echo [OK] 代码克隆完成

:create_venv

REM ===== 步骤4: 创建Conda环境并安装依赖 =====
echo.
echo [4/5] 创建Python环境并安装依赖...
echo ========================================
echo [DEBUG] 进入 :create_venv 部分
echo [DEBUG] MINICONDA_ROOT = !MINICONDA_ROOT!
echo [DEBUG] SCRIPT_DIR = %SCRIPT_DIR%
echo.

REM 使用命名环境（避免中文路径问题）
set CONDA_ENV_NAME=manga-env
set CONDA_ENV_EXISTS=0

REM 检查环境是否存在 - 使用 conda info --envs 避免编码错误
call conda info --envs 2>nul | findstr /C:"%CONDA_ENV_NAME%" >nul 2>&1
if %ERRORLEVEL% == 0 (
    set CONDA_ENV_EXISTS=1
    echo [OK] 检测到现有conda环境: %CONDA_ENV_NAME%
) else (
    echo [INFO] 未检测到环境: %CONDA_ENV_NAME%
)

if %CONDA_ENV_EXISTS% == 1 (
    echo.
    echo 检测到现有Conda环境,是否重新创建?
    echo [1] 使用现有环境 (快速)
    echo [2] 重新创建环境 (全新安装)
    echo.
    set /p recreate_env="请选择 (1/2, 默认1): "
    
    if "!recreate_env!"=="2" (
        echo 正在删除现有环境...
        call conda deactivate >nul 2>&1
        call conda env remove -n "%CONDA_ENV_NAME%" -y >nul 2>&1
        set CONDA_ENV_EXISTS=0
        echo [OK] 环境已删除
    ) else (
        echo [OK] 使用现有环境
        echo [DEBUG] 跳过环境创建，直接激活
        goto :activate_env
    )
)

if %CONDA_ENV_EXISTS% == 0 (
    :create_env_directly
    echo.
    echo 正在创建Conda环境...
    echo 环境名称: %CONDA_ENV_NAME%
    echo Python版本: 3.12
    echo.
    
    REM 清理可能存在的旧环境注册信息
    echo 清理conda环境列表...
    call conda env remove -n "%CONDA_ENV_NAME%" -y >nul 2>&1
    
    REM 接受Conda服务条款（避免交互式提示）
    call conda config --set channel_priority flexible >nul 2>&1
    call conda tos accept >nul 2>&1
    
    REM 创建命名环境
    call conda create -n "%CONDA_ENV_NAME%" python=3.12 -y
    if !ERRORLEVEL! neq 0 (
        echo [ERROR] Conda环境创建失败
        pause
        exit /b 1
    )
    echo [OK] Conda环境创建完成
)

:activate_env
echo.
echo 正在激活环境...
echo [DEBUG] CONDA_ENV_NAME = %CONDA_ENV_NAME%
echo [DEBUG] MINICONDA_ROOT = !MINICONDA_ROOT!

REM 优先尝试激活命名环境
call conda activate "%CONDA_ENV_NAME%" 2>nul
if !ERRORLEVEL! == 0 (
    echo [OK] 已激活命名环境: %CONDA_ENV_NAME%
    goto :env_activated
)

REM 如果命名环境不存在，尝试激活路径环境（兼容旧版本）
set CONDA_ENV_PATH=%SCRIPT_DIR%\conda_env
if exist "%CONDA_ENV_PATH%\python.exe" (
    echo [DEBUG] 检测到旧版本路径环境，尝试激活...
    REM 使用直接PATH方式激活路径环境
    set "PATH=%CONDA_ENV_PATH%;%CONDA_ENV_PATH%\Library\mingw-w64\bin;%CONDA_ENV_PATH%\Library\usr\bin;%CONDA_ENV_PATH%\Library\bin;%CONDA_ENV_PATH%\Scripts;%CONDA_ENV_PATH%\bin;%PATH%"
    set "CONDA_PREFIX=%CONDA_ENV_PATH%"
    set "CONDA_DEFAULT_ENV=%CONDA_ENV_PATH%"
    
    REM 验证
    "%CONDA_ENV_PATH%\python.exe" --version >nul 2>&1
    if !ERRORLEVEL! == 0 (
        echo [OK] 已激活路径环境（旧版本）
        goto :env_activated
    )
)

REM 两种环境都不存在或激活失败
echo [ERROR] 无法激活环境
echo.
echo 尝试了以下方式:
echo 1. 命名环境: %CONDA_ENV_NAME%
echo 2. 路径环境: %CONDA_ENV_PATH%
echo.
echo 请重新运行此脚本创建环境
pause
exit /b 1

:env_activated
echo [DEBUG] 环境激活成功

echo 正在升级 pip...
python -m pip install --upgrade pip >nul 2>&1

echo 正在安装基础依赖...
python -m pip install packaging setuptools wheel >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [WARNING] 基础依赖安装失败,继续尝试...
)

echo 正在检测 GPU 支持...
echo.

REM 调用项目的 launch.py 进行依赖安装
python packaging\launch.py --install-deps-only

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] 依赖安装失败
    echo.
    echo 你可以稍后手动运行:
    echo   步骤4-更新维护.bat
    echo.
    pause
    exit /b 1
)

echo.
echo [OK] 依赖安装完成

REM ===== 步骤5: 完成 =====
echo.
echo [5/5] 安装完成!
echo ========================================
echo.
echo [OK] 所有步骤已完成!
echo.
echo 安装位置: %SCRIPT_DIR%
echo.
echo 下一步操作:
echo   双击 步骤2-启动Qt界面.bat (Qt版本)
echo   或 步骤3-检查更新并启动.bat (自动检查更新)
echo.
echo 定期更新:
echo   双击 步骤4-更新维护.bat
echo.
pause

REM 询问是否清理pip缓存
echo.
echo ========================================
echo 磁盘空间优化
echo ========================================
echo.
echo pip 缓存文件可能占用较大空间
echo 清理缓存不会影响已安装的包
echo.
set /p clean_cache="是否清理 pip 缓存? (y/n, 默认n): "
if /i "%clean_cache%"=="y" (
    echo.
    echo 正在清理 pip 缓存...
    python -m pip cache purge >nul 2>&1
    if errorlevel 1 (
        echo [WARNING] 缓存清理失败，可能权限不足
    ) else (
        echo [OK] 缓存已清理
    )
) else (
    echo [INFO] 跳过缓存清理
)

REM 询问是否立即运行
echo.
set /p run_now="是否立即运行? (y/n): "
if /i "%run_now%"=="y" (
    echo.
    echo 正在启动...
    start 步骤2-启动Qt界面.bat
)

echo.
echo 安装流程已结束
pause
