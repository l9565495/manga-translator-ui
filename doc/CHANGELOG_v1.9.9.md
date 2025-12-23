# v1.9.9 更新日志

发布日期：2025-12-22

## ⚡ 优化

### 超分模型优化
- **MangaJaNai 延迟加载优化**：优化模型加载策略，不再在初始化时预加载默认模型，而是在推理时根据图片类型（彩色/黑白）动态加载对应模型，避免同时加载多个模型导致显存溢出

### 依赖安装优化
- **优化 PyTorch 依赖源配置**：移除 requirements 文件中的 `--extra-index-url https://pypi.org/simple`，避免版本冲突
- **移除 xformers 版本限制**：将 `xformers==0.0.32.post2` 改为 `xformers`，允许安装最新兼容版本
- **扩展 PyTorch 包识别列表**：在 launch.py 中扩展了 PyTorch 相关包的识别范围，确保所有 NVIDIA CUDA、Intel oneAPI 及 PyTorch 生态包都从正确的源（cu128）下载，包括：
  - PyTorch 核心包及变体（torch, torchvision, torchaudio, pytorch-triton 等）
  - NVIDIA CUDA 库（nvidia-cublas-cu12, nvidia-cudnn-cu12, nvidia-nccl-cu12 等）
  - Intel oneAPI 库（intel-openmp, oneccl, onemkl-sycl-* 等）
  - PyTorch 生态包（triton, fbgemm-gpu, vllm, flashinfer 等）

## 🐛 修复

### 超分模型修复
- **修复 MangaJaNai 模型切换显存问题**：修复在自动模式（x2/x4）下，从黑白图片切换到彩色图片时，旧模型未卸载导致显存占用过高的问题

### 上色模块修复
- **修复并行模式禁用时图片加载问题**：修复当用户启用并行模式但因特殊模式（如"仅上色"）导致并行被禁用时，系统未正确加载图片导致 `ctx.input` 为文件路径字符串而非 PIL Image 对象的问题（错误信息：`str object has no attribute 'convert'`）
