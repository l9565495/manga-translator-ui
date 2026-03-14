import os
import textwrap
from functools import partial

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QLabel, QLineEdit

from widgets.themed_message_box import show_error_dialog

from utils.wheel_filter import NoWheelComboBox as QComboBox


def on_translator_changed(self, display_name: str):
    """当翻译器下拉菜单变化时，动态更新所需的.env输入字段。"""
    if not hasattr(self, "env_layout") or not hasattr(self, "env_group_box") or self.env_group_box is None:
        return

    reverse_map = {v: k for k, v in self.controller.get_display_mapping("translator").items()}
    translator_key = reverse_map.get(display_name, display_name.lower())

    from PyQt6.QtWidgets import QGridLayout

    if isinstance(self.env_layout, QGridLayout):
        while self.env_layout.count():
            item = self.env_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
    else:
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


def create_env_widgets(self, keys: list, current_values: dict):
    """为给定的键创建标签和输入框。"""
    from PyQt6.QtWidgets import QGridLayout, QPushButton

    row = 0
    for key in keys:
        value = current_values.get(key, "")
        
        display_key = key
        for prefix in ["OCR_", "COLOR_", "RENDER_"]:
            if key.startswith(prefix):
                display_key = key[len(prefix):]
                break
                
        label_text = self.controller.get_display_mapping("labels").get(display_key, display_key)
        label = QLabel(f"{label_text}:")
        widget = QLineEdit(str(value) if value else "")
        widget.setPlaceholderText(self._get_env_default_placeholder(key))
        widget.textChanged.connect(partial(self._debounced_save_env_var, key))

        if isinstance(self.env_layout, QGridLayout):
            self.env_layout.addWidget(label, row, 0, Qt.AlignmentFlag.AlignLeft)
            self.env_layout.addWidget(widget, row, 1)

            if "API_KEY" in key or "AUTH_KEY" in key or "TOKEN" in key:
                test_button = QPushButton(self._t("Test"))
                test_button.setFixedWidth(60)
                test_button.clicked.connect(partial(self._on_test_api_clicked, key))
                self.env_layout.addWidget(test_button, row, 2)
            elif "MODEL" in key:
                get_models_button = QPushButton(self._t("Get Models"))
                get_models_button.setFixedWidth(100)
                get_models_button.clicked.connect(partial(self._on_get_models_clicked, key))
                self.env_layout.addWidget(get_models_button, row, 2)

            row += 1
        else:
            self.env_layout.addRow(label, widget)
        self.env_widgets[key] = (label, widget)


def get_env_default_placeholder(self, key: str) -> str:
    """返回环境变量输入框应显示的默认占位符。"""
    key_placeholder = self._t("placeholder_paste_key")
    token_placeholder = self._t("placeholder_paste_token")
    normalized_key = key.upper()
    for prefix in ("OCR_", "COLOR_", "RENDER_"):
        if normalized_key.startswith(prefix):
            normalized_key = normalized_key[len(prefix):]
            break

    default_placeholders = {
        "OPENAI_API_BASE": "https://api.openai.com/v1",
        "CUSTOM_OPENAI_API_BASE": "https://api.openai.com/v1",
        "GEMINI_API_BASE": "https://generativelanguage.googleapis.com",
        "SAKURA_API_BASE": "http://127.0.0.1:8080/v1",
        "OPENAI_MODEL": "gpt-4o",
        "CUSTOM_OPENAI_MODEL": "qwen2.5:7b",
        "GEMINI_MODEL": "gemini-1.5-flash-002",
        "GROQ_MODEL": "mixtral-8x7b-32768",
        "DEEPSEEK_MODEL": "deepseek-chat",
        "OPENAI_API_KEY": key_placeholder,
        "CUSTOM_OPENAI_API_KEY": key_placeholder,
        "GEMINI_API_KEY": key_placeholder,
        "GROQ_API_KEY": key_placeholder,
        "DEEPSEEK_API_KEY": key_placeholder,
        "DEEPL_AUTH_KEY": key_placeholder,
        "CAIYUN_TOKEN": token_placeholder,
    }
    return default_placeholders.get(normalized_key, "")


def debounced_save_env_var(self, key: str, text: str):
    """防抖保存.env变量。"""
    self._env_debounce_timer.stop()
    try:
        self._env_debounce_timer.timeout.disconnect()
    except TypeError:
        pass
    self._env_debounce_timer.timeout.connect(lambda: self.env_var_changed.emit(key, text))
    self._env_debounce_timer.start()


def _detect_current_api_type(env_key: str, translator_key: str) -> str:
    _, provider, _ = _split_env_key(env_key)
    if provider == "GEMINI":
        return "gemini"
    if provider:
        return "openai"

    normalized_translator_key = (translator_key or "").lower()
    if "gemini" in normalized_translator_key:
        return "gemini"
    return "openai"


