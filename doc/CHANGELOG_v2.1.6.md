# v2.1.6 更新日志

发布日期：2026-03-14

## ✨ 新增

- 新增 OpenAI Colorizer / OpenAI Renderer 的图像接口按 `API Base URL` 自动适配能力：
  - 命中 **硅基流动** `https://api.siliconflow.cn/v1` 时，`/images/generations` 会自动改用 `image` / `image2` / `image3` 风格请求体，兼容 `Qwen/Qwen-Image-Edit-2509`、`Kwai-Kolors/Kolors` 等模型。
  - 命中 **阿里云百炼原生多模态接口** `https://dashscope.aliyuncs.com/api/v1` 或 `https://dashscope-intl.aliyuncs.com/api/v1` 时，会自动改用 `services/aigc/multimodal-generation/generation`，并按 `input.messages + parameters` 的百炼原生格式发送图像生成 / 图像编辑请求。
  - 命中 **官方 OpenAI** `https://api.openai.com/v1` 时，会按默认 OpenAI 图像接口处理，继续使用 `/images/edits`、`/images/generations`、`/chat/completions` 的兼容回退流程；AI 上色多图提示词的 `Image 1`、`Image 2`、`Image 3` 编号角色说明也同样生效。
  - 命中 **火山引擎 / 其他 OpenAI 兼容图像接口** 时，保留原有 OpenAI 兼容请求格式。
  - 当 `API Base URL` 未命中已知后端时，`/images/generations` 现在会按兼容顺序自动尝试多种请求体格式，减少代理站 / 聚合站因字段差异导致的 400 报错。
- 新增 AI 上色多图提示词的按图号角色说明：请求中的附带图片现在会明确写成 `Image 1`、`Image 2`、`Image 3` 等角色说明，区分目标页、提示词参考图、历史已上色页，避免使用“后面的图”这类笼统描述。
- 新增 AI 上色 / AI 渲染对自定义 API 参数的后端适配：
  - 硅基流动图像接口会原样透传 `cfg`、`num_inference_steps`、`image_size`、`guidance_scale` 等参数。
  - 百炼原生图像接口会自动把自定义参数映射到 `parameters` 字段。

## 🐛 修复

- 修复非并发批量模式下进度条有时长时间不增长的问题：顺序批处理与高质量批处理现在都会在单张图片真正完成后推进整体进度，覆盖普通翻译、导入翻译并渲染、导出原文、导出翻译、仅上色、仅超分、仅修复等批量流程。
- 修复重新打开 JSON 后文本位置不在上一次保存位置的问题：编辑器加载 JSON 时始终从 `lines` 的外接矩形重算 `center`，避免旧版白框中心污染或超分缩放遗漏导致的位置偏移。
- 修复 Qt 编辑器切换选中不同文本框时误触发白框边缘编辑的问题：未选中的文本框首次点击现在仅用于切换选中，不再直接命中白框手柄并进入 `white_edge` / `white_move` 编辑状态。
- 修复 Qt 编辑器移动白框或白框尺寸未变化时仍可能重算字号的问题：白框提交时仅在尺寸实际变化时才执行 `框 -> 字号` 反算，避免来回切换或纯移动操作导致字号被意外刷新。
- 修复竖排线段符号显示方向错误的问题：为 `─ / ━ / ═` 等横线字符补充竖排字形映射，避免在竖排文本中仍按横线样式显示。
- 修复 YOLO OBB 辅助检测器长图统一切割路径中的未初始化变量问题：补上 patch 元信息初始化，避免长图检测时触发 `cannot access local variable 'patch_shape'` 并导致辅助检测回退失败。
- 修复 MangaLens 气泡检测器长图切割与主检测器重排计划不一致的问题：长图分片现在复用共享 `rearrange plan` 与 patch span 计算，统一纵横转置、切片区间和回映射逻辑，减少边界偏移与后续维护分叉。
- 修复极端长宽比图片的修复模块分片尾部可能未被处理的问题：`inpainting` 分片区间改为向上取整并强制最后一块覆盖到图像末端，避免最后几行或几列漏修复。

## ⚡ 优化

- 优化模型辅助合并中 `other` 辅助框的包裹判定：从必须完全包裹改为覆盖率大于 `90%` 即可参与合并，减少检测框边缘轻微偏差导致的漏合并。
