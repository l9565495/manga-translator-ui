# v2.0.9 更新日志

发布日期：待定

## ✨ 新功能

- **增强的输出格式支持**：
  - Qt 编辑器和翻译后端现在支持更多输出格式
  - 新增支持：AVIF、BMP、TIFF、HEIC/HEIF 格式
  - 完整支持列表：PNG、JPEG、WebP、AVIF、BMP、TIFF、HEIC/HEIF
  - HEIC/HEIF 格式需要安装 `pillow-heif` 库，未安装时自动降级为 PNG

- **curl_cffi TLS 指纹伪装**：
  - Gemini 翻译器支持 curl_cffi 绕过 TLS 指纹检测
  - 支持自定义 Gemini API Base 使用 Google 原生认证方式（x-goog-api-key）
  - 支持包含 "/" 的模型名（如 z-ai/glm4.7）自动 URL 编码

## 🐛 修复

- 修复 Qt 编辑器翻译图查看模式下图片不显示的问题（翻译后的图片现在正确加载到 inpainted 层）
- 修复并行模式下 PSD 导出图层缺少修复图的问题（修复图现在在 PSD 导出前保存）
- 修复并行模式下停止翻译响应不及时的问题（增加更多取消检查点，优化线程停止逻辑）
- 修复 Qt 编辑器中手动添加换行符后文本仍被强制换行的问题（检测到换行符时自动开启 AI 断句）
- 修复 Qt 编辑器蒙版编辑工具光标在整个应用程序显示的问题（光标现在仅在画布上显示）
- 修复 `AsyncGeminiCurlCffi` 响应解析时 `NoneType` 不可迭代错误
- 修复 Gemini API 安全设置格式错误（去掉枚举类名前缀）
- 修复 Gemini API 请求缺少 `role` 字段导致 400 错误
- 修复多模态不支持错误检测（新增 `image_url`、`expected \`text\``、`unknown variant` 关键词）

## 🔧 优化

- curl_cffi 客户端仅在出错时打印日志
- 更新模型推荐为最新版本（gpt-5.2、gemini-3-pro、grok-4.2）
- 友好错误提示使用 UI 显示名称（OpenAI高质量翻译、Google Gemini 等）
