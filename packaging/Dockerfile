# Manga Translator Docker Image
# 支持 CPU 和 GPU 版本

ARG CUDA_VERSION=12.1.0
ARG PYTHON_VERSION=3.12
ARG BUILD_TYPE=cpu

# ===== CPU 版本 =====
FROM python:${PYTHON_VERSION}-slim AS base-cpu

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    wget \
    curl \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ===== GPU 版本 =====
FROM nvidia/cuda:${CUDA_VERSION}-cudnn8-runtime-ubuntu22.04 AS base-gpu

# 安装 Python 3.12
RUN apt-get update && apt-get install -y \
    software-properties-common \
    && add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y \
    python3.12 \
    python3.12-dev \
    python3.12-distutils \
    python3-pip \
    git \
    wget \
    curl \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 设置 Python 3.12 为默认
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1

# 升级 pip
RUN python -m pip install --upgrade pip

# ===== 选择基础镜像 =====
FROM base-${BUILD_TYPE} AS base

# 设置工作目录
WORKDIR /app

# 复制项目文件
COPY . /app/

# 安装 Python 依赖
ARG BUILD_TYPE=cpu
RUN if [ "$BUILD_TYPE" = "gpu" ]; then \
        # GPU 版本：先安装 pydensecrf 从源码，然后安装其他依赖
        pip install --no-cache-dir Cython numpy && \
        pip install --no-cache-dir git+https://github.com/lucasb-eyer/pydensecrf.git && \
        grep -v "pydensecrf" requirements_gpu.txt > /tmp/requirements_gpu_no_pydensecrf.txt && \
        pip install --no-cache-dir -r /tmp/requirements_gpu_no_pydensecrf.txt; \
    else \
        # CPU 版本：先安装 pydensecrf 从源码，然后安装其他依赖
        pip install --no-cache-dir Cython numpy && \
        pip install --no-cache-dir git+https://github.com/lucasb-eyer/pydensecrf.git && \
        grep -v "pydensecrf" requirements_cpu.txt > /tmp/requirements_cpu_no_pydensecrf.txt && \
        pip install --no-cache-dir -r /tmp/requirements_cpu_no_pydensecrf.txt; \
    fi

# 创建必要的目录
RUN mkdir -p /app/fonts /app/dict /app/result /app/models /app/logs

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV MANGA_TRANSLATOR_WEB_SERVER=true

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

# 启动命令
CMD ["python", "-m", "manga_translator", "web", "--host", "0.0.0.0", "--port", "8000"]