def _get_api_address_example(api_type: str) -> str:
    if api_type == "gemini":
        return "https://generativelanguage.googleapis.com"
    return "https://api.openai.com/v1"


def _wrap_error_text(message: str, width: int = 60) -> str:
    wrapped_lines: list[str] = []
    for line in str(message or "").splitlines():
        if not line:
            wrapped_lines.append("")
            continue
        wrapped_lines.extend(
            textwrap.wrap(
                line,
                width=width,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )
    return "\n".join(wrapped_lines)


def _format_test_connection_error(api_type: str, message: str) -> str:
    raw_message = str(message or "").strip()
    error_lower = raw_message.lower()

    network_keywords = (
        "connection",
        "cannot connect to host",
        "connection refused",
        "connection reset",
        "network",
        "timeout",
        "timed out",
        "dns",
        "host",
        "hostname",
        "getaddrinfo",
        "name or service not known",
        "no address associated with hostname",
        "nodename nor servname provided",
        "failed to resolve",
        "temporary failure in name resolution",
        "远程主机",
        "连接",
        "超时",
        "网络",
        "主机",
    )

    is_network_error = any(keyword in error_lower for keyword in network_keywords)

    if is_network_error:
        friendly_message = (
            "检测到连接错误、超时或 Host 解析错误。\n"
            "请检查网络连接，并尝试开启 TUN（虚拟网卡模式）。"
        )
    else:
        friendly_message = "请检查 API 密钥和地址。"

    friendly_message += f"\n\nAPI 地址示例：{_get_api_address_example(api_type)}"
    if raw_message:
        friendly_message += f"\n\n原始错误：\n{_wrap_error_text(raw_message)}"

    return friendly_message


def _show_api_error_dialog(parent, title: str, heading: str, details: str) -> None:
    from PyQt6.QtWidgets import QMessageBox

    show_error_dialog(parent, heading or title, "", details, icon=QMessageBox.Icon.Critical)


def _show_api_success_dialog(parent, title: str, heading: str, details: str) -> None:
    from PyQt6.QtWidgets import QMessageBox

    show_error_dialog(parent, heading or title, "", details, icon=QMessageBox.Icon.Information)


def _split_env_key(env_key: str) -> tuple[str, str, str]:
    normalized_key = (env_key or "").upper()
    scope = ""
    for prefix in ("OCR_", "COLOR_", "RENDER_"):
        if normalized_key.startswith(prefix):
            scope = prefix
            normalized_key = normalized_key[len(prefix):]
            break

    for provider in ("CUSTOM_OPENAI", "OPENAI", "GEMINI", "DEEPSEEK", "GROQ", "SAKURA"):
        provider_prefix = f"{provider}_"
        if normalized_key.startswith(provider_prefix):
            field = normalized_key[len(provider_prefix):]
            return scope, provider, field

    return scope, "", normalized_key


def _build_related_env_key(scope: str, provider: str, field: str) -> str | None:
    if not provider:
        return None
    return f"{scope}{provider}_{field}"


def _read_env_widget_value(self, env_key: str | None) -> str | None:
    if not env_key:
        return None
    pair = self.env_widgets.get(env_key)
    if not pair:
        return None
    return pair[1].text().strip() or None


def _resolve_api_context(self, env_key: str, translator_key: str) -> tuple[str, str | None, str | None, str | None]:
    api_type = _detect_current_api_type(env_key, translator_key)
    scope, provider, field = _split_env_key(env_key)

    api_key = None
    if field in ("API_KEY", "AUTH_KEY", "TOKEN"):
        api_key = _read_env_widget_value(self, env_key)
    else:
        for candidate_field in ("API_KEY", "AUTH_KEY", "TOKEN"):
            api_key = _read_env_widget_value(self, _build_related_env_key(scope, provider, candidate_field))
            if api_key:
                break

    api_base = None
    for candidate_field in ("API_BASE", "BASE"):
        api_base = _read_env_widget_value(self, _build_related_env_key(scope, provider, candidate_field))
        if api_base:
            break

    model = _read_env_widget_value(self, _build_related_env_key(scope, provider, "MODEL"))
    return api_type, api_key, api_base, model


def on_open_custom_api_params_file(self):
    """打开自定义 API 参数编辑器。"""
    from manga_translator.custom_api_params import ensure_custom_api_params_file, get_custom_api_params_path

    try:
        config_path = ensure_custom_api_params_file(get_custom_api_params_path())
    except Exception as e:
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.warning(self, self._t("Error"), f"创建配置文件失败: {e}")
        return

    try:
        from widgets.custom_api_params_editor import CustomApiParamsEditorDialog

        dialog = CustomApiParamsEditorDialog(config_path, t_func=self._t, parent=self)
        dialog.exec()
    except Exception as e:
        from PyQt6.QtWidgets import QMessageBox

        QMessageBox.warning(self, self._t("Error"), f"打开编辑器失败: {e}")


def on_test_api_clicked(self, key: str):
    """测试API连接。"""
    import asyncio

    from PyQt6.QtCore import QThread

    from widgets.themed_progress_dialog import create_progress_dialog

    if key not in self.env_widgets:
        return

    _, widget = self.env_widgets[key]
    api_key = widget.text().strip()

    translator_combo = self.findChild(QComboBox, "translator.translator")
    if not translator_combo:
        return

    translator_display = translator_combo.currentText()
    reverse_map = {v: k for k, v in self.controller.get_display_mapping("translator").items()}
    translator_key = reverse_map.get(translator_display, translator_display.lower())
    api_type, api_key, api_base, model = _resolve_api_context(self, key, translator_key)

    progress = create_progress_dialog(
        self,
        self._t("Testing"),
        self._t("Testing API connection, please wait..."),
    )
    progress.show()

    def run_test():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            self.controller.test_api_connection_async(api_type, api_key, api_base, model)
        )
        loop.close()
        return result

    class TestThread(QThread):
        finished_signal = pyqtSignal(bool, str)

        def run(self):
            try:
                success, message = run_test()
                self.finished_signal.emit(success, message)
            except Exception as e:
                self.finished_signal.emit(False, str(e))

    def on_test_finished(success, message):
        progress.close()
        if success:
            success_details = _wrap_error_text(message) if message else self._t("API connection test successful!")
            _show_api_success_dialog(
                self,
                self._t("Success"),
                self._t("API connection test successful!"),
                success_details,
            )
        else:
            friendly_message = _format_test_connection_error(api_type, message)
            _show_api_error_dialog(
                self,
                self._t("Error"),
                self._t("API connection test failed"),
                friendly_message,
            )

    test_thread = TestThread()
    test_thread.finished_signal.connect(on_test_finished)
    test_thread.start()
    self._test_thread = test_thread


