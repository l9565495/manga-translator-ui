# v2.0.7 更新日志

发布日期：2026-01-08

## 🐛 修复

- 修复 Qt 编辑器导出 PSD 文件路径错误的问题：
  - PSD 文件现在会正确保存到原图所在目录的 `manga_translator_work/psd/` 下，而不是临时目录，避免导出后文件丢失
  - 修复 PSD 导出时无法找到 inpainted 图片的问题：现在使用原图路径查找 `manga_translator_work/inpainted/` 下的修复图，而不是在临时目录查找
