A卡 MTU 常见问题
目前 A卡 rocm7.2.1 已经完美支持 pytorch 
6000-9000系列
目前已知 windows下rocm 无法GPU加速 onnx模型 所以导致 paddle ocr相关模型 都会使用cpu加速

推荐设置：
文本检测开启 yolo辅助检测
日漫推荐ocr ：48px+mocr
英文推荐ocr: 48px+paddleocr
韩漫推荐ocr：paddlekorean
西语推荐ocr：paddlelatin



1 翻译时出现 no module named'torch.C. distributed c10d';'torch.c' is not package
答：transformer兼容问题 升级版本 ＞4.55

2. 翻译过程很卡 系统很卡 (已知RX7600有问题）
答：降级到 7.1.1rocm版本

3.