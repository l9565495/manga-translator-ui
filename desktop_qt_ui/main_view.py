
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QSplitter,
    QWidget,
)

from services import get_config_service, get_i18n_manager
import main_view_layout
from main_view_parts import dynamic_settings as main_view_dynamic
from main_view_parts import env_management as main_view_env
from main_view_parts import runtime as main_view_runtime
from main_view_parts import style as main_view_style
from main_view_parts import ui_texts as main_view_texts
from main_view_parts.theme import get_current_theme


class MainView(QWidget):
    """
    主翻译视图，对应旧UI的 MainView。
    包含文件列表、设置和日志。
    """
    setting_changed = pyqtSignal(str, object)
    env_var_changed = pyqtSignal(str, str)
    editor_view_requested = pyqtSignal()
    theme_change_requested = pyqtSignal(str)
    language_change_requested = pyqtSignal(str)

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
        self.setObjectName("main_view_root")
        
        # --- 创建主分割器 (左右) ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        main_splitter.setObjectName("main_view_splitter")
        self.layout.addWidget(main_splitter)

        # --- 左侧侧边栏 ---
        left_panel = self._create_left_sidebar()

        # --- 右侧面板 ---
        right_panel = self._create_right_panel()

        # --- 组合布局 ---
        main_splitter.addWidget(left_panel)
        main_splitter.addWidget(right_panel)
        main_splitter.setStretchFactor(0, 0) # 侧边栏固定为主
        main_splitter.setStretchFactor(1, 1) # 内容区可拉伸
        main_splitter.setCollapsible(0, False) # 侧边栏不折叠
        main_splitter.setCollapsible(1, True) # 内容区可以折叠
        main_splitter.setSizes([220, 1060]) # 设置初始比例
        main_splitter.setHandleWidth(6) # 设置分隔条宽度

        # 不在这里调用 _create_dynamic_settings，等待 app_logic.initialize 发送 config_loaded 信号
        # self._create_dynamic_settings()  # 删除这行，避免重复创建

        # Connect signals for button state management
        self.controller.state_manager.is_translating_changed.connect(self.on_translation_state_changed, type=Qt.ConnectionType.QueuedConnection)
        self.controller.state_manager.current_config_changed.connect(self.update_start_button_text)
        QTimer.singleShot(100, self.update_start_button_text) # Set initial text
        QTimer.singleShot(100, self._sync_workflow_mode_from_config) # Sync workflow mode dropdown
        self._apply_reference_ui_style()
    
    def _t(self, key: str, **kwargs) -> str:
        """翻译辅助方法"""
        if self.i18n:
            return self.i18n.translate(key, **kwargs)
        return key

    def _apply_reference_ui_style(self, theme: str | None = None):
        theme = theme or get_current_theme()
        main_view_style.apply_reference_ui_style(self, theme)
        if hasattr(self, "prompt_preview_panel") and self.prompt_preview_panel:
            self.prompt_preview_panel.apply_theme()
        if hasattr(self, "_refresh_font_preview_styles"):
            self._refresh_font_preview_styles()

    def _open_filter_list(self):
        main_view_dynamic._open_filter_list(self)

    @pyqtSlot(dict)
    def set_parameters(self, config: dict):
        main_view_dynamic.set_parameters(self, config)

    def _process_next_setting_chunk(self):
        main_view_dynamic._process_next_setting_chunk(self)

    def _finalize_settings_ui(self):
        main_view_dynamic._finalize_settings_ui(self)
    def _create_dynamic_settings(self):
        main_view_dynamic._create_dynamic_settings(self)
    def _on_setting_changed(self, value, full_key, display_map=None):
        main_view_dynamic._on_setting_changed(self, value, full_key, display_map)
    def _on_upscale_ratio_changed(self, text, full_key):
        main_view_dynamic._on_upscale_ratio_changed(self, text, full_key)
    def _on_numeric_input_changed(self, text, full_key, value_type):
        main_view_dynamic._on_numeric_input_changed(self, text, full_key, value_type)
    def _update_upscale_ratio_options(self, upscaler):
        main_view_dynamic._update_upscale_ratio_options(self, upscaler)
    def _create_param_widgets(self, data, parent_layout, prefix=""):
        main_view_dynamic._create_param_widgets(self, data, parent_layout, prefix)
    def _show_setting_description(self, key: str, name: str, description: str):
        """更新右侧描述面板"""
        if hasattr(self, 'settings_desc_name'):
            self.settings_desc_name.setText(name)
        if hasattr(self, 'settings_desc_key'):
            self.settings_desc_key.setText(self._t("Settings Desc Key", config_key=key))
        if hasattr(self, 'settings_desc_text'):
            self.settings_desc_text.setText(description or self._t("Settings Desc No Description"))
    def _create_left_sidebar(self) -> QWidget:
        return main_view_layout.create_left_sidebar(self)

    def _create_translation_page(self) -> QWidget:
        return main_view_layout.create_translation_page(self)

    def _create_settings_page(self) -> QWidget:
        return main_view_layout.create_settings_page(self)

    def _create_env_page(self) -> QWidget:
        return main_view_layout.create_env_page(self)

    def _create_prompt_page(self) -> QWidget:
        return main_view_layout.create_prompt_page(self)

    def _create_font_page(self) -> QWidget:
        return main_view_layout.create_font_page(self)

    def _create_right_panel(self) -> QWidget:
        return main_view_layout.create_right_panel(self)

    def _switch_content_page(self, page_key: str):
        main_view_layout.switch_content_page(self, page_key)

    def _on_nav_add_folder_clicked(self):
        main_view_layout.on_nav_add_folder_clicked(self)

    def _on_nav_mode_clicked(self):
        main_view_layout.on_nav_mode_clicked(self)

    def _on_nav_prompt_clicked(self):
        main_view_layout.on_nav_prompt_clicked(self)

    def _on_nav_editor_clicked(self):
        main_view_layout.on_nav_editor_clicked(self)

    def _on_nav_font_clicked(self):
        main_view_layout.on_nav_font_clicked(self)

    def _on_env_translator_combo_changed(self, display_name: str):
        main_view_layout.on_env_translator_combo_changed(self, display_name)

    def _populate_theme_combo(self):
        main_view_layout.populate_theme_combo(self)

    def _populate_language_combo(self):
        main_view_layout.populate_language_combo(self)

    def _on_theme_combo_changed(self, index: int):
        main_view_layout.on_theme_combo_changed(self, index)

    def _on_language_combo_changed(self, index: int):
        main_view_layout.on_language_combo_changed(self, index)

    def _sync_env_translator_combo_selection(self, display_name: str):
        main_view_layout.sync_env_translator_combo_selection(self, display_name)

    def _refresh_prompt_manager(self):
        main_view_layout.refresh_prompt_manager(self)

    def _apply_selected_prompt(self):
        main_view_layout.apply_selected_prompt(self)

    def _on_prompt_selection_changed(self, current, previous):
        main_view_layout.on_prompt_selection_changed(self, current, previous)

    def _open_prompt_editor(self, file_path: str):
        main_view_layout.open_prompt_editor(self, file_path)

    def _create_new_prompt(self):
        main_view_layout.create_new_prompt(self)

    def _delete_selected_prompt(self):
        main_view_layout.delete_selected_prompt(self)

    def _refresh_font_manager(self):
        main_view_layout.refresh_font_manager(self)

    def _apply_selected_font(self):
        main_view_layout.apply_selected_font(self)

    def _on_font_selection_changed(self, current, previous):
        main_view_layout._on_font_selection_changed(self, current, previous)

    def _refresh_font_preview_styles(self):
        main_view_layout.refresh_font_preview_styles(self)



    
    def update_progress(self, current: int, total: int, message: str = ""):
        main_view_runtime.update_progress(self, current, total, message)
    
    def reset_progress(self):
        main_view_runtime.reset_progress(self)
    
    def refresh_tab_titles(self):
        main_view_texts.refresh_tab_titles(self)
    
    def refresh_ui_texts(self):
        main_view_texts.refresh_ui_texts(self)
    
    def _clear_dynamic_settings(self):
        main_view_texts.clear_dynamic_settings(self)

    def _on_translator_changed(self, display_name: str):
        main_view_env.on_translator_changed(self, display_name)

    def _create_env_widgets(self, keys: list, current_values: dict):
        main_view_env.create_env_widgets(self, keys, current_values)

    def _get_env_default_placeholder(self, key: str) -> str:
        return main_view_env.get_env_default_placeholder(self, key)

    def _debounced_save_env_var(self, key: str, text: str):
        main_view_env.debounced_save_env_var(self, key, text)

    def _on_open_custom_api_params_file(self):
        main_view_env.on_open_custom_api_params_file(self)

    def _on_test_api_clicked(self, key: str):
        main_view_env.on_test_api_clicked(self, key)

    def _on_get_models_clicked(self, key: str):
        main_view_env.on_get_models_clicked(self, key)

    def _refresh_preset_list(self, deleted_preset_name: str = None):
        main_view_env.refresh_preset_list(self, deleted_preset_name)

    def _on_add_preset_clicked(self):
        main_view_env.on_add_preset_clicked(self)

    def _on_delete_preset_clicked(self):
        main_view_env.on_delete_preset_clicked(self)

    def _on_preset_changed(self, new_preset_name: str):
        main_view_env.on_preset_changed(self, new_preset_name)

    def update_output_path_display(self, path: str):
        main_view_env.update_output_path_display(self, path)

    def _trigger_add_files(self):
        main_view_env.trigger_add_files(self)

    def closeEvent(self, event):
        """处理窗口关闭事件"""
        self.app_logic.shutdown()
        event.accept()

    @pyqtSlot(bool)
    def on_translation_state_changed(self, is_translating: bool):
        main_view_runtime.on_translation_state_changed(self, is_translating)
    
    def _enable_stop_button(self):
        main_view_runtime.enable_stop_button(self)

    def set_stopping_state(self):
        main_view_runtime.set_stopping_state(self)

    def _sync_workflow_mode_from_config(self):
        main_view_runtime.sync_workflow_mode_from_config(self)

    def _on_workflow_mode_changed(self, index: int):
        main_view_runtime.on_workflow_mode_changed(self, index)

    def _update_workflow_mode_description(self, index: int | None = None):
        main_view_runtime.update_workflow_mode_description(self, index)

    def update_start_button_text(self):
        main_view_runtime.update_start_button_text(self)