def on_get_models_clicked(self, key: str):
    """获取可用模型列表。"""
    import asyncio

    from PyQt6.QtCore import QThread
    from PyQt6.QtWidgets import QMessageBox

    from desktop_qt_ui.widgets.model_selector_dialog import ModelSelectorDialog
    from widgets.themed_progress_dialog import create_progress_dialog

    translator_combo = self.findChild(QComboBox, "translator.translator")
    if not translator_combo:
        return

    translator_display = translator_combo.currentText()
    reverse_map = {v: k for k, v in self.controller.get_display_mapping("translator").items()}
    translator_key = reverse_map.get(translator_display, translator_display.lower())
    model_api_type, api_key, api_base, _ = _resolve_api_context(self, key, translator_key)

    progress = create_progress_dialog(
        self,
        self._t("Get Models"),
        self._t("Fetching models, please wait..."),
    )
    progress.show()

    def run_get_models():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            self.controller.get_available_models_async(model_api_type, api_key, api_base)
        )
        loop.close()
        return result

    class GetModelsThread(QThread):
        finished_signal = pyqtSignal(bool, list, str)

        def run(self):
            try:
                success, models, message = run_get_models()
                self.finished_signal.emit(success, models, message)
            except Exception as e:
                self.finished_signal.emit(False, [], str(e))

    def on_get_models_finished(success, models, message):
        progress.close()
        if success:
            if models:
                selected_model, ok = ModelSelectorDialog.get_model(
                    models,
                    self._t("Select Model"),
                    self._t("Available models:"),
                    parent=self,
                    t_func=self._t,
                )
                if ok and selected_model and key in self.env_widgets:
                    _, widget = self.env_widgets[key]
                    widget.setText(selected_model)
                    self.env_var_changed.emit(key, selected_model)
            else:
                QMessageBox.warning(self, self._t("Warning"), self._t("No models available"))
        else:
            friendly_message = _format_test_connection_error(model_api_type, message)
            _show_api_error_dialog(
                self,
                self._t("Error"),
                self._t("Failed to get models"),
                friendly_message,
            )

    get_models_thread = GetModelsThread()
    get_models_thread.finished_signal.connect(on_get_models_finished)
    get_models_thread.start()
    self._get_models_thread = get_models_thread


