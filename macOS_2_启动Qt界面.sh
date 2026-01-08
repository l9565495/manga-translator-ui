#!/bin/bash

# ==================== macOS Qt 界面启动脚本 ====================
# 适用于 Apple Silicon Mac
# 对应 Windows 的「步骤2-启动Qt界面.bat」
# =====================================================================

# 使用脚本所在目录作为工作目录
cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"

# 配置
CONDA_ENV_NAME="manga-env"
MINICONDA_DIR="$SCRIPT_DIR/Miniforge3"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=============================================="
echo "  Manga Translator UI - Qt 界面启动"
echo "=============================================="
echo ""

# 查找并初始化 Conda
init_conda() {
    # 优先检查本地 Miniconda/Miniforge
    if [ -f "$MINICONDA_DIR/bin/conda" ]; then
        export PATH="$MINICONDA_DIR/bin:$PATH"
        eval "$("$MINICONDA_DIR/bin/conda" shell.bash hook)"
        return 0
    fi
    
    # 检查系统 Conda
    if command -v conda &> /dev/null; then
        eval "$(conda shell.bash hook)"
        return 0
    fi
    
    return 1
}

# 初始化 Conda
if ! init_conda; then
    echo -e "${RED}[错误] 未找到 Conda${NC}"
    echo "   请先运行 ./macOS_1_首次安装.sh 安装"
    exit 1
fi

# 激活环境
if ! conda activate "$CONDA_ENV_NAME" 2>/dev/null; then
    echo -e "${RED}[错误] 未找到环境: $CONDA_ENV_NAME${NC}"
    echo "   请先运行 ./macOS_1_首次安装.sh 安装"
    exit 1
fi
echo -e "${GREEN}[OK] 已激活环境: $CONDA_ENV_NAME${NC}"

# 检查 PyQt6
if ! python -c "import PyQt6" 2>/dev/null; then
    echo -e "${RED}[错误] PyQt6 未安装${NC}"
    echo "   请运行 ./macOS_1_首次安装.sh 安装依赖"
    exit 1
fi

# 启动 Qt 界面
echo ""
echo -e "${GREEN}[*] 启动 Qt 界面...${NC}"
echo ""
python desktop_qt_ui/main.py
