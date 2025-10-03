import sys
import os
import logging
import warnings

# 修复PyInstaller打包后onnxruntime的DLL加载问题
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    # 运行在PyInstaller打包环境中
    if sys.platform == 'win32' and hasattr(os, 'add_dll_directory'):
        # 只设置DLL搜索路径，不预加载
        # 让Python的导入机制自然处理DLL加载
        os.add_dll_directory(sys._MEIPASS)
        onnx_capi_dir = os.path.join(sys._MEIPASS, 'onnxruntime', 'capi')
        if os.path.exists(onnx_capi_dir):
            os.add_dll_directory(onnx_capi_dir)

# 抑制 xformers/triton 警告
warnings.filterwarnings('ignore', message='.*Triton.*')
warnings.filterwarnings('ignore', module='xformers')

# 将项目根目录添加到 sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from PyQt6.QtWidgets import QApplication
from main_window import MainWindow
from services import init_services

def main():
    """
    应用主入口
    """
    # --- 日志配置 ---
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - [%(name)s] - %(message)s',
        stream=sys.stdout,
    )

    # --- 环境设置 ---
    # 1. 创建 QApplication 实例
    app = QApplication(sys.argv)

    # 2. 初始化所有服务
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if not init_services(root_dir):
        logging.fatal("Fatal: Service initialization failed.")
        sys.exit(1)

    # 3. 创建并显示主窗口
    main_window = MainWindow()
    main_window.show()

    # 4. 启动事件循环
    sys.exit(app.exec())

if __name__ == '__main__':
    # 在创建QApplication之前设置DPI策略，这是解决DPI问题的另一种稳妥方式
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    main()
