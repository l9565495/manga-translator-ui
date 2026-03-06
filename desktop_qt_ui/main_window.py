from PyQt6.QtCore import QLibraryInfo, QLocale, QTimer, Qt, QTranslator, pyqtSlot
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox, QStackedWidget

from app_logic import MainAppLogic
from editor.editor_controller import EditorController
from editor.editor_logic import EditorLogic
from editor.editor_model import EditorModel
from editor_view import EditorView
from main_view import MainView
from services import ServiceManager, get_config_service, get_logger, get_state_manager, get_i18n_manager


class MainWindow(QMainWindow):
    """
    应用主窗口，继承自 QMainWindow。
    负责承载所有UI组件、菜单栏、工具栏等。
    """
    def __init__(self):
        super().__init__()

        self.logger = get_logger(__name__)
        self.i18n = get_i18n_manager()
        self._qt_translator = None
        self._apply_qt_translator(self.i18n.get_current_locale() if self.i18n else "en_US")
        
        self.setWindowTitle(self._t("Manga Translator"))
        self.resize(1300, 800) # 设置默认窗口大小（增加20像素）
        self.setMinimumSize(800, 600) # 设置最小窗口大小
        # 不设置最大大小，允许无限制调整
        
        # 窗口居中显示
        from PyQt6.QtGui import QScreen
        screen = QScreen.availableGeometry(self.screen())
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        
        # 窗口图标已在 main.py 中设置，这里不需要重复设置
        
        # 当前应用的主题（用于逻辑判断）
        self.current_applied_theme = "light"

        self._setup_logic_and_models()
        self._setup_ui()
        self._load_stylesheet()  # 加载样式表
        self._connect_signals()

        self.app_logic.initialize()
        
        # 检查是否需要启动系统主题监听
        config = self.config_service.get_config()
        if config.app.theme == "system":
            self.last_system_theme = self._detect_windows_theme()
            self.theme_check_timer = QTimer(self)
            self.theme_check_timer.timeout.connect(self._check_system_theme_change)
            self.theme_check_timer.start(5000)  # 每5秒检查一次
    
    def _t(self, key: str, **kwargs) -> str:
        """翻译辅助方法"""
        if self.i18n:
            return self.i18n.translate(key, **kwargs)
        return key

    def _setup_logic_and_models(self):
        """实例化所有逻辑和数据模型"""
        self.config_service = get_config_service()
        self.state_manager = get_state_manager()
        config = self.config_service.get_config()

        initial_theme = config.app.theme
        if initial_theme == "system":
            detected_theme = self._detect_windows_theme()
            if detected_theme == "dark":
                initial_theme = "dark"
            else:
                initial_theme = config.app.theme_user_preference

        from main_view_parts.theme import set_current_theme

        set_current_theme(initial_theme)
        self.current_applied_theme = initial_theme

        # --- Logic Controllers ---
        self.app_logic = MainAppLogic()
        ServiceManager.register_service('app_logic', self.app_logic)
        self.editor_model = EditorModel()
        self.editor_controller = EditorController(self.editor_model)
        self.editor_logic = EditorLogic(self.editor_controller)

    def _setup_ui(self):
        """初始化UI组件"""
        # 不显示顶部菜单栏，菜单功能统一整合到设置区域
        self._create_ui_actions()
        self.menuBar().hide()

        # --- 中心布局 (QStackedWidget) ---
        self.stacked_widget = QStackedWidget()
        self.setCentralWidget(self.stacked_widget)

        self.main_view = MainView(self.app_logic, self)
        self.editor_view = EditorView(self.app_logic, self.editor_model, self.editor_controller, self.editor_logic, self)

        # 设置 app_logic 对 main_view 的引用，用于更新进度条
        self.app_logic.main_view = self.main_view

        self.stacked_widget.addWidget(self.main_view)
        self.stacked_widget.addWidget(self.editor_view)

        self.stacked_widget.setCurrentWidget(self.main_view)

    def _create_ui_actions(self):
        """创建内部动作对象（无顶部菜单栏）"""
        self.add_files_action = QAction(self._t("&Add Files..."), self)
        self.undo_action = QAction(self._t("&Undo"), self)
        self.redo_action = QAction(self._t("&Redo"), self)
        self.main_view_action = QAction(self._t("Main View"), self)
        self.editor_view_action = QAction(self._t("Editor View"), self)
        self.light_theme_action = QAction(self._t("Light"), self)
        self.dark_theme_action = QAction(self._t("Dark"), self)
        self.gray_theme_action = QAction(self._t("Gray"), self)
        self.system_theme_action = QAction(self._t("Follow System"), self)

    def _load_stylesheet(self):
        """加载样式表，根据配置选择主题"""
        from services import get_config_service
        config_service = get_config_service()
        config = config_service.get_config()
        
        # 获取主题设置，Pydantic会自动使用默认值'light'
        theme = config.app.theme
        self._apply_theme(theme)
    
    def _apply_theme(self, theme: str):
        """应用指定的主题"""
        
        # 处理系统主题逻辑：如果是 'system'，则解析为实际主题
        if theme == 'system':
            sys_theme = self._detect_windows_theme()
            if sys_theme == 'dark':
                self._apply_theme('dark')
            else:
                config = self.config_service.get_config()
                # 使用用户偏好（light 或 gray）
                self._apply_theme(config.app.theme_user_preference)
            return

        # 记录当前实际应用的主题
        self.current_applied_theme = theme
        
        from main_view_parts.theme import apply_application_theme, build_theme_palette

        apply_application_theme(theme, QApplication.instance())
        palette = build_theme_palette(theme)
        self.setPalette(palette)
        self.setStyleSheet("")

        # 通知各视图应用对应主题的内联样式
        if hasattr(self, 'main_view') and self.main_view:
            self.main_view._apply_reference_ui_style(theme)
            self.main_view.update()
        if hasattr(self, 'editor_view') and self.editor_view:
            self.editor_view._apply_editor_style(theme)
            self.editor_view.update()
        if hasattr(self, "stacked_widget") and self.stacked_widget:
            self.stacked_widget.update()
        self.update()
        self._apply_native_title_bar_theme(theme)
        QTimer.singleShot(0, lambda active_theme=theme: self._apply_native_title_bar_theme(active_theme))

    def _apply_native_title_bar_theme(self, theme: str):
        """同步 Windows 原生标题栏颜色，避免深色内容区配浅色系统标题栏。"""
        import sys

        if sys.platform != "win32":
            return

        try:
            import ctypes
            from ctypes import wintypes

            from PyQt6.QtGui import QColor

            from main_view_parts.theme_colors import get_theme_colors

            hwnd = int(self.winId())
            if not hwnd:
                return

            colors = get_theme_colors(theme)
            dwmapi = ctypes.windll.dwmapi
            user32 = ctypes.windll.user32

            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1 = 19
            DWMWA_BORDER_COLOR = 34
            DWMWA_CAPTION_COLOR = 35
            DWMWA_TEXT_COLOR = 36
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020

            def _to_colorref(value: str):
                color = QColor(value)
                return wintypes.DWORD(color.red() | (color.green() << 8) | (color.blue() << 16))

            def _set_dwm_attr(attribute: int, data):
                return dwmapi.DwmSetWindowAttribute(
                    wintypes.HWND(hwnd),
                    ctypes.c_uint(attribute),
                    ctypes.byref(data),
                    ctypes.sizeof(data),
                )

            is_dark_caption = theme in {"dark", "gray"}
            dark_mode = ctypes.c_int(1 if is_dark_caption else 0)
            result = _set_dwm_attr(DWMWA_USE_IMMERSIVE_DARK_MODE, dark_mode)
            if result != 0:
                _set_dwm_attr(DWMWA_USE_IMMERSIVE_DARK_MODE_BEFORE_20H1, dark_mode)

            caption_color = _to_colorref(colors["bg_window_shell"])
            border_color = _to_colorref(colors["border_sidebar"])
            text_color = _to_colorref(colors["text_bright"] if is_dark_caption else colors["text_accent"])

            _set_dwm_attr(DWMWA_CAPTION_COLOR, caption_color)
            _set_dwm_attr(DWMWA_BORDER_COLOR, border_color)
            _set_dwm_attr(DWMWA_TEXT_COLOR, text_color)

            user32.SetWindowPos(
                wintypes.HWND(hwnd),
                wintypes.HWND(0),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
        except Exception as exc:
            self.logger.debug(f"应用原生标题栏主题失败: {exc}")
    
    def _detect_windows_theme(self) -> str:
        """检测Windows系统主题（深色/浅色）
        返回: 'dark' 或 'light'
        """
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if value == 1 else "dark"
        except Exception as e:
            # 默认返回浅色（或记录日志）
            # self.logger.warning(f"无法检测系统主题: {e}")
            return "light"

    def _check_system_theme_change(self):
        """检查系统主题是否变化"""
        config = self.config_service.get_config()
        if config.app.theme != "system":
            # 如果用户切换到其他主题，停止监听
            if hasattr(self, 'theme_check_timer'):
                self.theme_check_timer.stop()
            return
        
        current_system_theme = self._detect_windows_theme()
        if current_system_theme != self.last_system_theme:
            self.logger.info(f"系统主题变化: {self.last_system_theme} -> {current_system_theme}")
            
            if current_system_theme == "dark":
                # 系统切换到深色
                if self.current_applied_theme != "dark":
                    # 保存用户偏好（浅色或灰色）
                    config.app.theme_user_preference = self.current_applied_theme
                    self.config_service.save_config_file()
                    self.logger.info(f"保存用户偏好: {self.current_applied_theme}")
                # 切换到深色主题
                self._apply_theme("dark")
            else:
                # 系统切换到浅色
                # 恢复用户偏好
                user_pref = config.app.theme_user_preference
                self._apply_theme(user_pref)
                self.logger.info(f"恢复用户偏好: {user_pref}")
            
            self.last_system_theme = current_system_theme

    def _change_theme(self, theme: str):
        """切换主题并保存到配置"""
        from services import get_config_service
        config_service = get_config_service()
        config = config_service.get_config()
        
        if theme == "system":
            # 应用主题（逻辑主题）
            self._apply_theme("system")
            
            # 启动监听
            self.last_system_theme = self._detect_windows_theme()
            if not hasattr(self, 'theme_check_timer'):
                self.theme_check_timer = QTimer(self)
                self.theme_check_timer.timeout.connect(self._check_system_theme_change)
            
            if not self.theme_check_timer.isActive():
                self.theme_check_timer.start(5000)
        else:
            # 停止监听
            if hasattr(self, 'theme_check_timer'):
                self.theme_check_timer.stop()
                
            # 应用主题
            self._apply_theme(theme)
            
            # 如果是浅色或灰色，更新用户偏好
            if theme in ['light', 'gray']:
                config.app.theme_user_preference = theme
        
        # 保存到配置
        config.app.theme = theme
        config_service.set_config(config)
        
        # 保存到文件
        config_service.save_config_file()

    def _connect_signals(self):
        # --- MainAppLogic Connections ---
        self.app_logic.config_loaded.connect(self.main_view.set_parameters)
        self.app_logic.config_loaded.connect(self.editor_view.property_panel.repopulate_options)
        self.app_logic.files_added.connect(self.main_view.file_list.add_files)
        self.app_logic.files_cleared.connect(self.main_view.file_list.clear)
        self.app_logic.file_removed.connect(self.main_view.file_list.remove_file)
        self.app_logic.file_removed.connect(self._on_file_removed_update_editor)
        self.app_logic.files_cleared.connect(self._on_files_cleared_update_editor)
        self.app_logic.output_path_updated.connect(self.main_view.update_output_path_display)
        self.app_logic.task_completed.connect(self.on_task_completed, type=Qt.ConnectionType.QueuedConnection)
        self.app_logic.error_dialog_requested.connect(self._show_error_dialog, type=Qt.ConnectionType.QueuedConnection)

        # --- View to Logic Connections ---
        self.main_view.setting_changed.connect(self.app_logic.update_single_config)
        self.main_view.editor_view_requested.connect(self.switch_to_editor_view)
        self.main_view.theme_change_requested.connect(self._change_theme)
        self.main_view.language_change_requested.connect(self._change_language)

        # --- Live-reload connection ---
        self.app_logic.render_setting_changed.connect(self.editor_logic.on_global_render_setting_changed)

        # --- View to Coordinator Connections ---
        self.main_view.file_list.file_selected.connect(self.on_file_selected_from_main_list)
        self.main_view.file_list.files_dropped.connect(self.app_logic.add_files)  # 拖放文件支持
        # self.main_view.enter_editor_button.clicked.connect(self.enter_editor_mode) # Example for a dedicated button

        # --- Editor related connections ---
        self.editor_view.back_to_main_requested.connect(lambda: self.stacked_widget.setCurrentWidget(self.main_view))

        # --- View Switching Connections ---
        self.main_view_action.triggered.connect(lambda: self.stacked_widget.setCurrentWidget(self.main_view))
        self.editor_view_action.triggered.connect(self.switch_to_editor_view)

        # --- 撤销/重做连接到编辑器controller ---
        self.undo_action.triggered.connect(self.editor_controller.undo)
        self.redo_action.triggered.connect(self.editor_controller.redo)
        
        # --- 主题切换连接 ---
        self.light_theme_action.triggered.connect(lambda: self._change_theme("light"))
        self.dark_theme_action.triggered.connect(lambda: self._change_theme("dark"))
        self.gray_theme_action.triggered.connect(lambda: self._change_theme("gray"))
        self.system_theme_action.triggered.connect(lambda: self._change_theme("system"))

    @pyqtSlot(str)
    def on_file_selected_from_main_list(self, file_path: str):
        """
        Coordinator slot. Handles when a file is double-clicked in the main view.
        It tells the editor logic to load the file, then switches the view.
        """
        self.logger.info(f"File double-clicked from main list: {file_path}. Switching to editor.")
        self.enter_editor_mode(file_to_load=file_path)
    
    def _on_file_removed_update_editor(self, file_path: str):
        """当主页文件被移除时，更新编辑器（如果编辑器正在显示该文件）"""
        if self.stacked_widget.currentWidget() == self.editor_view:
            # 检查当前加载的图片是否被移除
            current_image = self.editor_controller.model.get_source_image_path()
            
            if current_image:
                import os
                norm_current = os.path.normpath(current_image)
                norm_removed = os.path.normpath(file_path)
                
                # 如果移除的是当前图片
                if norm_current == norm_removed:
                    self.editor_controller.model.set_image(None)
                    self.editor_controller._clear_editor_state()
                # 如果移除的是文件夹，检查当前图片是否在该文件夹内
                elif os.path.isdir(file_path):
                    try:
                        # 检查当前图片是否在被移除的文件夹内
                        if os.path.commonpath([norm_current, norm_removed]) == norm_removed:
                            self.editor_controller.model.set_image(None)
                            self.editor_controller._clear_editor_state()
                    except ValueError:
                        # 不同驱动器，跳过
                        pass
            
            # 注意：编辑器有自己独立的文件列表，不需要同步主页的删除操作
            # 只有当主页文件全部清空时，才清空编辑器列表
    
    def _on_files_cleared_update_editor(self):
        """当文件列表被清空时，清空编辑器"""
        if self.stacked_widget.currentWidget() == self.editor_view:
            # 如果当前在编辑器视图，清空编辑器
            self.logger.info("Files cleared. Clearing editor.")
            # 清空文件列表（内部会自动清空画布和状态）
            self.editor_logic.clear_list()

    def _change_language(self, locale_code: str):
        """切换语言"""
        if self.i18n and self.i18n.set_locale(locale_code):
            self._apply_qt_translator(locale_code)
            # 保存语言设置到配置
            config = self.config_service.get_config()
            config.app.ui_language = locale_code
            self.config_service.set_config(config)
            self.config_service.save_config_file()
            
            # 刷新UI文本
            self._refresh_ui_texts()
            self.logger.info(f"语言已切换到: {locale_code}")

    def _apply_qt_translator(self, locale_code: str):
        """加载 Qt 内建控件翻译（如 QColorDialog），使其跟随应用语言。"""
        app = QApplication.instance()
        if app is None:
            return

        if self._qt_translator is not None:
            app.removeTranslator(self._qt_translator)
            self._qt_translator = None

        translator = QTranslator(self)
        qt_translations_dir = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)

        # locale_code 形如 zh_CN / en_US，依次尝试精确与语言级别匹配
        language = QLocale(locale_code).name().split('_', 1)[0]
        candidates = (
            f"qtbase_{locale_code}",
            f"qtbase_{language}",
            f"qt_{locale_code}",
            f"qt_{language}",
        )

        loaded = any(translator.load(name, qt_translations_dir) for name in candidates)
        if loaded:
            app.installTranslator(translator)
            self._qt_translator = translator
    
    def _refresh_ui_texts(self):
        """刷新UI文本"""
        # 更新窗口标题
        self.setWindowTitle(self._t("Manga Translator"))
        self._refresh_action_texts()
        
        # 刷新主视图的所有文本
        if hasattr(self, 'main_view') and self.main_view:
            self.main_view.refresh_ui_texts()
        
        # 刷新编辑器视图的所有文本（如果存在）
        if hasattr(self, 'editor_view') and self.editor_view:
            if hasattr(self.editor_view, 'refresh_ui_texts'):
                self.editor_view.refresh_ui_texts()

    def _refresh_action_texts(self):
        """刷新内部动作文本（菜单栏隐藏时仍保留动作对象）"""
        if hasattr(self, 'add_files_action'):
            self.add_files_action.setText(self._t("&Add Files..."))
        if hasattr(self, 'undo_action'):
            self.undo_action.setText(self._t("&Undo"))
        if hasattr(self, 'redo_action'):
            self.redo_action.setText(self._t("&Redo"))
        if hasattr(self, 'main_view_action'):
            self.main_view_action.setText(self._t("Main View"))
        if hasattr(self, 'editor_view_action'):
            self.editor_view_action.setText(self._t("Editor View"))
        if hasattr(self, 'light_theme_action'):
            self.light_theme_action.setText(self._t("Light"))
        if hasattr(self, 'dark_theme_action'):
            self.dark_theme_action.setText(self._t("Dark"))
        if hasattr(self, 'gray_theme_action'):
            self.gray_theme_action.setText(self._t("Gray"))
        if hasattr(self, 'system_theme_action'):
            self.system_theme_action.setText(self._t("Follow System"))
    
    @pyqtSlot(list)
    def on_task_completed(self, saved_files: list):
        """
        Handles the completion of a translation task.
        Asks the user if they want to open the results in the editor.
        """
        try:
            if not saved_files:
                return

            # 创建自定义消息框，避免图片过多导致闪退
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self._t('Task Completed'))
            msg_box.setText(self._t("Translation completed, {count} files saved.\n\nOpen results in editor?", count=len(saved_files)))
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)
            
            # 不设置图标，避免加载过多资源
            msg_box.setIcon(QMessageBox.Icon.Question)
            
            reply = msg_box.exec()

            if reply == QMessageBox.StandardButton.Yes:
                self.enter_editor_mode(files_to_load=saved_files)
        except Exception as e:
            self.logger.error(f"on_task_completed 发生异常: {e}", exc_info=True)
            import traceback
            traceback.print_exc()

    @pyqtSlot(str)
    def _show_error_dialog(self, error_message: str):
        """弹出翻译错误提示框"""
        try:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle(self._t("Translation Error"))
            msg_box.setIcon(QMessageBox.Icon.Critical)
            msg_box.setText(error_message)
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.exec()
        except Exception as e:
            self.logger.error(f"_show_error_dialog error: {e}", exc_info=True)

    def switch_to_editor_view(self):
        """
        Simply switches to the editor view without reloading file lists.
        Used when user manually switches views.
        """
        self.stacked_widget.setCurrentWidget(self.editor_view)

    def enter_editor_mode(self, file_to_load: str = None, files_to_load: list = None):
        """
        Switches to the editor view and loads the necessary files.
        file_to_load: 单个文件路径（双击文件时使用）
        files_to_load: 翻译后的文件列表（从翻译完成进入时使用）
        """
        import os

        try:
            # 获取完整的文件夹树结构
            tree_structure = self.app_logic.get_folder_tree_structure()
            expanded_files = tree_structure['files']
            folder_tree = tree_structure['tree']

            # 传递翻译后的图片列表给编辑器
            # 从file_to_folder_map获取翻译后的图片路径
            translated_files = []
            translated_folder_map = {}  # 翻译后文件的文件夹映射
            config = self.app_logic.config_service.get_config()
            output_folder = config.app.last_output_path
            output_format = config.cli.format
            if not output_format or output_format == "不指定":
                output_format = None
            save_info = {
                'output_folder': output_folder,
                'format': output_format,
                'save_to_source_dir': config.cli.save_to_source_dir,
            }
            
            for source_file in expanded_files:
                # 根据源文件路径构造翻译后的图片路径
                translated_file = self.app_logic._calculate_output_path(source_file, save_info)
                if os.path.exists(translated_file):
                    translated_files.append(translated_file)
                    translated_folder_map[translated_file] = os.path.dirname(translated_file)

            # 判断是否从翻译完成进入（有 files_to_load 参数）
            if files_to_load and len(files_to_load) > 0:
                # 从翻译完成进入：显示翻译后的文件列表
                # 不使用源文件的 folder_tree，让编辑器根据翻译后的文件自己构建树结构
                self.editor_logic.load_file_lists(
                    source_files=expanded_files,      # 传递源文件列表（用于配对）
                    translated_files=translated_files, # 传递翻译后的文件列表
                    folder_tree=None,                 # 不使用源文件的树结构
                    show_translated=True              # 显示翻译后的文件列表
                )
                
                # 加载第一个翻译后的文件
                self.editor_logic.load_image_into_editor(files_to_load[0])
            else:
                # 手动打开编辑器：显示源文件列表
                self.editor_logic.load_file_lists(
                    source_files=expanded_files, 
                    translated_files=translated_files,
                    folder_tree=folder_tree
                )
                # 如果指定了要加载的文件
                if file_to_load:
                    self.editor_logic.load_image_into_editor(file_to_load)
                elif translated_files:
                    # 如果没有指定，加载第一个翻译后的文件
                    self.editor_logic.load_image_into_editor(translated_files[0])

            self.stacked_widget.setCurrentWidget(self.editor_view)
        except Exception as e:
            self.logger.error(f"enter_editor_mode 发生异常: {e}", exc_info=True)
            import traceback
            traceback.print_exc()

    def closeEvent(self, event):
        """处理窗口关闭事件"""
        self.app_logic.shutdown()
        event.accept()
