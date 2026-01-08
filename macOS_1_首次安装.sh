#!/bin/bash

# ==================== macOS 首次安装脚本 ====================
# 适用于 Apple Silicon Mac
# 对应 Windows 的「步骤1-首次安装.bat」
# 使用 Miniconda/Miniforge 管理 Python 环境
# =====================================================================

set -e

# 使用脚本所在目录作为工作目录
cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"

# 配置
# 配置
CONDA_ENV_NAME="manga-env"
MINICONDA_DIR="$SCRIPT_DIR/Miniforge3" # 使用 Miniforge3 目录
# 使用 Miniforge (默认使用 conda-forge，解决 Terms of Service 问题)
MINICONDA_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-arm64.sh"
PYTHON_VERSION="3.12"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=============================================="
echo "  Manga Translator UI - 首次安装"
echo "=============================================="
echo ""

# 检查是否为 Apple Silicon
check_apple_silicon() {
    if [[ $(uname -m) != "arm64" ]]; then
        echo -e "${YELLOW}[警告] 此脚本专为 Apple Silicon 设计${NC}"
        echo "   检测到架构: $(uname -m)"
        # 使用 Intel 版本的 Miniforge
        MINICONDA_URL="https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-x86_64.sh"
        read -p "是否继续? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        echo -e "${GREEN}[OK] 检测到 Apple Silicon (arm64)${NC}"
    fi
}

# 检查 Xcode 命令行工具
check_xcode_tools() {
    echo ""
    echo -e "${BLUE}[*] 检查 Xcode 命令行工具...${NC}"
    
    if xcode-select -p &> /dev/null; then
        echo -e "${GREEN}[OK] Xcode 命令行工具已安装${NC}"
    else
        echo -e "${YELLOW}[警告] 需要安装 Xcode 命令行工具${NC}"
        read -p "是否现在安装? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            xcode-select --install
            echo "请等待安装完成后重新运行此脚本"
            exit 0
        fi
    fi
}

# 安装或检测 Miniforge
setup_miniconda() {
    echo ""
    echo -e "${BLUE}[*] 检查 Conda 环境...${NC}"
    
    # 检查本地 Miniconda/Miniforge
    if [ -f "$MINICONDA_DIR/bin/conda" ]; then
        echo -e "${GREEN}[OK] 检测到本地 Conda: $MINICONDA_DIR${NC}"
        # 尝试接受 TOS (如果存在)
        "$MINICONDA_DIR/bin/conda" config --set channel_priority flexible 2>/dev/null || true
        return 0
    fi
    
    # 检查系统 Conda
    if command -v conda &> /dev/null; then
        SYSTEM_CONDA=$(which conda)
        echo -e "${GREEN}[OK] 检测到系统 Conda: $SYSTEM_CONDA${NC}"
        # 使用系统 Conda
        MINICONDA_DIR="$(dirname "$(dirname "$SYSTEM_CONDA")")"
        return 0
    fi
    
    # 需要安装 Miniforge
    echo -e "${YELLOW}[*] 未检测到 Conda，开始下载 Miniforge...${NC}"
    echo -e "${YELLOW}    Miniforge 是社区维护的 Conda 发行版${NC}"
    
    INSTALLER_PATH="$SCRIPT_DIR/miniforge_installer.sh"
    
    # 下载
    echo -e "${BLUE}[*] 下载 Miniforge...${NC}"
    curl -fL -o "$INSTALLER_PATH" "$MINICONDA_URL" || {
        echo -e "${RED}[错误] 下载 Miniforge 失败${NC}"
        exit 1
    }
    
    # 安装
    echo -e "${BLUE}[*] 安装 Miniforge 到 $MINICONDA_DIR...${NC}"
    bash "$INSTALLER_PATH" -b -p "$MINICONDA_DIR"
    
    # 清理安装包
    rm -f "$INSTALLER_PATH"
    
    echo -e "${GREEN}[OK] Miniforge 安装完成${NC}"
}

# 初始化 Conda
init_conda() {
    echo ""
    echo -e "${BLUE}[*] 初始化 Conda...${NC}"
    
    # 设置 PATH
    export PATH="$MINICONDA_DIR/bin:$PATH"
    
    # 初始化 Conda Shell
    eval "$("$MINICONDA_DIR/bin/conda" shell.bash hook)"
    
    # 配置使用 conda-forge (如果是刚安装的，Miniforge默认就是这个)
    conda config --add channels conda-forge 2>/dev/null || true
    conda config --set channel_priority flexible 2>/dev/null || true
    
    echo -e "${GREEN}[OK] Conda 已初始化${NC}"
}

