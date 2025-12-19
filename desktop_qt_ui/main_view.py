
import os
from functools import partial

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from services import get_config_service, get_i18n_manager
from widgets.file_list_view import FileListView
from utils.resource_helper import resource_path


class MainView(QWidget):
    """
    主翻译视图，对应旧UI的 MainView。
    包含文件列表、设置和日志。
    """
    setting_changed = pyqtSignal(str, object)
    env_var_changed = pyqtSignal(str, str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.config_service = get_config_service()
        self.i18n = get_i18n_manager()
        self.env_widgets = {}
        self._env_debounce_timer = QTimer(self)
        self._env_debounce_timer.setSingleShot(True)
        self._env_debounce_timer.setInterval(500) # 500ms debounce delay

        self.layout = QHBoxLayout(self)
        self.env_var_changed.connect(self.controller.save_env_var)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # --- 创建主分割器 (左右) ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.layout.addWidget(main_splitter)

        # --- 左侧面板 ---
        left_panel = self._create_left_panel()

        # --- 右侧面板 ---
        right_panel = self._create_right_panel()

        # --- 组合布局 ---
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 1) # 左侧面板可以拉伸
        main_splitter.setStretchFactor(1, 3) # 右侧面板拉伸更多
        main_splitter.setCollapsible(0, True) # 左侧面板可以折叠
        main_splitter.setCollapsible(1, True) # 右侧面板可以折叠
        main_splitter.setSizes([300, 980]) # 设置初始比例
        main_splitter.setHandleWidth(6) # 设置分隔条宽度

        self._create_dynamic_settings()

        # Connect signals for button state management
        self.controller.state_manager.is_translating_changed.connect(self.on_translation_state_changed, type=Qt.ConnectionType.QueuedConnection)
        self.controller.state_manager.current_config_changed.connect(self.update_start_button_text)
        QTimer.singleShot(100, self.update_start_button_text) # Set initial text
        QTimer.singleShot(100, self._sync_workflow_mode_from_config) # Sync workflow mode dropdown
    
    def _t(self, key: str, **kwargs) -> str:
        """翻译辅助方法"""
        if self.i18n:
            return self.i18n.translate(key, **kwargs)
        return key

    def _open_filter_list(self):
        """打开过滤列表文件"""
        from manga_translator.utils.text_filter import ensure_filter_list_exists
        import subprocess
        import sys
        
        filter_path = ensure_filter_list_exists()
        
        # 根据操作系统打开文件
        if sys.platform == 'win32':
            subprocess.Popen(['notepad.exe', filter_path])
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', filter_path])
        else:
            subprocess.Popen(['xdg-open', filter_path])

    @pyqtSlot(dict)
    def set_parameters(self, config: dict):
        """
        Receives a config dictionary and starts the incremental creation of setting widgets.
        """
        # Store config and sections to process
        self._config_to_process = config
        self._sections_to_process = [
            "translator", "cli", "detector", "inpainter",
            "render", "upscale", "colorizer", "ocr", "global"
        ]
        
        # Clear existing widgets immediately
        for panel in self.tab_frames.values():
            layout = panel.layout()
            while layout.count():
                child = layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()

        # Schedule the first chunk of work
        QTimer.singleShot(0, self._process_next_setting_chunk)

    def _process_next_setting_chunk(self):
        """
        Processes one section of the settings UI and schedules the next one.
        """
        if not self._sections_to_process:
            self._finalize_settings_ui()
            return

        section = self._sections_to_process.pop(0)
        config = self._config_to_process

        # 使用固定的英文键名
        panel_map = {
            "translator": self.tab_frames["Basic Settings_left"],
            "cli": self.tab_frames["Basic Settings_right"],
            "detector": self.tab_frames["Advanced Settings_left"],
            "inpainter": self.tab_frames["Advanced Settings_left"],
            "render": self.tab_frames["Advanced Settings_right"],
            "upscale": self.tab_frames["Advanced Settings_right"],
            "colorizer": self.tab_frames["Advanced Settings_right"],
            "ocr": self.tab_frames["Options_left"],
            "global": self.tab_frames["Options_right"],
        }

        panel = panel_map.get(section)
        if section == "global":
            # 处理顶层的全局参数
            global_params = {k: v for k, v in config.items() if k not in ["translator", "cli", "detector", "inpainter", "render", "upscale", "colorizer", "ocr", "app"]}
            if global_params and panel:
                self._create_param_widgets(global_params, panel.layout(), "")
        elif panel and section in config:
            self._create_param_widgets(config[section], panel.layout(), section)

        # Schedule the next chunk
        QTimer.singleShot(0, self._process_next_setting_chunk)

    def _finalize_settings_ui(self):
        """
        Called after all incremental updates are done. Sets up dependent UI like .env section.
        """
        translator_combo = self.findChild(QComboBox, "translator.translator")
        if translator_combo:
            parent_layout = translator_combo.parent().layout()
            if parent_layout:
                # 如果 env_group_box 已存在，先移除它
                if hasattr(self, 'env_group_box') and self.env_group_box is not None:
                    try:
                        # 检查对象是否还有效
                        if not self.env_group_box.isWidgetType() or self.env_group_box.parent() is None:
                            # 对象已被删除，只需重置引用
                            self.env_group_box = None
                        else:
                            parent_layout.removeWidget(self.env_group_box)
                            self.env_group_box.deleteLater()
                            self.env_group_box = None
                    except RuntimeError:
                        # 对象已被删除
                        self.env_group_box = None
                
                # 重新创建 env_group_box - 使用 VBoxLayout 包含预设管理和环境变量输入
                self.env_group_box = QGroupBox(self._t("API Keys (.env)"))
                from PyQt6.QtWidgets import QGridLayout
                env_main_layout = QVBoxLayout(self.env_group_box)
                
                # 预设管理区域
                preset_widget = QWidget()
                preset_layout = QHBoxLayout(preset_widget)
                preset_layout.setContentsMargins(0, 0, 0, 0)
                
                preset_label = QLabel(self._t("Preset:"))
                self.preset_combo = QComboBox()
                self.preset_combo.setMinimumWidth(150)
                self.preset_combo.setEditable(False)
                self._refresh_preset_list()
                
                # 从配置中读取上次使用的预设并选中
                saved_preset = self.controller.config_service.get_current_preset()
                index = self.preset_combo.findText(saved_preset)
                if index >= 0:
                    self.preset_combo.setCurrentIndex(index)
                
                self.add_preset_button = QPushButton("+")
                self.add_preset_button.setFixedWidth(30)
                self.add_preset_button.setToolTip(self._t("Add new preset"))
                
                self.delete_preset_button = QPushButton(self._t("Delete"))
                self.delete_preset_button.setToolTip(self._t("Delete selected preset"))
                
                preset_layout.addWidget(preset_label)
                preset_layout.addWidget(self.preset_combo)
                preset_layout.addWidget(self.add_preset_button)
                preset_layout.addWidget(self.delete_preset_button)
                preset_layout.addStretch()
                
                # 记录当前预设名称，用于切换时自动保存
                self._current_preset_name = self.preset_combo.currentText() if self.preset_combo.count() > 0 else ""
                
                env_main_layout.addWidget(preset_widget)
                
                # 环境变量输入区域
                env_input_widget = QWidget()
                self.env_layout = QGridLayout(env_input_widget)
                self.env_layout.setColumnStretch(1, 1)  # 让输入框列可以拉伸
                self.env_layout.setHorizontalSpacing(10)
                self.env_layout.setVerticalSpacing(8)
                self.env_layout.setContentsMargins(0, 0, 0, 0)
                
                env_main_layout.addWidget(env_input_widget)
                
                # 连接预设按钮信号
                self.add_preset_button.clicked.connect(self._on_add_preset_clicked)
                self.delete_preset_button.clicked.connect(self._on_delete_preset_clicked)
                # 切换预设时自动保存当前预设并加载新预设
                self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
                
                # 关键：使用 addRow 只传一个参数，让 GroupBox 跨越整行，不受标签列宽度影响
                parent_layout.addRow(self.env_group_box)

            try:
                translator_combo.currentTextChanged.disconnect(self._on_translator_changed)
            except TypeError:
                pass
            translator_combo.currentTextChanged.connect(self._on_translator_changed)
            self._on_translator_changed(translator_combo.currentText())

    def _create_dynamic_settings(self):
        """读取配置文件并动态创建所有设置控件"""
        try:
            config = self.config_service.get_config().dict() # Get default config
            self.set_parameters(config)
        except Exception as e:
            print(f"Error creating dynamic settings: {e}")

    def _on_setting_changed(self, value, full_key, display_map=None):
        """A slot to handle when any setting widget is changed by the user."""
        final_value = value
        # Handle reverse mapping for QComboBox
        if display_map:
            reverse_map = {v: k for k, v in display_map.items()}
            final_value = reverse_map.get(value, value) # Fallback to value itself if not in map
        
        # 特殊处理：当 upscaler 变化时，更新 upscale_ratio 动态下拉框
        if full_key == "upscale.upscaler":
            self._update_upscale_ratio_options(final_value)
        
        self.setting_changed.emit(full_key, final_value)

    def _on_upscale_ratio_changed(self, text, full_key):
        """处理 upscale_ratio 动态下拉框的变化"""
        config = self.config_service.get_config()
        
        if config.upscale.upscaler == "realcugan":
            # 当前是 realcugan
            if text == self._t("upscale_ratio_not_use"):
                # 禁用超分
                self.setting_changed.emit("upscale.upscale_ratio", None)
                self.setting_changed.emit("upscale.realcugan_model", None)
            else:
                # text 可能是中文显示名称，需要转换回英文值
                display_map = self.controller.get_display_mapping("realcugan_model")
                model_value = text
                
                # 如果有display_map，进行反向查找
                if display_map:
                    reverse_map = {v: k for k, v in display_map.items()}
                    model_value = reverse_map.get(text, text)
                
                # 从模型名称中提取倍率
                scale_str = model_value.split('x')[0] if 'x' in model_value else None
                if scale_str and scale_str.isdigit():
                    scale = int(scale_str)
                    # 同时更新 realcugan_model 和 upscale_ratio
                    self.setting_changed.emit("upscale.realcugan_model", model_value)
                    self.setting_changed.emit("upscale.upscale_ratio", scale)
                else:
                    # 无法解析倍率，只更新模型
                    self.setting_changed.emit("upscale.realcugan_model", model_value)
        elif config.upscale.upscaler == "mangajanai":
            # 当前是 mangajanai，直接把选项存到 upscale_ratio
            if text == self._t("upscale_ratio_not_use"):
                # 禁用超分
                self.setting_changed.emit("upscale.upscale_ratio", None)
            else:
                # 直接存储选项字符串 (x2, x4, DAT2 x4)
                self.setting_changed.emit("upscale.upscale_ratio", text)
        else:
            # 当前是其他超分模型，text 是倍率
            if text == self._t("upscale_ratio_not_use"):
                self.setting_changed.emit(full_key, None)
            else:
                try:
                    ratio = int(text)
                    self.setting_changed.emit(full_key, ratio)
                except ValueError:
                    self.setting_changed.emit(full_key, None)
    
    def _on_numeric_input_changed(self, text, full_key, value_type):
        """统一处理数值类型输入框的变化（支持 int 和 float）"""
        if not text or not text.strip():
            # 空值 = 使用默认值 (None)
            self.setting_changed.emit(full_key, None)
        else:
            try:
                value = value_type(text)
                self.setting_changed.emit(full_key, value)
            except ValueError:
                # 无效输入 = 使用默认值
                self.setting_changed.emit(full_key, None)
    
    def _update_upscale_ratio_options(self, upscaler):
        """当 upscaler 变化时，更新 upscale_ratio 下拉框的选项"""
        # 查找 upscale_ratio_dynamic widget
        upscale_ratio_widget = self.findChild(QComboBox, "upscale_ratio_dynamic")
        if not upscale_ratio_widget:
            return
        
        # 阻止信号触发
        upscale_ratio_widget.blockSignals(True)
        
        # 清空并重新填充
        upscale_ratio_widget.clear()
        
        if upscaler == "realcugan":
            # 显示 Real-CUGAN 模型列表（使用中文显示）
            realcugan_models = self.controller.get_options_for_key("realcugan_model")
            display_map = self.controller.get_display_mapping("realcugan_model")
            
            if realcugan_models:
                # 如果有display_map，使用中文名称
                if display_map:
                    display_options = [display_map.get(model, model) for model in realcugan_models]
                    all_options = [self._t("upscale_ratio_not_use")] + display_options
                else:
                    all_options = [self._t("upscale_ratio_not_use")] + realcugan_models
                
                upscale_ratio_widget.addItems(all_options)
            
            # 设置默认值
            config = self.config_service.get_config()
            if config.upscale.realcugan_model:
                # 如果有display_map，显示中文名称
                if display_map:
                    display_name = display_map.get(config.upscale.realcugan_model, config.upscale.realcugan_model)
                    upscale_ratio_widget.setCurrentText(display_name)
                else:
                    upscale_ratio_widget.setCurrentText(config.upscale.realcugan_model)
            elif config.upscale.upscale_ratio is None:
                upscale_ratio_widget.setCurrentText(self._t("upscale_ratio_not_use"))
            elif realcugan_models:
                if display_map:
                    upscale_ratio_widget.setCurrentText(display_map.get(realcugan_models[0], realcugan_models[0]))
                else:
                    upscale_ratio_widget.setCurrentText(realcugan_models[0])
        elif upscaler == "mangajanai":
            # 显示 MangaJaNai 特殊选项
            mangajanai_options = ["x2", "x4", "DAT2 x4"]
            all_options = [self._t("upscale_ratio_not_use")] + mangajanai_options
            upscale_ratio_widget.addItems(all_options)
            
            # 设置默认值 - upscale_ratio 直接存储选项字符串
            config = self.config_service.get_config()
            ratio = config.upscale.upscale_ratio
            if ratio is None:
                upscale_ratio_widget.setCurrentText(self._t("upscale_ratio_not_use"))
            elif isinstance(ratio, str) and ratio in mangajanai_options:
                upscale_ratio_widget.setCurrentText(ratio)
            elif ratio == 2:
                upscale_ratio_widget.setCurrentText("x2")
            else:
                upscale_ratio_widget.setCurrentText("x4")
        else:
            # 显示普通倍率选项
            ratio_options = [self._t("upscale_ratio_not_use"), "2", "3", "4"]
            upscale_ratio_widget.addItems(ratio_options)
            # 设置默认值
            config = self.config_service.get_config()
            if config.upscale.upscale_ratio is None:
                upscale_ratio_widget.setCurrentText(self._t("upscale_ratio_not_use"))
            else:
                upscale_ratio_widget.setCurrentText(str(config.upscale.upscale_ratio))
        
        # 恢复信号
        upscale_ratio_widget.blockSignals(False)

    def _create_param_widgets(self, data, parent_layout, prefix=""):
        if not isinstance(data, dict):
            return

        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key

            # 跳过这些选项，因为已经用下拉框替代或不需要在UI中显示
            # realcugan_model 将通过 upscale_ratio 动态下拉框处理
            # gimp_font 已废弃，使用 font_path 代替
            # translator.attempts 隐藏，始终与 cli.attempts 同步
            if full_key in ["cli.load_text", "cli.template", "cli.generate_and_export", "cli.colorize_only", "cli.upscale_only", "cli.inpaint_only", "upscale.realcugan_model", "render.gimp_font", "translator.attempts"]:
                continue

            label_text = key
            if self.controller.get_display_mapping('labels') and self.controller.get_display_mapping('labels').get(key):
                label_text = self.controller.get_display_mapping('labels').get(key)
            label = QLabel(f"{label_text}:")
            widget = None

            options = self.controller.get_options_for_key(key)
            display_map = self.controller.get_display_mapping(key)

            if full_key == "filter_text_enabled":
                # 特殊处理：过滤列表开关 + 打开过滤列表按钮
                container = QWidget()
                hbox = QHBoxLayout(container)
                hbox.setContentsMargins(0, 0, 0, 0)
                
                checkbox = QCheckBox()
                checkbox.setChecked(value)
                checkbox.stateChanged.connect(lambda state, k=full_key: self._on_setting_changed(bool(state), k, None))
                
                open_btn = QPushButton(self._t("btn_open_filter_list"))
                open_btn.clicked.connect(self._open_filter_list)
                
                hbox.addWidget(checkbox)
                hbox.addWidget(open_btn)
                hbox.addStretch()
                widget = container

            elif full_key == "render.font_path":
                container = QWidget()
                hbox = QHBoxLayout(container)
                hbox.setContentsMargins(0, 0, 0, 0)
                
                # 创建自定义ComboBox,在下拉时刷新字体列表
                class RefreshableComboBox(QComboBox):
                    def showPopup(self):
                        current_text = self.currentText()
                        self.clear()
                        try:
                            fonts_dir = resource_path('fonts')
                            if os.path.isdir(fonts_dir):
                                font_files = sorted([f for f in os.listdir(fonts_dir) if f.lower().endswith(('.ttf', '.otf', '.ttc'))])
                                self.addItems(font_files)
                        except Exception as e:
                            print(f"Error scanning fonts directory: {e}")
                        # 恢复之前选择的值
                        if current_text:
                            index = self.findText(current_text)
                            if index >= 0:
                                self.setCurrentIndex(index)
                            else:
                                self.setCurrentText(current_text)
                        super().showPopup()
                
                combo = RefreshableComboBox()
                try:
                    fonts_dir = resource_path('fonts')
                    if os.path.isdir(fonts_dir):
                        font_files = sorted([f for f in os.listdir(fonts_dir) if f.lower().endswith(('.ttf', '.otf', '.ttc'))])
                        combo.addItems(font_files)
                except Exception as e:
                    print(f"Error scanning fonts directory: {e}")
                combo.setCurrentText(str(value) if value else "")
                combo.currentTextChanged.connect(lambda text, k=full_key: self._on_setting_changed(text, k, None))
                button = QPushButton(self._t("Open Directory"))
                button.clicked.connect(self.controller.open_font_directory)
                hbox.addWidget(combo)
                hbox.addWidget(button)
                widget = container

            elif full_key == "translator.high_quality_prompt_path":
                container = QWidget()
                hbox = QHBoxLayout(container)
                hbox.setContentsMargins(0, 0, 0, 0)
                
                # 创建自定义ComboBox,在下拉时刷新提示词列表
                class RefreshablePromptComboBox(QComboBox):
                    def __init__(self, controller_ref, parent=None):
                        super().__init__(parent)
                        self.controller_ref = controller_ref
                    
                    def showPopup(self):
                        current_text = self.currentText()
                        self.clear()
                        prompt_files = self.controller_ref.get_hq_prompt_options()
                        if prompt_files:
                            self.addItems(prompt_files)
                        # 恢复之前选择的值
                        if current_text:
                            index = self.findText(current_text)
                            if index >= 0:
                                self.setCurrentIndex(index)
                            else:
                                self.setCurrentText(current_text)
                        super().showPopup()
                
                combo = RefreshablePromptComboBox(self.controller)
                prompt_files = self.controller.get_hq_prompt_options()
                if prompt_files:
                    combo.addItems(prompt_files)
                filename = os.path.basename(value) if value else ""
                combo.setCurrentText(filename)
                combo.currentTextChanged.connect(lambda text, k=full_key: self._on_setting_changed(os.path.join('dict', text).replace('\\', '/') if text else None, k, None))
                button = QPushButton(self._t("Open Directory"))
                button.clicked.connect(self.controller.open_dict_directory)
                hbox.addWidget(combo)
                hbox.addWidget(button)
                widget = container

            elif isinstance(value, bool):
                widget = QCheckBox()
                widget.setChecked(value)
                widget.stateChanged.connect(lambda state, k=full_key: self._on_setting_changed(bool(state), k, None))

            # 特殊处理：upscale_ratio 动态下拉框（必须在 int/float 判断之前）
            elif full_key == "upscale.upscale_ratio":
                widget = QComboBox()
                widget.setObjectName("upscale_ratio_dynamic")
                
                # 获取当前的 upscaler 值来决定显示什么选项
                config = self.config_service.get_config()
                current_upscaler = config.upscale.upscaler
                
                if current_upscaler == "realcugan":
                    # 显示 Real-CUGAN 模型列表（使用中文显示）
                    realcugan_models = self.controller.get_options_for_key("realcugan_model")
                    display_map = self.controller.get_display_mapping("realcugan_model")
                    
                    if realcugan_models:
                        # 如果有display_map，使用中文名称
                        if display_map:
                            display_options = [display_map.get(model, model) for model in realcugan_models]
                            all_options = [self._t("upscale_ratio_not_use")] + display_options
                        else:
                            all_options = [self._t("upscale_ratio_not_use")] + realcugan_models
                        widget.addItems(all_options)
                    
                    # 设置当前值（从 realcugan_model 获取）
                    current_model = config.upscale.realcugan_model
                    if current_model:
                        # 如果有display_map，显示中文名称
                        if display_map:
                            display_name = display_map.get(current_model, current_model)
                            widget.setCurrentText(display_name)
                        else:
                            widget.setCurrentText(current_model)
                    elif value is None:
                        widget.setCurrentText(self._t("upscale_ratio_not_use"))
                    elif realcugan_models:
                        widget.setCurrentText(realcugan_models[0])
                elif current_upscaler == "mangajanai":
                    # 显示 MangaJaNai 特殊选项
                    mangajanai_options = ["x2", "x4", "DAT2 x4"]
                    all_options = [self._t("upscale_ratio_not_use")] + mangajanai_options
                    widget.addItems(all_options)
                    
                    # 设置当前值 - upscale_ratio 直接存储选项字符串
                    if value is None:
                        widget.setCurrentText(self._t("upscale_ratio_not_use"))
                    elif isinstance(value, str) and value in mangajanai_options:
                        widget.setCurrentText(value)
                    elif value == 2:
                        widget.setCurrentText("x2")
                    else:
                        widget.setCurrentText("x4")
                else:
                    # 显示普通倍率选项
                    ratio_options = [self._t("upscale_ratio_not_use"), "2", "3", "4"]
                    widget.addItems(ratio_options)
                    # 设置当前值
                    if value is None:
                        widget.setCurrentText(self._t("upscale_ratio_not_use"))
                    else:
                        widget.setCurrentText(str(value))
                
                widget.currentTextChanged.connect(lambda text, k=full_key: self._on_upscale_ratio_changed(text, k))
            
            elif isinstance(value, (int, float)):
                widget = QLineEdit(str(value))
                widget.editingFinished.connect(lambda k=full_key, w=widget: self._on_numeric_input_changed(w.text(), k, float if isinstance(value, float) else int))

            elif value is None and key in ['tile_size', 'line_spacing', 'font_size']:
                # 处理值为 None 的数值类型参数（Optional[int] 或 Optional[float]）
                widget = QLineEdit("")
                # 根据参数名设置提示文本
                if key == 'tile_size':
                    widget.setPlaceholderText(self._t("Default: 400"))
                    widget.editingFinished.connect(lambda k=full_key, w=widget: self._on_numeric_input_changed(w.text(), k, int))
                elif key == 'line_spacing':
                    widget.setPlaceholderText(self._t("Horizontal default: 0.01, Vertical default: 0.2"))
                    widget.editingFinished.connect(lambda k=full_key, w=widget: self._on_numeric_input_changed(w.text(), k, float))
                elif key == 'font_size':
                    widget.setPlaceholderText(self._t("Auto"))
                    widget.editingFinished.connect(lambda k=full_key, w=widget: self._on_numeric_input_changed(w.text(), k, int))

            elif (isinstance(value, str) or value is None) and (options or display_map):
                widget = QComboBox()
                if key == "translator":
                    widget.setObjectName("translator.translator")
                    widget.setMinimumWidth(180)  # 设置翻译器下拉框最小宽度
                
                if display_map:
                    widget.addItems(list(display_map.values()))
                    current_display_name = display_map.get(value) if value is not None else None
                    if current_display_name:
                        widget.setCurrentText(current_display_name)
                    widget.currentTextChanged.connect(lambda text, k=full_key, dm=display_map: self._on_setting_changed(text, k, dm))
                else:
                    widget.addItems(options)
                    if value is not None:
                        widget.setCurrentText(value)
                    else:
                        # 对于 None 值，设置第一个选项为默认值（通常是 "不使用"）
                        if options:
                            widget.setCurrentText(options[0])
                    widget.currentTextChanged.connect(lambda text, k=full_key: self._on_setting_changed(text, k, None))

            elif isinstance(value, str):
                widget = QLineEdit(value)
                widget.editingFinished.connect(lambda k=full_key, w=widget: self._on_setting_changed(w.text(), k, None))
            
            if widget:
                parent_layout.addRow(label, widget)


    def _create_left_panel(self) -> QWidget:
        left_panel = QWidget()
        # 不设置任何宽度限制，完全自由调整
        left_layout = QVBoxLayout(left_panel)

        # 文件操作按钮
        file_button_widget = QWidget()
        file_buttons_layout = QHBoxLayout(file_button_widget)
        file_buttons_layout.setContentsMargins(0,0,0,0)
        self.add_files_button = QPushButton(self._t("Add Files"))
        self.add_folder_button = QPushButton(self._t("Add Folder"))
        self.clear_list_button = QPushButton(self._t("Clear List"))
        file_buttons_layout.addWidget(self.add_files_button)
        file_buttons_layout.addWidget(self.add_folder_button)
        file_buttons_layout.addWidget(self.clear_list_button)
        left_layout.addWidget(file_button_widget)

        # 文件列表
        self.file_list = FileListView(None, self) # Pass None for model initially
        left_layout.addWidget(self.file_list)

        # --- Output Folder ---
        self.output_folder_label = QLabel(self._t("Output Directory:"))
        left_layout.addWidget(self.output_folder_label)

        output_folder_widget = QWidget()
        output_folder_layout = QHBoxLayout(output_folder_widget)
        output_folder_layout.setContentsMargins(0,0,0,0)
        self.output_folder_input = QLineEdit()
        self.output_folder_input.setPlaceholderText(self._t("Select or drag output folder..."))
        self.browse_button = QPushButton(self._t("Browse..."))
        self.open_button = QPushButton(self._t("Open"))
        output_folder_layout.addWidget(self.output_folder_input)
        output_folder_layout.addWidget(self.browse_button)
        output_folder_layout.addWidget(self.open_button)
        left_layout.addWidget(output_folder_widget)

        # 翻译流程模式选择（放在开始翻译按钮上面）
        self.workflow_mode_label = QLabel(self._t("Translation Workflow Mode:"))
        left_layout.addWidget(self.workflow_mode_label)

        from PyQt6.QtWidgets import QComboBox
        self.workflow_mode_combo = QComboBox()
        self.workflow_mode_combo.addItems([
            self._t("Normal Translation"),
            self._t("Export Translation"),
            self._t("Export Original Text"),
            self._t("Import Translation and Render"),
            self._t("Colorize Only"),
            self._t("Upscale Only"),
            self._t("Inpaint Only")
        ])
        self.workflow_mode_combo.currentIndexChanged.connect(self._on_workflow_mode_changed)
        left_layout.addWidget(self.workflow_mode_combo)

        self.start_button = QPushButton(self._t("Start Translation"))
        self.start_button.setFixedHeight(40)
        left_layout.addWidget(self.start_button)
         # 配置导入导出按钮
        config_io_widget = QWidget()
        config_io_layout = QHBoxLayout(config_io_widget)
        config_io_layout.setContentsMargins(0,0,0,0)
        self.export_config_button = QPushButton(self._t("Export Config"))
        self.import_config_button = QPushButton(self._t("Import Config"))
        config_io_layout.addWidget(self.export_config_button)
        config_io_layout.addWidget(self.import_config_button)
        left_layout.addWidget(config_io_widget)
        # Connect all signals at the end, after all widgets are created
        self.add_files_button.clicked.connect(self._trigger_add_files)
        self.add_folder_button.clicked.connect(self.controller.add_folder)
        self.clear_list_button.clicked.connect(self.controller.clear_file_list)
        self.file_list.file_remove_requested.connect(self.controller.remove_file)
        self.browse_button.clicked.connect(self.controller.select_output_folder)
        self.open_button.clicked.connect(self.controller.open_output_folder)
        self.start_button.clicked.connect(self.controller.start_backend_task)
        self.export_config_button.clicked.connect(self.controller.export_config)
        self.import_config_button.clicked.connect(self.controller.import_config)
        return left_panel

    def _create_right_panel(self) -> QWidget:
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # 右侧的上下分割器 (设置 vs 日志)
        right_splitter = QSplitter(Qt.Orientation.Vertical)
        right_layout.addWidget(right_splitter)

        # 设置标签页
        self.settings_tabs = QTabWidget()
        right_splitter.addWidget(self.settings_tabs)

        # --- 动态创建标签页和其内部布局 ---
        self.tab_frames = {}
        # 使用固定的英文键名，避免语言切换时键名不匹配
        tabs_config = [
            ("Basic Settings", self._t("Basic Settings")),
            ("Advanced Settings", self._t("Advanced Settings")),
            ("Options", self._t("Options"))
        ]
        for tab_key, tab_display_name in tabs_config:
            tab_content_widget = QWidget()
            tab_layout = QHBoxLayout(tab_content_widget)
            tab_layout.setContentsMargins(0,0,0,0)
            
            tab_splitter = QSplitter(Qt.Orientation.Horizontal)
            tab_layout.addWidget(tab_splitter)

            # 每一页都有一左一右两个滚动区域
            left_scroll = QScrollArea()
            left_scroll.setWidgetResizable(True)
            right_scroll = QScrollArea()
            right_scroll.setWidgetResizable(True)

            # 用一个空的QWidget作为滚动区域的内容，后续动态添加控件
            left_scroll_content = QWidget()
            right_scroll_content = QWidget()
            left_scroll.setWidget(left_scroll_content)
            right_scroll.setWidget(right_scroll_content)

            # 给滚动区域的内容设置布局，以便添加控件
            left_form = QFormLayout(left_scroll_content)
            left_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            left_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            left_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # 标签左对齐，消除空白
            left_form.setHorizontalSpacing(10)
            left_form.setVerticalSpacing(8)
            
            right_form = QFormLayout(right_scroll_content)
            right_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
            right_form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            right_form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)  # 标签左对齐，消除空白
            right_form.setHorizontalSpacing(10)
            right_form.setVerticalSpacing(8)

            tab_splitter.addWidget(left_scroll)
            tab_splitter.addWidget(right_scroll)

            self.settings_tabs.addTab(tab_content_widget, tab_display_name)
            
            # 使用固定的英文键名保存引用
            self.tab_frames[f"{tab_key}_left"] = left_scroll_content
            self.tab_frames[f"{tab_key}_right"] = right_scroll_content

        # 日志框和进度条容器
        log_container = QWidget()
        log_container_layout = QVBoxLayout(log_container)
        log_container_layout.setContentsMargins(0, 0, 0, 0)
        log_container_layout.setSpacing(5)
        
        # 日志框（使用QPlainTextEdit性能更好）
        from PyQt6.QtWidgets import QPlainTextEdit
        self.log_box = QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText(self._t("Log output..."))
        self.log_box.setMaximumBlockCount(5000)  # 限制最大行数，防止内存问题
        log_container_layout.addWidget(self.log_box)
        
        # 进度条（常态显示）
        from PyQt6.QtWidgets import QProgressBar
        self.progress_bar = QProgressBar()
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("0/0 (0%)")
        self.progress_bar.setFixedHeight(25)
        # 设置样式：默认灰色，翻译时蓝色
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 3px;
                text-align: center;
                background-color: #f0f0f0;
            }
            QProgressBar::chunk {
                background-color: #d0d0d0;
            }
        """)
        log_container_layout.addWidget(self.progress_bar)
        
        right_splitter.addWidget(log_container)

        right_splitter.setStretchFactor(0, 2) # 让设置面板占据更多空间
        right_splitter.setStretchFactor(1, 1) # 日志输出占据较少空间
        right_splitter.setSizes([400, 400]) # 设置初始高度：设置面板400px，日志输出400px

        return right_panel

    def append_log(self, message):
        """安全地将消息追加到日志框（带批量更新优化）。"""
        # 初始化日志缓冲区
        if not hasattr(self, '_log_buffer'):
            self._log_buffer = []
            self._log_timer = None
        
        # 限制缓冲区大小，避免日志过多导致卡顿
        if len(self._log_buffer) >= 200:
            self._flush_log_buffer()
        
        self._log_buffer.append(message.strip())
        
        # 如果定时器未启动，启动50ms后批量更新
        if self._log_timer is None:
            from PyQt6.QtCore import QTimer
            self._log_timer = QTimer()
            self._log_timer.setSingleShot(True)
            self._log_timer.timeout.connect(self._flush_log_buffer)
            self._log_timer.start(50)  # 50ms批量更新一次
    
    def _flush_log_buffer(self):
        """批量刷新日志缓冲区"""
        if not hasattr(self, '_log_buffer') or not self._log_buffer:
            self._log_timer = None
            return
        
        # 检查是否已经在底部
        scrollbar = self.log_box.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 10
        
        # 批量追加所有日志
        self.log_box.appendPlainText('\n'.join(self._log_buffer))
        self._log_buffer.clear()
        self._log_timer = None
        
        # 限制日志框的最大行数，避免过多日志导致卡顿
        max_lines = 5000
        current_lines = self.log_box.document().blockCount()
        if current_lines > max_lines:
            cursor = self.log_box.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            # 删除超出部分的行数
            lines_to_remove = current_lines - max_lines
            for _ in range(lines_to_remove):
                cursor.select(cursor.SelectionType.BlockUnderCursor)
                cursor.removeSelectedText()
                cursor.deleteChar()  # 删除换行符
        
        # 只有之前在底部时才自动滚动到底部
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())
    
    def update_progress(self, current: int, total: int, message: str = ""):
        """更新进度条
        
        Args:
            current: 当前进度值
            total: 总进度值
            message: 可选的进度消息
        """
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(current)
            percentage = int((current / total) * 100) if total > 0 else 0
            self.progress_bar.setFormat(f"{current}/{total} ({percentage}%)")
            
            # 翻译中：蓝色进度条（只在首次进入翻译状态时设置样式）
            if current > 0 and not getattr(self, '_progress_active', False):
                self._progress_active = True
                self.progress_bar.setStyleSheet("""
                    QProgressBar {
                        border: 1px solid #0078d4;
                        border-radius: 3px;
                        text-align: center;
                        background-color: #f0f0f0;
                    }
                    QProgressBar::chunk {
                        background-color: #0078d4;
                    }
                """)
        else:
            # 重置为灰色
            self._progress_active = False
            self.progress_bar.setMaximum(100)
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0/0 (0%)")
            self.progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #ccc;
                    border-radius: 3px;
                    text-align: center;
                    background-color: #f0f0f0;
                }
                QProgressBar::chunk {
                    background-color: #d0d0d0;
                }
            """)
    
    def reset_progress(self):
        """重置进度条为初始状态（灰色）"""
        self._progress_active = False  # 重置标志，确保下次翻译能正确显示蓝色
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0/0 (0%)")
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 3px;
                text-align: center;
                background-color: #f0f0f0;
            }
            QProgressBar::chunk {
                background-color: #d0d0d0;
            }
        """)
    
    def refresh_tab_titles(self):
        """刷新标签页标题（用于语言切换）"""
        tab_titles = ["Basic Settings", "Advanced Settings", "Options"]
        for i, title_key in enumerate(tab_titles):
            if i < self.settings_tabs.count():
                self.settings_tabs.setTabText(i, self._t(title_key))
    
    def refresh_ui_texts(self):
        """刷新所有UI文本（用于语言切换）"""
        # 刷新标签页标题
        self.refresh_tab_titles()
        
        # 刷新左侧文件管理按钮
        if hasattr(self, 'add_files_button'):
            self.add_files_button.setText(self._t("Add Files"))
        if hasattr(self, 'add_folder_button'):
            self.add_folder_button.setText(self._t("Add Folder"))
        if hasattr(self, 'clear_list_button'):
            self.clear_list_button.setText(self._t("Clear List"))
        
        # 刷新输出目录标签
        if hasattr(self, 'output_folder_label'):
            self.output_folder_label.setText(self._t("Output Directory:"))
        if hasattr(self, 'output_folder_input'):
            self.output_folder_input.setPlaceholderText(self._t("Select or drag output folder..."))
        if hasattr(self, 'browse_button'):
            self.browse_button.setText(self._t("Browse..."))
        if hasattr(self, 'open_button'):
            self.open_button.setText(self._t("Open"))
        
        # 刷新翻译流程模式标签和下拉菜单
        if hasattr(self, 'workflow_mode_label'):
            self.workflow_mode_label.setText(self._t("Translation Workflow Mode:"))
        if hasattr(self, 'workflow_mode_combo'):
            current_index = self.workflow_mode_combo.currentIndex()
            self.workflow_mode_combo.blockSignals(True)
            self.workflow_mode_combo.clear()
            self.workflow_mode_combo.addItems([
                self._t("Normal Translation"),
                self._t("Export Translation"),
                self._t("Export Original Text"),
                self._t("Import Translation and Render"),
                self._t("Colorize Only"),
                self._t("Upscale Only"),
                self._t("Inpaint Only")
            ])
            self.workflow_mode_combo.setCurrentIndex(current_index)
            self.workflow_mode_combo.blockSignals(False)
        
        # 刷新开始按钮
        self.update_start_button_text()
        
        # 刷新配置导入导出按钮
        if hasattr(self, 'export_config_button'):
            self.export_config_button.setText(self._t("Export Config"))
        if hasattr(self, 'import_config_button'):
            self.import_config_button.setText(self._t("Import Config"))
        
        # 刷新日志框占位符
        if hasattr(self, 'log_box'):
            self.log_box.setPlaceholderText(self._t("Log output..."))
        
        # 刷新文件列表视图（强制重绘以更新拖拽提示文本）
        if hasattr(self, 'file_list') and hasattr(self.file_list, 'refresh_ui_texts'):
            self.file_list.refresh_ui_texts()
        
        # 刷新 API Keys 分组框标题
        if hasattr(self, 'env_group_box') and self.env_group_box is not None:
            try:
                self.env_group_box.setTitle(self._t("API Keys (.env)"))
            except RuntimeError:
                pass
        
        # 清理并重新创建动态设置以更新所有标签
        self._clear_dynamic_settings()
        self._create_dynamic_settings()
    
    def _clear_dynamic_settings(self):
        """清理所有动态创建的设置控件"""
        # 清理 env_group_box
        if hasattr(self, 'env_group_box'):
            self.env_group_box = None
        
        # 清理所有面板中的控件
        for panel in self.tab_frames.values():
            if panel and panel.layout():
                layout = panel.layout()
                # 清空布局中的所有控件
                while layout.count():
                    item = layout.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()

    def _on_translator_changed(self, display_name: str):
        """当翻译器下拉菜单变化时，动态更新所需的.env输入字段"""
        translator_key = self.controller.get_display_mapping('translator').get(display_name, display_name.lower())
        reverse_map = {v: k for k, v in self.controller.get_display_mapping('translator').items()}
        translator_key = reverse_map.get(display_name, display_name.lower())

        # Clear previous env widgets
        from PyQt6.QtWidgets import QGridLayout
        if isinstance(self.env_layout, QGridLayout):
            # GridLayout 清除方式
            while self.env_layout.count():
                item = self.env_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        else:
            # FormLayout 清除方式
            while self.env_layout.rowCount() > 0:
                self.env_layout.removeRow(0)
        self.env_widgets.clear()

        if not translator_key:
            self.env_group_box.setVisible(False)
            return

        all_vars = self.config_service.get_all_env_vars(translator_key)
        if not all_vars:
            self.env_group_box.setVisible(False)
            return
            
        self.env_group_box.setVisible(True)
        current_env_values = self.config_service.load_env_vars()
        self._create_env_widgets(all_vars, current_env_values)

    def _create_env_widgets(self, keys: list, current_values: dict):
        """为给定的键创建标签和输入框"""
        from PyQt6.QtWidgets import QGridLayout
        row = 0
        for key in keys:
            value = current_values.get(key, "")
            label_text = self.controller.get_display_mapping('labels').get(key, key)
            label = QLabel(f"{label_text}:")
            widget = QLineEdit(value)
            widget.textChanged.connect(partial(self._debounced_save_env_var, key))
            # 使用 GridLayout 的 addWidget 而不是 FormLayout 的 addRow
            if isinstance(self.env_layout, QGridLayout):
                self.env_layout.addWidget(label, row, 0, Qt.AlignmentFlag.AlignLeft)
                self.env_layout.addWidget(widget, row, 1)
                row += 1
            else:
                self.env_layout.addRow(label, widget)
            self.env_widgets[key] = (label, widget)

    def _debounced_save_env_var(self, key: str, text: str):
        """防抖保存.env变量"""
        self._env_debounce_timer.stop()
        try:
            self._env_debounce_timer.timeout.disconnect()
        except TypeError:
            pass  # No connection to disconnect, which is fine.
        self._env_debounce_timer.timeout.connect(lambda: self.env_var_changed.emit(key, text))
        self._env_debounce_timer.start()

    def _refresh_preset_list(self):
        """刷新预设列表"""
        if not hasattr(self, 'preset_combo'):
            return
        
        current_text = self.preset_combo.currentText()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        
        presets = self.controller.get_presets_list()
        if presets:
            self.preset_combo.addItems(presets)
            # 恢复之前选择的预设
            if current_text and current_text in presets:
                self.preset_combo.setCurrentText(current_text)
        
        self.preset_combo.blockSignals(False)

    def _on_add_preset_clicked(self):
        """添加新预设"""
        from PyQt6.QtWidgets import QInputDialog, QMessageBox
        
        preset_name, ok = QInputDialog.getText(
            self,
            self._t("Add Preset"),
            self._t("Enter preset name:")
        )
        
        if ok and preset_name:
            preset_name = preset_name.strip()
            if not preset_name:
                QMessageBox.warning(
                    self,
                    self._t("Warning"),
                    self._t("Preset name cannot be empty")
                )
                return
            
            # 检查预设是否已存在
            existing_presets = self.controller.get_presets_list()
            if preset_name in existing_presets:
                reply = QMessageBox.question(
                    self,
                    self._t("Confirm"),
                    self._t("Preset '{name}' already exists. Overwrite?", name=preset_name),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            
            # 保存当前.env配置为预设
            success = self.controller.save_preset(preset_name)
            if success:
                self._refresh_preset_list()
                self.preset_combo.setCurrentText(preset_name)
                QMessageBox.information(
                    self,
                    self._t("Success"),
                    self._t("Preset saved successfully")
                )
            else:
                QMessageBox.critical(
                    self,
                    self._t("Error"),
                    self._t("Failed to save preset")
                )

    def _on_delete_preset_clicked(self):
        """删除选中的预设"""
        from PyQt6.QtWidgets import QMessageBox
        
        preset_name = self.preset_combo.currentText()
        if not preset_name:
            QMessageBox.warning(
                self,
                self._t("Warning"),
                self._t("Please select a preset to delete")
            )
            return
        
        reply = QMessageBox.question(
            self,
            self._t("Confirm"),
            self._t("Are you sure you want to delete preset '{name}'?", name=preset_name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            success = self.controller.delete_preset(preset_name)
            if success:
                self._refresh_preset_list()
                QMessageBox.information(
                    self,
                    self._t("Success"),
                    self._t("Preset deleted successfully")
                )
            else:
                QMessageBox.critical(
                    self,
                    self._t("Error"),
                    self._t("Failed to delete preset")
                )

    def _on_preset_changed(self, new_preset_name: str):
        """切换预设时自动保存当前预设并加载新预设"""
        if not new_preset_name:
            return
        
        # 获取当前预设名称
        old_preset_name = getattr(self, '_current_preset_name', '')
        
        # 如果有旧预设，先保存当前环境变量到旧预设
        if old_preset_name and old_preset_name != new_preset_name:
            self.controller.save_preset(old_preset_name)
        
        # 加载新预设
        success = self.controller.load_preset(new_preset_name)
        if success:
            # 更新当前预设名称
            self._current_preset_name = new_preset_name
            # 保存当前预设到配置文件（持久化）
            self.controller.config_service.set_current_preset(new_preset_name)
            # 重新加载当前翻译器的环境变量显示
            translator_combo = self.findChild(QComboBox, "translator.translator")
            if translator_combo:
                self._on_translator_changed(translator_combo.currentText())

    def update_output_path_display(self, path: str):
        """Slot to update the text of the output folder input field."""
        self.output_folder_input.setText(path)

    def _trigger_add_files(self):
        """触发添加文件对话框"""
        last_dir = self.controller.get_last_open_dir()
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, 
            self._t("Add Files"), 
            last_dir, 
            "All Supported Files (*.png *.jpg *.jpeg *.bmp *.webp *.avif *.pdf *.epub *.cbz *.cbr *.zip);;"
            "Image Files (*.png *.jpg *.jpeg *.bmp *.webp *.avif);;"
            "PDF Files (*.pdf);;"
            "EPUB Files (*.epub);;"
            "Comic Book Archives (*.cbz *.cbr *.zip)"
        )
        if file_paths:
            self.controller.add_files(file_paths)
            # Save the directory of the first selected file for next time
            new_dir = os.path.dirname(file_paths[0])
            self.controller.set_last_open_dir(new_dir)

    def closeEvent(self, event):
        """处理窗口关闭事件"""
        self.app_logic.shutdown()
        event.accept()

    @pyqtSlot(bool)
    def on_translation_state_changed(self, is_translating: bool):
        """Handles the change of the translation state to update the start/stop button."""
        if is_translating:
            # 禁用按钮2秒，防止快速重复点击导致线程冲突
            self.start_button.setEnabled(False)
            self.start_button.setText(self._t("Starting..."))
            QTimer.singleShot(2000, self._enable_stop_button)
        else:
            self.start_button.setEnabled(True)
            self.start_button.setStyleSheet("")
            self.start_button.style().unpolish(self.start_button)
            self.start_button.style().polish(self.start_button)
            self.start_button.update()
            
            try:
                self.start_button.clicked.disconnect()
            except TypeError:
                pass
            self.start_button.clicked.connect(self.controller.start_backend_task)
            self.update_start_button_text()
    
    def _enable_stop_button(self):
        """启用停止按钮（延迟调用）"""
        if self.controller.state_manager.is_translating():
            self.start_button.setEnabled(True)
            self.start_button.setText(self._t("Stop Translation"))
            self.start_button.setStyleSheet("background-color: #C53929; color: white;")
            try:
                self.start_button.clicked.disconnect()
            except TypeError:
                pass
            self.start_button.clicked.connect(self.controller.stop_task)

    def set_stopping_state(self):
        """设置按钮为"停止中..."状态，禁用按钮防止重复点击"""
        self.start_button.setEnabled(False)
        self.start_button.setText(self._t("Stopping..."))
        self.start_button.setStyleSheet("background-color: #888888; color: white;")
        try:
            self.start_button.clicked.disconnect()
        except TypeError:
            pass

    def _sync_workflow_mode_from_config(self):
        """从配置同步下拉框的选择"""
        try:
            config = self.config_service.get_config()

            # 阻止信号触发，避免循环
            self.workflow_mode_combo.blockSignals(True)

            if config.cli.inpaint_only:
                self.workflow_mode_combo.setCurrentIndex(6)  # 仅输出修复图片
            elif config.cli.upscale_only:
                self.workflow_mode_combo.setCurrentIndex(5)  # 仅超分
            elif config.cli.colorize_only:
                self.workflow_mode_combo.setCurrentIndex(4)  # 仅上色
            elif config.cli.load_text:
                self.workflow_mode_combo.setCurrentIndex(3)  # 导入翻译并渲染
            elif config.cli.template:
                self.workflow_mode_combo.setCurrentIndex(2)  # 导出原文
            elif config.cli.generate_and_export:
                self.workflow_mode_combo.setCurrentIndex(1)  # 导出翻译
            else:
                self.workflow_mode_combo.setCurrentIndex(0)  # 正常翻译流程

            self.workflow_mode_combo.blockSignals(False)
        except Exception as e:
            print(f"Error syncing workflow mode: {e}")

    def _on_workflow_mode_changed(self, index: int):
        """处理翻译流程模式改变"""
        # 根据下拉框选择更新配置
        # 0: 正常翻译流程
        # 1: 导出翻译
        # 2: 导出原文
        # 3: 导入翻译并渲染
        # 4: 仅上色
        # 5: 仅超分

        config = self.config_service.get_config()

        # 重置所有选项
        config.cli.load_text = False
        config.cli.template = False
        config.cli.generate_and_export = False
        config.cli.colorize_only = False
        config.cli.upscale_only = False
        config.cli.inpaint_only = False

        if index == 1:  # 导出翻译
            config.cli.generate_and_export = True
        elif index == 2:  # 导出原文
            config.cli.template = True
        elif index == 3:  # 导入翻译并渲染
            config.cli.load_text = True
        elif index == 4:  # 仅上色
            config.cli.colorize_only = True
        elif index == 5:  # 仅超分
            config.cli.upscale_only = True
        elif index == 6:  # 仅输出修复图片
            config.cli.inpaint_only = True

        # ✅ 保存配置到内存和文件
        self.config_service.set_config(config)
        self.config_service.save_config_file()

        # 立即更新按钮文字
        self.update_start_button_text()

    def update_start_button_text(self):
        """Updates the start button text based on the current configuration."""
        if self.controller.state_manager.is_translating():
            return  # Don't change text while a task is running

        try:
            config = self.config_service.get_config()
            if config.cli.inpaint_only:
                self.start_button.setText(self._t("Start Inpainting"))
            elif config.cli.upscale_only:
                self.start_button.setText(self._t("Start Upscaling"))
            elif config.cli.colorize_only:
                self.start_button.setText(self._t("Start Colorizing"))
            elif config.cli.load_text:
                self.start_button.setText(self._t("Import Translation and Render"))
            elif config.cli.template:
                self.start_button.setText(self._t("Generate Original Text Template"))
            elif config.cli.generate_and_export:
                self.start_button.setText(self._t("Export Translation"))
            else:
                self.start_button.setText(self._t("Start Translation"))
        except Exception as e:
            # Fallback in case config is not ready
            self.start_button.setText(self._t("Start Translation"))
            print(f"Could not update button text: {e}")


