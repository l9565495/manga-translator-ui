from PyQt6.QtCore import QTimer

from main_view_parts.theme import repolish_widget


def _set_progress_state(self, state: str):
    if hasattr(self, "progress_bar"):
        self.progress_bar.setProperty("progressState", state)
        repolish_widget(self.progress_bar)


def _set_start_button_state(self, state: str):
    if hasattr(self, "start_button"):
        self.start_button.setProperty("translationState", state)
        repolish_widget(self.start_button)


def update_workflow_mode_description(self, index: int | None = None):
    """根据翻译流程模式更新翻译页标题下方的介绍文字。"""
    if not hasattr(self, "translation_page_subtitle"):
        return

    if index is None:
        if hasattr(self, "workflow_mode_combo"):
            index = self.workflow_mode_combo.currentIndex()
        else:
            index = 0

    mode_keys = {
        0: "Normal Translation",
        1: "Export Translation",
        2: "Export Original Text",
        3: "Import Translation and Render",
        4: "Colorize Only",
        5: "Upscale Only",
        6: "Inpaint Only",
        7: "Replace Translation",
    }
    tip_keys = {
        0: "Tip: Standard translation pipeline with detection, OCR, translation and rendering",
        1: "Tip: After exporting, check manga_translator_work/translations/ for imagename_translated.txt files",
        2: "Tip: After exporting, manually translate imagename_original.txt in manga_translator_work/originals/, then use 'Import Translation and Render' mode",
        3: "Tip: Will read TXT files from manga_translator_work/originals/ or translations/ and render (prioritize _original.txt)",
        4: "Tip: Only colorize images, no detection, OCR, translation or rendering",
        5: "Tip: Only upscale images, no detection, OCR, translation or rendering",
        6: "Tip: Detect text regions and inpaint to output clean images, no translation or rendering",
        7: "Tip: Place translated images in manga_translator_work/translated_images with matching filenames. The app extracts translated text, matches regions on raw images, inpaints originals, and renders translated text.",
    }
    mode_key = mode_keys.get(index, mode_keys[0])
    tip_key = tip_keys.get(index, tip_keys[0])
    if hasattr(self, "translation_page_title"):
        self.translation_page_title.setText(self._t(mode_key))
    self.translation_page_subtitle.setText(self._t(tip_key))







def update_progress(self, current: int, total: int, message: str = ""):
    """更新进度条。"""
    if total > 0:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        percentage = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setFormat(f"{current}/{total} ({percentage}%)")

        if not getattr(self, "_progress_active", False):
            self._progress_active = True
            _set_progress_state(self, "active")
    else:
        self._progress_active = False
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0/0 (0%)")
        _set_progress_state(self, "idle")


def reset_progress(self):
    """重置进度条为初始状态（灰色）。"""
    self._progress_active = False
    self.progress_bar.setMaximum(100)
    self.progress_bar.setValue(0)
    self.progress_bar.setFormat("0/0 (0%)")
    _set_progress_state(self, "idle")


def on_translation_state_changed(self, is_translating: bool):
    """根据翻译状态更新开始/停止按钮。"""
    if is_translating:
        self.start_button.setEnabled(False)
        self.start_button.setText(self._t("Starting..."))
        QTimer.singleShot(2000, self._enable_stop_button)
    else:
        self.start_button.setEnabled(True)
        _set_start_button_state(self, "ready")

        try:
            self.start_button.clicked.disconnect()
        except TypeError:
            pass
        self.start_button.clicked.connect(self.controller.start_backend_task)
        self.update_start_button_text()


def enable_stop_button(self):
    """启用停止按钮（延迟调用）。"""
    if self.controller.state_manager.is_translating():
        self.start_button.setEnabled(True)
        self.start_button.setText(self._t("Stop Translation"))
        _set_start_button_state(self, "stop")
        try:
            self.start_button.clicked.disconnect()
        except TypeError:
            pass
        self.start_button.clicked.connect(self.controller.stop_task)


def set_stopping_state(self):
    """设置按钮为“停止中...”状态，避免重复点击。"""
    self.start_button.setEnabled(False)
    self.start_button.setText(self._t("Stopping..."))
    _set_start_button_state(self, "stopping")
    try:
        self.start_button.clicked.disconnect()
    except TypeError:
        pass


def sync_workflow_mode_from_config(self):
    """从配置同步下拉框的选择。"""
    try:
        config = self.config_service.get_config()
        self.workflow_mode_combo.blockSignals(True)

        if config.cli.replace_translation:
            self.workflow_mode_combo.setCurrentIndex(7)
        elif config.cli.inpaint_only:
            self.workflow_mode_combo.setCurrentIndex(6)
        elif config.cli.upscale_only:
            self.workflow_mode_combo.setCurrentIndex(5)
        elif config.cli.colorize_only:
            self.workflow_mode_combo.setCurrentIndex(4)
        elif config.cli.load_text:
            self.workflow_mode_combo.setCurrentIndex(3)
        elif config.cli.template:
            self.workflow_mode_combo.setCurrentIndex(2)
        elif config.cli.generate_and_export:
            self.workflow_mode_combo.setCurrentIndex(1)
        else:
            self.workflow_mode_combo.setCurrentIndex(0)

        self.workflow_mode_combo.blockSignals(False)
        update_workflow_mode_description(self, self.workflow_mode_combo.currentIndex())
    except Exception as e:
        print(f"Error syncing workflow mode: {e}")


def on_workflow_mode_changed(self, index: int):
    """处理翻译流程模式改变并持久化。"""
    config = self.config_service.get_config()

    config.cli.load_text = False
    config.cli.template = False
    config.cli.generate_and_export = False
    config.cli.colorize_only = False
    config.cli.upscale_only = False
    config.cli.inpaint_only = False
    config.cli.replace_translation = False

    if index == 1:
        config.cli.generate_and_export = True
    elif index == 2:
        config.cli.template = True
    elif index == 3:
        config.cli.load_text = True
    elif index == 4:
        config.cli.colorize_only = True
    elif index == 5:
        config.cli.upscale_only = True
    elif index == 6:
        config.cli.inpaint_only = True
    elif index == 7:
        config.cli.replace_translation = True

    self.config_service.set_config(config)
    self.config_service.save_config_file()
    self.update_start_button_text()
    update_workflow_mode_description(self, index)


def update_start_button_text(self):
    """根据当前模式更新开始按钮文案。"""
    if self.controller.state_manager.is_translating():
        return

    try:
        config = self.config_service.get_config()
        if config.cli.replace_translation:
            self.start_button.setText(self._t("Start Replace Translation"))
        elif config.cli.inpaint_only:
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
        self.start_button.setText(self._t("Start Translation"))
        print(f"Could not update button text: {e}")