# 创建或激活环境
setup_environment() {
    echo ""
    echo -e "${BLUE}[*] 设置 Conda 环境...${NC}"
    
    # 检查环境是否存在
    if conda env list | grep -qE "^${CONDA_ENV_NAME}[[:space:]]"; then
        echo -e "${GREEN}[OK] 检测到已有环境: $CONDA_ENV_NAME${NC}"
        read -p "是否删除并重新创建? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            conda env remove -n "$CONDA_ENV_NAME" -y
            conda create -n "$CONDA_ENV_NAME" python=$PYTHON_VERSION -y
            echo -e "${GREEN}[OK] 环境已重新创建${NC}"
        fi
    else
        echo -e "${BLUE}[*] 创建新环境: $CONDA_ENV_NAME (Python $PYTHON_VERSION)${NC}"
        conda create -n "$CONDA_ENV_NAME" python=$PYTHON_VERSION -y
        echo -e "${GREEN}[OK] 环境创建完成${NC}"
    fi
    
    # 激活环境
    conda activate "$CONDA_ENV_NAME"
    echo -e "${GREEN}[OK] 已激活环境: $CONDA_ENV_NAME${NC}"
}

# 安装依赖
install_dependencies() {
    echo ""
    echo -e "${BLUE}[*] 安装依赖...${NC}"
    
    # 检查 requirements_metal.txt 是否存在
    if [ ! -f "requirements_metal.txt" ]; then
        echo -e "${RED}[错误] 未找到 requirements_metal.txt${NC}"
        exit 1
    fi
    
    # 安装 PyTorch (MPS 版本)
    echo ""
    echo -e "${BLUE}[*] 安装 PyTorch (MPS 版本)...${NC}"
    pip install torch torchvision torchaudio
    
    # 安装其他依赖
    echo ""
    echo -e "${BLUE}[*] 安装其他依赖...${NC}"
    pip install -r requirements_metal.txt --ignore-installed torch torchvision torchaudio
    
    # 编译安装 pydensecrf
    echo ""
    echo -e "${BLUE}[*] 编译安装 pydensecrf...${NC}"
    if pip install git+https://github.com/lucasb-eyer/pydensecrf.git; then
        echo -e "${GREEN}[OK] pydensecrf 安装成功${NC}"
    else
        echo -e "${YELLOW}[警告] pydensecrf 安装失败，部分功能可能不可用${NC}"
    fi
}

# 验证安装
verify_installation() {
    echo ""
    echo -e "${BLUE}[*] 验证安装...${NC}"
    
    python -c "
import sys
print(f'Python: {sys.version}')
print()

import torch
print(f'PyTorch: {torch.__version__}')
print(f'MPS Available: {torch.backends.mps.is_available()}')
print(f'MPS Built: {torch.backends.mps.is_built()}')
print()

if torch.backends.mps.is_available():
    device = torch.device('mps')
    x = torch.randn(2, 3, device=device)
    y = torch.randn(3, 4, device=device)
    z = torch.mm(x, y)
    print('[OK] MPS 矩阵运算测试通过')
else:
    print('[警告] MPS 不可用，将使用 CPU')
print()

try:
    from manga_translator import MangaTranslator
    print('[OK] manga_translator 模块导入成功')
except Exception as e:
    print(f'[警告] manga_translator 模块导入失败: {e}')
"
}

# 主流程
main() {
    check_apple_silicon
    check_xcode_tools
    setup_miniconda
    init_conda
    setup_environment
    install_dependencies
    verify_installation
    
    echo ""
    echo "=============================================="
    echo -e "${GREEN}[OK] 安装完成!${NC}"
    echo "=============================================="
    echo ""
    echo "使用方法:"
    echo ""
    echo "  直接运行启动脚本:"
    echo "    ./macOS_2_启动Qt界面.sh"
    echo ""
    echo "  或手动激活环境后运行:"
    echo "    source $MINICONDA_DIR/bin/activate $CONDA_ENV_NAME"
    echo "    python desktop_qt_ui/main.py"
    echo ""
}

# 运行
main
