# v1.9.7 更新日志

发布日期：2025-12-21

## 🐛 修复

### 渲染性能优化
- **修复断句优化算法导致的卡顿问题**：
  - 原算法使用暴力枚举（O(2^n)），当断句标记超过20个时会导致组合数爆炸（如27个断句产生1.34亿种组合）
  - 新算法采用分层策略：
    - 小规模（n≤10）：完全穷举，保证最优解
    - 中等规模（11≤n≤20）：智能采样（单删除+相邻对+部分三元组）
    - 大规模（n>20）：稀疏采样（每隔2个测试单删除，每隔3个测试相邻对）
  - 性能提升：27个断句从1.34亿种组合降至约24种，从卡死到秒级完成

### 翻译错误修复
- **修复空文本导致的AttributeError**：
  - 修复 `apply_dictionary` 函数缺少 `return` 语句，导致预翻译字典替换后返回 `None`
  - 在 `common.py` 的 `_build_unified_user_prompt` 中添加 None 检查，跳过空文本
  - 在 `manga_translator.py` 多处添加 `if region.text is not None` 过滤
  - 在 OCR 过滤阶段添加 `not region.text` 条件，直接过滤空文本

### 文件排序修复
- **修复自然排序类型比较错误**：修复文件列表排序时出现的 `'>' not supported between instances of 'str' and 'int'` 错误，优化 `_natural_sort_key` 方法使用元组确保类型安全

### 超分倍率解析修复
- **支持多种超分倍率格式**：修复加载 JSON 时超分倍率解析错误，现在支持：
  - 数字格式：`2`, `3`, `4`
  - 字符串数字：`"2"`, `"3"`, `"4"`
  - MangaJaNai 格式：`"x2"`, `"x4"`, `"DAT2 x4"`
  - RealCUGAN 格式：`"2x-conservative"`, `"3x-denoise1x"` 等
- **新增 parse_upscale_ratio 辅助函数**：统一处理超分倍率解析，避免字符串与数字运算错误
- **增强错误追踪**：添加详细的错误堆栈信息，便于快速定位问题

### 线程池清理
- **改进线程池清理机制**：为缩略图加载线程池添加 shutdown 函数，在应用关闭时正确清理线程池资源，防止资源泄漏警告

### API响应验证和错误处理增强
- **新增统一的API响应验证**：
  - 在 `common.py` 中添加 `validate_openai_response()` 和 `validate_gemini_response()` 函数
  - 应用到 5 个翻译器：OpenAI、OpenAI HQ、Sakura、Gemini、Gemini HQ
  - 防止无效响应对象导致的 `'str' object has no attribute 'choices'` 错误

- **修复 text_regions 类型错误**：
  - 在 `concurrent_pipeline.py` 中确保 `text_regions` 始终为列表类型
  - 修复翻译失败时错误地赋值为 `True` 导致的 `object of type 'bool' has no len()` 错误
  - 修复无文本时错误地赋值为 `ctx` 对象的问题
  - 在渲染阶段添加类型检查，使用 `isinstance()` 验证

- **检测器输入验证增强**：
  - **DefaultDetector**：在 `_infer` 方法中添加输入图片验证，检查图片是否为空或维度不正确
  - **YOLOOBBDetector**：多层验证机制
    - `_infer()` 方法：详细的输入验证和日志记录
    - `preprocess()` 方法：验证图片有效性和维度
    - `letterbox()` 方法：验证尺寸和计算结果的有效性
    - `_detect_single_patch()` 方法：添加异常处理和 patch 验证
    - `_rearrange_detect()` 方法：验证输入图片和每个 patch 的有效性
  - 防止 OpenCV resize 断言失败：`error: (-215:Assertion failed) !ssize.empty() in function 'cv::resize'`

- **图片加载验证**：
  - 在 `manga_translator.py` 的多个关键位置添加 `img_rgb` 加载后的验证
  - 检查图片是否为空、尺寸是否有效
  - 在超分后、检测前进行验证，防止空图片或无效尺寸导致崩溃
  - 包括主流程、批量处理流程、批量检测流程等多个场景

- **改进错误日志**：所有验证点都添加了详细的错误日志，便于追踪问题根源

### 日志系统优化
- **文件日志始终记录 DEBUG 级别**：日志文件现在始终输出 DEBUG 级别的详细日志，便于问题排查和调试
- **控制台日志根据配置调整**：控制台输出仍然根据"详细日志"配置决定是 DEBUG 还是 INFO 级别
- **统一日志级别管理**：优化 `app_logic.py`、`main.py` 和 `log_service.py` 中的日志级别设置逻辑
- **改进调试体验**：用户可以在保持控制台简洁的同时，在日志文件中获取完整的调试信息
