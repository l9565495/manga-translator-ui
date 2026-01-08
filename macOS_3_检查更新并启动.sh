#!/bin/bash

# ==================== macOS 检查更新并启动 ====================
# 适用于 Apple Silicon Mac
# 对应 Windows 的「步骤3-检查更新并启动.bat」
# =====================================================================

# 使用脚本所在目录作为工作目录
cd "$(dirname "$0")" || { echo "Error: Failed to change directory"; exit 1; }
SCRIPT_DIR="$(pwd)"

# 配置
CONDA_ENV_NAME="manga-env"
MINICONDA_DIR="$SCRIPT_DIR/Miniforge3"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "=============================================="
echo "  Manga Translator UI - 检查更新并启动"
echo "=============================================="
echo ""

# 查找并初始化 Conda
init_conda() {
    if [ -f "$MINICONDA_DIR/bin/conda" ]; then
        export PATH="$MINICONDA_DIR/bin:$PATH"
        eval "$("$MINICONDA_DIR/bin/conda" shell.bash hook)"
        return 0
    fi
    
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

# 检查更新
echo ""
echo -e "${BLUE}[*] 检查版本更新...${NC}"
if [ -f "packaging/check_version.py" ]; then
    python packaging/check_version.py --brief 2>/dev/null || true
else
    echo -e "${YELLOW}[提示] 版本检查脚本不存在，跳过${NC}"
fi

# 启动 Qt 界面
echo ""
echo "========================================"
echo -e "${GREEN}[*] 启动应用程序...${NC}"
echo ""
python desktop_qt_ui/main.py
