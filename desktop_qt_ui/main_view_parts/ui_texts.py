def refresh_tab_titles(self):
    """刷新标签页标题（用于语言切换）。"""
    tab_titles = getattr(self, "settings_tab_title_keys", None)
    if not tab_titles:
        tab_titles = ["Application Settings", "Basic Settings", "Advanced Settings", "Options"]
    for i, title_key in enumerate(tab_titles):
        if i < self.settings_tabs.count():
            self.settings_tabs.setTabText(i, self._t(title_key))


def refresh_ui_texts(self):
    """刷新所有UI文本（用于语言切换）。"""
    self.refresh_tab_titles()

    if hasattr(self, "sidebar_start_label"):
        self.sidebar_start_label.setText(self._t("Start Translation"))
    if hasattr(self, "sidebar_settings_label"):
        self.sidebar_settings_label.setText(self._t("Settings"))
    if hasattr(self, "sidebar_tools_label"):
        self.sidebar_tools_label.setText(self._t("Data Management"))
    if hasattr(self, "sidebar_editor_label"):
        self.sidebar_editor_label.setText(self._t("Editor"))
    if hasattr(self, "nav_translation_button"):
        self.nav_translation_button.setText(self._t("Translation Interface"))
    if hasattr(self, "nav_editor_button"):
        self.nav_editor_button.setText(self._t("Editor View"))
    if hasattr(self, "nav_add_folder_button"):
        self.nav_add_folder_button.setText(self._t("Add Folder"))
    if hasattr(self, "nav_mode_button"):
        self.nav_mode_button.setText(self._t("Select Mode"))
    if hasattr(self, "nav_settings_button"):
        self.nav_settings_button.setText(self._t("Settings"))
    if hasattr(self, "nav_env_button"):
        self.nav_env_button.setText(self._t("API Management"))
    if hasattr(self, "nav_prompt_button"):
        self.nav_prompt_button.setText(self._t("Prompt Management"))
    if hasattr(self, "nav_font_button"):
        self.nav_font_button.setText(self._t("Font Management"))
    if hasattr(self, "app_settings_box"):
        self.app_settings_box.setTitle(self._t("Application Settings"))

    if hasattr(self, "theme_label"):
        self.theme_label.setText(self._t("Theme:"))
    if hasattr(self, "language_label"):
        self.language_label.setText(self._t("Language:"))
    self._populate_theme_combo()
    self._populate_language_combo()

    if hasattr(self, "translation_page_title"):
        self.translation_page_title.setText(self._t("Translation Interface"))
    if hasattr(self, "translation_input_card"):
        self.translation_input_card.setTitle(self._t("Input Files"))
    if hasattr(self, "translation_task_card"):
        self.translation_task_card.setTitle(self._t("Translation Task"))
    if hasattr(self, "add_files_button"):
        self.add_files_button.setText(self._t("Add Files"))
    if hasattr(self, "add_folder_button"):
        self.add_folder_button.setText(self._t("Add Folder"))
    if hasattr(self, "clear_list_button"):
        self.clear_list_button.setText(self._t("Clear List"))

    if hasattr(self, "output_folder_label"):
        self.output_folder_label.setText(self._t("Output Directory:"))
    if hasattr(self, "output_folder_input"):
        self.output_folder_input.setPlaceholderText(self._t("Select or drag output folder..."))
    if hasattr(self, "browse_button"):
        self.browse_button.setText(self._t("Browse..."))
    if hasattr(self, "open_button"):
        self.open_button.setText(self._t("Open"))

    if hasattr(self, "workflow_mode_hint_label"):
        self.workflow_mode_hint_label.setText(
            self._t("Choose translation workflow mode before starting the task.")
        )
    if hasattr(self, "workflow_mode_label"):
        self.workflow_mode_label.setText(self._t("Translation Workflow Mode:"))
    current_index = 0
    if hasattr(self, "workflow_mode_combo"):
        current_index = self.workflow_mode_combo.currentIndex()
        self.workflow_mode_combo.blockSignals(True)
        self.workflow_mode_combo.clear()
        self.workflow_mode_combo.addItems(
            [
                self._t("Normal Translation"),
                self._t("Export Translation"),
                self._t("Export Original Text"),
                self._t("Import Translation and Render"),
                self._t("Colorize Only"),
                self._t("Upscale Only"),
                self._t("Inpaint Only"),
                self._t("Replace Translation"),
            ]
        )
        self.workflow_mode_combo.setCurrentIndex(current_index)
        self.workflow_mode_combo.blockSignals(False)
    if hasattr(self, "_update_workflow_mode_description"):
        self._update_workflow_mode_description(current_index)

    self.update_start_button_text()

    if hasattr(self, "export_config_button"):
        self.export_config_button.setText(self._t("Export Config"))
    if hasattr(self, "import_config_button"):
        self.import_config_button.setText(self._t("Import Config"))

    if hasattr(self, "settings_page_title"):
        self.settings_page_title.setText(self._t("Settings Page Title"))
    if hasattr(self, "settings_page_subtitle"):
        self.settings_page_subtitle.setText(self._t("Settings Page Subtitle"))
    if hasattr(self, "settings_desc_header_label"):
        self.settings_desc_header_label.setText(self._t("Settings Desc Header"))
    if hasattr(self, "settings_desc_name"):
        self.settings_desc_name.setText("")
    if hasattr(self, "settings_desc_key"):
        self.settings_desc_key.setText("")
    if hasattr(self, "settings_desc_text"):
        self.settings_desc_text.setText(self._t("Settings Desc Placeholder"))



    if hasattr(self, "env_page_title_label"):
        self.env_page_title_label.setText(self._t("API Management"))
    if hasattr(self, "env_page_subtitle_label"):
        self.env_page_subtitle_label.setText(
            self._t("Manage API keys and environment variables for each translator")
        )
    if hasattr(self, "env_tab_widget"):
        self.env_tab_widget.setTabText(0, self._t("Translation"))
        self.env_tab_widget.setTabText(1, self._t("OCR"))
        self.env_tab_widget.setTabText(2, self._t("Colorization"))
        self.env_tab_widget.setTabText(3, self._t("Render"))

    if hasattr(self, "file_list") and hasattr(self.file_list, "refresh_ui_texts"):
        self.file_list.refresh_ui_texts()

    if hasattr(self, "prompt_page_title_label"):
        self.prompt_page_title_label.setText(self._t("Prompt Management"))
    if hasattr(self, "prompt_card"):
        self.prompt_card.setTitle(self._t("Prompt Management"))
    if hasattr(self, "prompt_refresh_button"):
        self.prompt_refresh_button.setText(self._t("Refresh"))
    if hasattr(self, "prompt_open_dir_button"):
        self.prompt_open_dir_button.setText(self._t("Open Directory"))
    if hasattr(self, "prompt_apply_button"):
        self.prompt_apply_button.setText(self._t("Apply Selected Prompt"))
    if hasattr(self, "prompt_new_button"):
        self.prompt_new_button.setText(self._t("New"))
    if hasattr(self, "prompt_delete_button"):
        self.prompt_delete_button.setText(self._t("Delete"))

    if hasattr(self, "font_page_title_label"):
        self.font_page_title_label.setText(self._t("Font Management"))
    if hasattr(self, "font_card"):
        self.font_card.setTitle(self._t("Font Management"))
    if hasattr(self, "font_refresh_button"):
        self.font_refresh_button.setText(self._t("Refresh"))
    if hasattr(self, "font_open_dir_button"):
        self.font_open_dir_button.setText(self._t("Open Directory"))
    if hasattr(self, "font_apply_button"):
        self.font_apply_button.setText(self._t("Apply Selected Font"))

    if hasattr(self, "env_group_box") and self.env_group_box is not None:
        try:
            self.env_group_box.setTitle(self._t("API Keys (.env)"))
        except RuntimeError:
            pass

    self._clear_dynamic_settings()
    self._create_dynamic_settings()


def clear_dynamic_settings(self):
    """清理所有动态创建的设置控件。"""
    if hasattr(self, "env_group_box"):
        self.env_group_box = None
    if hasattr(self, "env_group_container_layout"):
        while self.env_group_container_layout.count():
            item = self.env_group_container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    for panel in self.tab_frames.values():
        if panel and panel.layout():
            layout = panel.layout()
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