def refresh_preset_list(self, deleted_preset_name: str = None):
    """刷新预设列表。"""
    if not hasattr(self, "preset_combo"):
        return

    current_text = self.preset_combo.currentText()
    current_index = self.preset_combo.currentIndex()

    self.preset_combo.blockSignals(True)
    self.preset_combo.clear()

    presets = self.controller.get_presets_list()
    if not presets:
        self.controller.save_preset("默认", copy_current=False)
        presets = self.controller.get_presets_list()

    if presets:
        self.preset_combo.addItems(presets)

        if current_text and current_text in presets:
            self.preset_combo.setCurrentText(current_text)
            self.preset_combo.blockSignals(False)
        else:
            new_index = min(current_index, len(presets) - 1)
            self.preset_combo.setCurrentIndex(new_index)
            new_preset = self.preset_combo.currentText()
            self.preset_combo.blockSignals(False)
            self._on_preset_changed(new_preset)
            return

    self.preset_combo.blockSignals(False)


def on_add_preset_clicked(self):
    """添加新预设。"""
    from PyQt6.QtWidgets import QMessageBox
    from widgets.themed_text_input_dialog import themed_get_text

    preset_name, ok = themed_get_text(
        self,
        title=self._t("Add Preset"),
        label=self._t("Enter preset name:"),
        ok_text=self._t("OK"),
        cancel_text=self._t("Cancel"),
    )

    if ok and preset_name:
        preset_name = preset_name.strip()
        if not preset_name:
            QMessageBox.warning(self, self._t("Warning"), self._t("Preset name cannot be empty"))
            return

        existing_presets = self.controller.get_presets_list()
        if preset_name in existing_presets:
            reply = QMessageBox.question(
                self,
                self._t("Confirm"),
                self._t("Preset '{name}' already exists. Overwrite?", name=preset_name),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        success = self.controller.save_preset(preset_name, copy_current=False)
        if success:
            self._refresh_preset_list()
            self.preset_combo.setCurrentText(preset_name)
        else:
            QMessageBox.critical(self, self._t("Error"), self._t("Failed to create preset"))


def on_delete_preset_clicked(self):
    """删除选中的预设。"""
    from PyQt6.QtWidgets import QMessageBox

    preset_name = self.preset_combo.currentText()
    if not preset_name:
        QMessageBox.warning(self, self._t("Warning"), self._t("Please select a preset to delete"))
        return

    reply = QMessageBox.question(
        self,
        self._t("Confirm"),
        self._t("Are you sure you want to delete preset '{name}'?", name=preset_name),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )

    if reply == QMessageBox.StandardButton.Yes:
        success = self.controller.delete_preset(preset_name)
        if success:
            self._refresh_preset_list(deleted_preset_name=preset_name)
            QMessageBox.information(self, self._t("Success"), self._t("Preset deleted successfully"))
        else:
            QMessageBox.critical(self, self._t("Error"), self._t("Failed to delete preset"))


def on_preset_changed(self, new_preset_name: str):
    """切换预设时加载新预设。"""
    if not new_preset_name:
        return

    old_preset_name = getattr(self, "_current_preset_name", "")
    if old_preset_name == new_preset_name:
        return

    if self._env_debounce_timer.isActive():
        self._env_debounce_timer.stop()
        for key, (label, widget) in self.env_widgets.items():
            current_value = widget.text()
            self.controller.save_env_var(key, current_value)

    if old_preset_name:
        existing_presets = self.controller.get_presets_list()
        if old_preset_name in existing_presets:
            self.controller.save_preset(old_preset_name, copy_current=True)

    success = self.controller.load_preset(new_preset_name)
    if success:
        self._current_preset_name = new_preset_name
        self.controller.config_service.set_current_preset(new_preset_name)

        current_env_values = self.config_service.load_env_vars()
        for key, (label, widget) in self.env_widgets.items():
            new_value = current_env_values.get(key, "")
            widget.blockSignals(True)
            widget.setText(str(new_value) if new_value else "")
            widget.setPlaceholderText(self._get_env_default_placeholder(key))
            widget.blockSignals(False)


def update_output_path_display(self, path: str):
    """更新输出目录输入框显示。"""
    self.output_folder_input.setText(path)


def trigger_add_files(self):
    """触发添加文件对话框。"""
    last_dir = self.controller.get_last_open_dir()
    file_paths, _ = QFileDialog.getOpenFileNames(
        self,
        self._t("Add Files"),
        last_dir,
        "All Supported Files (*.png *.jpg *.jpeg *.bmp *.webp *.avif *.heic *.heif *.pdf *.epub *.cbz *.cbr *.zip);;"
        "Image Files (*.png *.jpg *.jpeg *.bmp *.webp *.avif *.heic *.heif);;"
        "PDF Files (*.pdf);;"
        "EPUB Files (*.epub);;"
        "Comic Book Archives (*.cbz *.cbr *.zip)",
    )
    if file_paths:
        self.controller.add_files(file_paths)
        new_dir = os.path.dirname(file_paths[0])
        self.controller.set_last_open_dir(new_dir)
