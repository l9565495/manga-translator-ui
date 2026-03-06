# v2.1.5 更新日志

发布日期：2026-03-01

## ✨ 新增

- 提示词支持 YAML 格式（优先于 JSON）
- 新增统一提示词加载模块 `prompt_loader.py`
- Web 端支持上传/管理 YAML 提示词文件

## 🔧 优化

- 更新了新的 UI，统一了桌面端主界面、设置页和编辑器的整体风格。
- `_build_system_prompt` 和 `_flatten_prompt_data` 统一到基类，消除约 320 行重复代码
- 清理 `common.py` 死代码，从 2890 行精简至约 2436 行

## 🗑️ 移除

- 旧版 JSON 系统提示词（已有 YAML 替代）
