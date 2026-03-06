"""
提示词预览 & 编辑组件
Prompt preview & editor components for the Prompt Management page.
"""
import json
import os
from typing import Any, Callable, Dict, List, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from main_view_parts.theme import get_current_theme, get_current_theme_colors


# 模块级翻译函数（由 Panel / Dialog 初始化时设置）
_current_t = lambda x: x


def _theme_tokens() -> Dict[str, str]:
    """为提示词预览/编辑器生成当前主题下的局部 token。"""
    c = get_current_theme_colors()
    is_light = get_current_theme() == "light"
    return {
        **c,
        "card_bg": c["bg_desc_panel"],
        "card_border": c["desc_panel_border"],
        "fg": c["text_primary"],
        "fg_bright": c["text_page_title"],
        "fg_dim": c["text_page_subtitle"],
        "accent": c["divider_accent_start"],
        "table_bg": c["bg_list"],
        "table_border": c["border_list"],
        "table_alt_bg": c["tab_bg"],
        "table_grid": c["divider_sub_line"],
        "table_header_bg": c["bg_toolbar"],
        "selection_bg": c["list_item_selected"],
        "selection_fg": c["list_item_selected_text"],
        "editor_bg": c["bg_text_edit"],
        "editor_border": c["border_input_focus"],
        "menu_hover_bg": c["tab_hover"],
        "danger_hover_bg": "rgba(214, 72, 72, 0.14)" if is_light else "rgba(200, 60, 60, 0.34)",
        "danger_hover_fg": "#D94C4C" if is_light else "#FF8A8A",
        "status_success": "#2E9D57" if is_light else "#6BCB77",
        "status_error": "#D94C4C" if is_light else "#FF6B6B",
    }


def _section_label_style() -> str:
    t = _theme_tokens()
    return (
        f"color: {t['fg_bright']}; font-size: 13px; font-weight: 700; "
        "padding: 4px 0 2px 0; background: transparent;"
    )


def _dim_label_style() -> str:
    t = _theme_tokens()
    return f"color: {t['fg_dim']}; font-size: 12px; background: transparent;"


def _body_label_style() -> str:
    t = _theme_tokens()
    return f"color: {t['fg']}; font-size: 12px; background: transparent; padding: 2px 0;"


def _divider_style() -> str:
    t = _theme_tokens()
    return (
        "background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
        f"stop:0 {t['divider_line_start']}, stop:1 {t['divider_line_end']});"
        "max-height: 1px; border: none;"
    )


def _prompt_card_style() -> str:
    t = _theme_tokens()
    return f"""
        #prompt_preview_card {{
            background: {t["card_bg"]};
            border: 1px solid {t["card_border"]};
            border-radius: 10px;
        }}
    """


def _title_style(size: int) -> str:
    t = _theme_tokens()
    return f"color: {t['fg_bright']}; font-size: {size}px; font-weight: 700; background: transparent;"


def _table_style(editable: bool = False) -> str:
    t = _theme_tokens()
    editor_css = ""
    if editable:
        editor_css = f"""
            QTableWidget QLineEdit {{
                background: {t["bg_input_focus"]};
                color: {t["fg"]};
                border: 1px solid {t["editor_border"]};
                padding: 2px 6px;
                font-size: 12px;
            }}
        """
    return f"""
        QTableWidget {{
            background: {t["table_bg"]};
            border: 1px solid {t["table_border"]};
            border-radius: 6px;
            color: {t["fg"]};
            gridline-color: {t["table_grid"]};
            font-size: 12px;
        }}
        QTableWidget::item {{
            padding: 4px 8px;
        }}
        QTableWidget::item:alternate {{
            background: {t["table_alt_bg"]};
        }}
        QTableWidget::item:selected {{
            background: {t["selection_bg"]};
            color: {t["selection_fg"]};
        }}
        QHeaderView::section {{
            background: {t["table_header_bg"]};
            color: {t["fg_bright"]};
            font-weight: 600;
            font-size: 11px;
            padding: 5px 8px;
            border: none;
            border-bottom: 1px solid {t["table_border"]};
        }}
        {editor_css}
    """


def _prompt_tabs_style() -> str:
    t = _theme_tokens()
    return f"""
        QTabWidget::pane {{
            border: 1px solid {t["border_card"]};
            border-radius: 6px;
            background: {t["bg_panel"]};
            padding: 2px;
        }}
        QTabBar::tab {{
            background: {t["tab_bg"]};
            border: 1px solid {t["border_tab"]};
            border-bottom: none;
            border-top-left-radius: 6px;
            border-top-right-radius: 6px;
            color: {t["fg_dim"]};
            padding: 6px 12px;
            margin-right: 2px;
            font-size: 11px;
            font-weight: 600;
        }}
        QTabBar::tab:selected {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                                        stop:0 {t["tab_selected_start"]}, stop:1 {t["tab_selected_end"]});
            color: {t["fg_bright"]};
            border-color: {t["border_tab_selected"]};
        }}
        QTabBar::tab:hover:!selected {{
            background: {t["menu_hover_bg"]};
            color: {t["fg"]};
        }}
    """


def _text_edit_style() -> str:
    t = _theme_tokens()
    return f"""
        QPlainTextEdit {{
            background: {t["editor_bg"]};
            border: 1px solid {t["border_settings_input"]};
            border-radius: 8px;
            color: {t["fg"]};
            padding: 10px;
            selection-background-color: {t["selection_bg"]};
        }}
    """


def _dialog_style() -> str:
    t = _theme_tokens()
    return f"""
        QDialog {{
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {t["bg_gradient_start"]}, stop:0.55 {t["bg_gradient_mid"]}, stop:1 {t["bg_gradient_end"]});
        }}
        QLabel {{
            color: {t["fg"]};
            background: transparent;
        }}
        QTabWidget::pane {{
            border: 1px solid {t["border_card"]};
            border-radius: 10px;
            background: {t["bg_panel"]};
            padding: 4px;
        }}
        QTabBar::tab {{
            background: {t["tab_bg"]};
            border: 1px solid {t["border_tab"]};
            border-bottom: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            color: {t["fg_dim"]};
            padding: 9px 16px;
            margin-right: 3px;
            font-weight: 600;
            font-size: 12px;
        }}
        QTabBar::tab:selected {{
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 {t["tab_selected_start"]}, stop:1 {t["tab_selected_end"]});
            color: {t["fg_bright"]};
            border-color: {t["border_tab_selected"]};
        }}
        QTabBar::tab:hover:!selected {{
            background: {t["menu_hover_bg"]};
            color: {t["fg"]};
        }}
    """


def _add_section_button_style() -> str:
    t = _theme_tokens()
    return f"""
        QPushButton {{
            background: {t["btn_chip_bg"]};
            border: 1px dashed {t["btn_chip_border"]};
            border-radius: 8px;
            color: {t["accent"]};
            padding: 10px 20px;
            font-weight: 600;
            font-size: 13px;
        }}
        QPushButton:hover {{
            background: {t["btn_chip_hover"]};
            border-color: {t["border_tab_selected"]};
            color: {t["fg_bright"]};
        }}
    """


def _op_button_style(danger: bool = False) -> str:
    t = _theme_tokens()
    if danger:
        return f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {t["fg_dim"]};
                font-size: 14px;
                padding: 2px 6px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background: {t["danger_hover_bg"]};
                color: {t["danger_hover_fg"]};
            }}
        """
    return f"""
        QPushButton {{
            background: transparent;
            border: none;
            color: {t["fg_dim"]};
            font-size: 14px;
            padding: 2px 6px;
            border-radius: 4px;
        }}
        QPushButton:hover {{
            background: {t["nav_hover_bg"]};
            color: {t["fg_bright"]};
        }}
    """


def _line_edit_style() -> str:
    t = _theme_tokens()
    return f"""
        QLineEdit {{
            background: {t["bg_input"]};
            border: 1px solid {t["border_settings_input"]};
            border-radius: 7px;
            color: {t["fg"]};
            padding: 7px 10px;
            min-height: 20px;
        }}
        QLineEdit:focus {{
            border-color: {t["editor_border"]};
        }}
    """


def _menu_style() -> str:
    t = _theme_tokens()
    return f"""
        QMenu {{
            background: {t["bg_dropdown"]};
            border: 1px solid {t["border_input"]};
            border-radius: 8px;
            padding: 6px 4px;
            color: {t["fg"]};
        }}
        QMenu::item {{
            padding: 8px 20px;
            border-radius: 5px;
            font-size: 13px;
        }}
        QMenu::item:selected {{
            background: {t["menu_hover_bg"]};
            color: {t["fg_bright"]};
        }}
    """


def _status_style(kind: str) -> str:
    t = _theme_tokens()
    color = t["fg_dim"]
    if kind == "success":
        color = t["status_success"]
    elif kind == "error":
        color = t["status_error"]
    return f"color: {color}; font-size: 12px; background: transparent;"


def _section_label(text: str) -> QLabel:
    """可复用的小标题 Label。"""
    lbl = QLabel(text)
    lbl.setStyleSheet(_section_label_style())
    return lbl


def _dim_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(_dim_label_style())
    return lbl


def _body_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    lbl.setStyleSheet(_body_label_style())
    return lbl


def _divider() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(_divider_style())
    return line


def _make_glossary_table(entries: List[Dict[str, str]]) -> QTableWidget:
    """生成一个只读的 original → translation 表。"""
    table = QTableWidget(len(entries), 2)
    table.setHorizontalHeaderLabels([_current_t("Original"), _current_t("Translation")])
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.setStyleSheet(_table_style())

    for row, entry in enumerate(entries):
        table.setItem(row, 0, QTableWidgetItem(entry.get("original", "")))
        table.setItem(row, 1, QTableWidgetItem(entry.get("translation", "")))

    # auto-size height: header + rows (capped at 300px)
    row_h = 28
    header_h = table.horizontalHeader().height() if table.horizontalHeader().isVisible() else 28
    desired = header_h + row_h * len(entries) + 4
    table.setFixedHeight(min(desired, 300))
    table.verticalHeader().setDefaultSectionSize(row_h)
    return table


# ─────────────────────────────────────────────────────────
# PromptPreviewPanel  (右侧结构化预览)
# ─────────────────────────────────────────────────────────
class PromptPreviewPanel(QWidget):
    """
    右侧预览面板。
    - 如果 prompt 文件符合已知格式（有 glossary / project_data），展示结构化预览
    - 否则展示原始文本内容
    """
    edit_requested = pyqtSignal(str)  # file_path

    def __init__(self, t_func: Callable = None, parent=None):
        super().__init__(parent)
        self._t = t_func or (lambda x: x)
        global _current_t
        _current_t = self._t
        self._current_path: Optional[str] = None
        self._setup_ui()

    # ─── UI 搭建 ───────────────────────────────────────
    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 外框容器 (card 样式)
        self._card = QWidget()
        self._card.setObjectName("prompt_preview_card")
        self._card.setStyleSheet(_prompt_card_style())
        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(8)

        # Title row
        title_row = QHBoxLayout()
        self._title_label = QLabel(self._t("Prompt Preview"))
        self._title_label.setStyleSheet(_title_style(14))
        title_row.addWidget(self._title_label, 1)

        self._edit_btn = QPushButton(self._t("Edit"))
        self._edit_btn.setProperty("chipButton", True)
        self._edit_btn.setFixedWidth(72)
        self._edit_btn.clicked.connect(self._on_edit_clicked)
        self._edit_btn.setEnabled(False)
        title_row.addWidget(self._edit_btn)
        card_layout.addLayout(title_row)

        card_layout.addWidget(_divider())

        # 文件名
        self._filename_label = _dim_label(self._t("Select a prompt file to preview"))
        card_layout.addWidget(self._filename_label)

        # Scroll area for content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(0, 4, 0, 4)
        self._content_layout.setSpacing(8)
        scroll.setWidget(self._content_widget)
        card_layout.addWidget(scroll, 1)

        root.addWidget(self._card)

    def apply_theme(self):
        """主题切换后重建本面板的局部样式。"""
        self._card.setStyleSheet(_prompt_card_style())
        self._title_label.setStyleSheet(_title_style(14))
        self._filename_label.setStyleSheet(_dim_label_style())
        if self._current_path:
            self.load_file(self._current_path)

    # ─── 清空 ──────────────────────────────────────────
    def _clear_content(self):
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    # ─── 外部调用：加载文件 ─────────────────────────────
    def load_file(self, file_path: str):
        """加载 prompt 文件并展示预览。"""
        self._current_path = file_path
        self._clear_content()
        self._edit_btn.setEnabled(bool(file_path))

        if not file_path or not os.path.isfile(file_path):
            self._filename_label.setText(self._t("File not found"))
            return

        self._filename_label.setText(os.path.basename(file_path))

        # 尝试解析
        data = self._try_load(file_path)
        if data is not None and self._is_structured(data):
            self._render_structured(data)
        else:
            self._render_raw(file_path)

    def clear(self):
        self._current_path = None
        self._clear_content()
        self._edit_btn.setEnabled(False)
        self._filename_label.setText(self._t("Select a prompt file to preview"))

    # ─── 解析 ──────────────────────────────────────────
    @staticmethod
    def _try_load(path: str) -> Optional[dict]:
        ext = os.path.splitext(path)[1].lower()
        try:
            with open(path, "r", encoding="utf-8") as f:
                if ext in (".yaml", ".yml"):
                    try:
                        import yaml
                        return yaml.safe_load(f)
                    except ImportError:
                        return None
                else:
                    return json.load(f)
        except Exception:
            return None

    @staticmethod
    def _is_structured(data: Any) -> bool:
        if not isinstance(data, dict):
            return False
        # 只要有以下任一关键字段就认为是结构化的
        return bool(
            data.get("glossary")
            or data.get("project_data")
            or data.get("persona")
            or data.get("character_list")
        )

    # ─── 结构化渲染 ────────────────────────────────────
    def _render_structured(self, data: dict):
        layout = self._content_layout

        # 1. Persona
        persona = data.get("persona")
        if persona:
            layout.addWidget(_section_label("📋 " + self._t("Persona")))
            layout.addWidget(_body_label(str(persona)))
            layout.addWidget(_divider())

        # 2. Project data
        project = data.get("project_data")
        if isinstance(project, dict):
            title = project.get("title")
            if title:
                layout.addWidget(_section_label("📚 " + self._t("Project") + f": {title}"))
            else:
                layout.addWidget(_section_label("📚 " + self._t("Project Data")))

            # Character list
            chars = project.get("character_list")
            if isinstance(chars, list) and chars:
                layout.addWidget(_dim_label(self._t("Characters") + f" ({len(chars)})"))
                char_table = QTableWidget(len(chars), 3)
                char_table.setHorizontalHeaderLabels([self._t("JP Name"), self._t("CN Name"), self._t("Nicknames")])
                char_table.horizontalHeader().setStretchLastSection(True)
                char_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
                char_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
                char_table.verticalHeader().setVisible(False)
                char_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
                char_table.setAlternatingRowColors(True)
                char_table.setStyleSheet(_table_style())
                for r, ch in enumerate(chars):
                    char_table.setItem(r, 0, QTableWidgetItem(ch.get("jp_name", "")))
                    char_table.setItem(r, 1, QTableWidgetItem(ch.get("cn_name", "")))
                    nicks = ch.get("nicknames", [])
                    char_table.setItem(r, 2, QTableWidgetItem(", ".join(nicks) if isinstance(nicks, list) else str(nicks)))
                row_h = 28
                hdr_h = 28
                char_table.setFixedHeight(min(hdr_h + row_h * len(chars) + 4, 260))
                char_table.verticalHeader().setDefaultSectionSize(row_h)
                layout.addWidget(char_table)

            # Terminology (project-level)
            term = project.get("terminology")
            if isinstance(term, dict) and term:
                layout.addWidget(_dim_label(self._t("Terminology") + f" ({len(term)})"))
                entries = [{"original": k, "translation": v} for k, v in term.items()]
                layout.addWidget(_make_glossary_table(entries))

            layout.addWidget(_divider())

        # 3. Style Guide
        sg = data.get("style_guide")
        if isinstance(sg, list) and sg:
            layout.addWidget(_section_label("🎨 " + self._t("Style Guide")))
            for item in sg:
                layout.addWidget(_body_label("• " + str(item)))
            layout.addWidget(_divider())

        # 4. Translation Rules
        tr = data.get("translation_rules")
        if isinstance(tr, list) and tr:
            layout.addWidget(_section_label("📏 " + self._t("Translation Rules")))
            for item in tr:
                layout.addWidget(_body_label("• " + str(item)))
            layout.addWidget(_divider())

        # 5. Glossary (auto-extracted)
        glossary = data.get("glossary")
        if isinstance(glossary, dict) and glossary:
            total = sum(len(v) for v in glossary.values() if isinstance(v, list))
            layout.addWidget(_section_label("📖 " + self._t("Glossary") + f" ({total})"))

            # 用 tab widget 按分类展示
            tabs = QTabWidget()
            tabs.setStyleSheet(_prompt_tabs_style())

            category_icons = {
                "Person": "👤",
                "Location": "📍",
                "Org": "🏢",
                "Item": "🔮",
                "Skill": "⚡",
                "Creature": "🐾",
            }

            for cat_key in ["Person", "Location", "Org", "Item", "Skill", "Creature"]:
                entries = glossary.get(cat_key, [])
                if not isinstance(entries, list) or not entries:
                    continue
                icon = category_icons.get(cat_key, "")
                tab_page = QWidget()
                tab_lay = QVBoxLayout(tab_page)
                tab_lay.setContentsMargins(4, 4, 4, 4)
                tab_lay.addWidget(_make_glossary_table(entries))
                tabs.addTab(tab_page, f"{icon} {self._t(cat_key)} ({len(entries)})")

            # 处理非标准分类
            standard_keys = {"Person", "Location", "Org", "Item", "Skill", "Creature"}
            for cat_key, entries in glossary.items():
                if cat_key in standard_keys:
                    continue
                if not isinstance(entries, list) or not entries:
                    continue
                tab_page = QWidget()
                tab_lay = QVBoxLayout(tab_page)
                tab_lay.setContentsMargins(4, 4, 4, 4)
                tab_lay.addWidget(_make_glossary_table(entries))
                tabs.addTab(tab_page, f"{cat_key} ({len(entries)})")

            tabs.setMinimumHeight(200)
            layout.addWidget(tabs)
            layout.addWidget(_divider())

        # 6. Output format
        of = data.get("output_format")
        if of:
            layout.addWidget(_section_label("📤 " + self._t("Output Format")))
            layout.addWidget(_body_label(str(of)))

        layout.addStretch()

    # ─── 原始文本渲染 ──────────────────────────────────
    def _render_raw(self, file_path: str):
        layout = self._content_layout
        layout.addWidget(_dim_label(self._t("Unrecognized format – showing raw content")))
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception as e:
            raw = f"Error reading file: {e}"

        text_edit = QPlainTextEdit(raw)
        text_edit.setReadOnly(True)
        font = QFont("Consolas", 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        text_edit.setFont(font)
        text_edit.setStyleSheet(_text_edit_style())
        layout.addWidget(text_edit, 1)

    # ─── 编辑按钮 ──────────────────────────────────────
    def _on_edit_clicked(self):
        if self._current_path:
            self.edit_requested.emit(self._current_path)


# ─────────────────────────────────────────────────────────
# 可编辑 glossary 表格（支持增删行）
# ─────────────────────────────────────────────────────────
def _make_editable_glossary_table(entries: List[Dict[str, str]]) -> QTableWidget:
    """生成一个可编辑的 original → translation 表。"""
    table = QTableWidget(len(entries), 2)
    table.setHorizontalHeaderLabels([_current_t("Original"), _current_t("Translation")])
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.setStyleSheet(_table_style(editable=True))

    for row, entry in enumerate(entries):
        table.setItem(row, 0, QTableWidgetItem(entry.get("original", "")))
        table.setItem(row, 1, QTableWidgetItem(entry.get("translation", "")))

    row_h = 28
    table.verticalHeader().setDefaultSectionSize(row_h)
    return table


def _styled_text_edit(text: str = "", read_only: bool = False) -> QPlainTextEdit:
    """统一风格的文本编辑框。"""
    te = QPlainTextEdit(text)
    te.setReadOnly(read_only)
    font = QFont("Consolas", 11)
    font.setStyleHint(QFont.StyleHint.Monospace)
    te.setFont(font)
    te.setStyleSheet(_text_edit_style())
    te.setTabStopDistance(28)
    return te

_GLOSSARY_CATEGORIES = ["Person", "Location", "Org", "Item", "Skill", "Creature"]


class PromptEditorDialog(QDialog):
    """
    弹窗式编辑器，支持两种模式：
    - 模板编辑 (Tab 1): 结构化表单编辑各字段
    - 自由编辑 (Tab 2): 直接编辑原始文本
    不符合格式的文件只显示自由编辑 Tab。
    """

    def __init__(self, file_path: str, t_func: Callable = None, parent=None):
        super().__init__(parent)
        self._t = t_func or (lambda x: x)
        global _current_t
        _current_t = self._t
        self._file_path = file_path
        self._original_content = ""
        self._data: Optional[dict] = None  # 解析后的结构化数据
        self._is_structured = False
        self._template_dirty = False  # 模板 tab 是否有修改
        self._free_dirty = False  # 自由 tab 是否有修改

        # 模板编辑的控件引用
        self._persona_edit: Optional[QPlainTextEdit] = None
        self._style_guide_edit: Optional[QPlainTextEdit] = None
        self._rules_edit: Optional[QPlainTextEdit] = None
        self._output_format_edit: Optional[QPlainTextEdit] = None
        self._char_table: Optional[QTableWidget] = None
        self._term_table: Optional[QTableWidget] = None
        self._title_edit = None
        self._glossary_tables: Dict[str, QTableWidget] = {}

        self._setup_ui()
        self._load_file()

    # ─── UI ────────────────────────────────────────────
    def _setup_ui(self):
        self.setWindowTitle(self._t("Edit Prompt") + f" – {os.path.basename(self._file_path)}")
        self.setMinimumSize(820, 580)
        self.resize(1000, 700)
        self.setStyleSheet(_dialog_style())

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        title = QLabel(self._t("Edit Prompt"))
        title.setStyleSheet(_title_style(16))
        hdr.addWidget(title, 1)
        hdr.addWidget(_dim_label(os.path.basename(self._file_path)))
        root.addLayout(hdr)
        root.addWidget(_divider())

        # Tabs
        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)

        # Status
        self._status = _dim_label("")
        root.addWidget(self._status)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = QPushButton(self._t("Cancel"))
        self._cancel_btn.setFixedWidth(100)
        self._cancel_btn.setProperty("chipButton", True)
        self._cancel_btn.clicked.connect(self.reject)

        self._save_btn = QPushButton(self._t("Save"))
        self._save_btn.setFixedWidth(100)
        self._save_btn.setProperty("variant", "accent")
        self._save_btn.clicked.connect(self._save)

        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._save_btn)
        root.addLayout(btn_row)

    # ─── 加载 ──────────────────────────────────────────
    def _load_file(self):
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                self._original_content = f.read()
        except Exception as e:
            self._original_content = ""
            self._status.setText(f"Error: {e}")
            self._status.setStyleSheet(_status_style("error"))

        # 尝试解析
        self._data = PromptPreviewPanel._try_load(self._file_path)
        self._is_structured = (
            self._data is not None and PromptPreviewPanel._is_structured(self._data)
        )

        if self._is_structured:
            self._build_template_tab()

        self._build_free_tab()
        self._status.setText(self._t("Loaded successfully"))
        self._status.setStyleSheet(_status_style("default"))

    # ─── 模板编辑 Tab ──────────────────────────────────
    def _build_template_tab(self):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # 保存 layout 引用，供动态添加字段用
        self._template_layout = layout
        # 有序容器列表 [(key, container_widget), ...]
        self._section_containers: list = []

        data = self._data

        # Persona
        persona = data.get("persona", "")
        if persona is not None:
            self._insert_section("persona", layout, text=str(persona))

        # Project title
        project = data.get("project_data")
        if isinstance(project, dict):
            self._insert_section("project_title", layout, title=project.get("title", ""))

            # Character list
            chars = project.get("character_list", [])
            if isinstance(chars, list):
                self._insert_section("characters", layout, chars=chars)

            # Terminology
            term = project.get("terminology")
            if isinstance(term, dict):
                self._insert_section("terminology", layout, term=term)

        # Style Guide
        sg = data.get("style_guide")
        if isinstance(sg, list):
            self._insert_section("style_guide", layout, rules=sg)

        # Translation Rules
        tr = data.get("translation_rules")
        if isinstance(tr, list):
            self._insert_section("translation_rules", layout, rules=tr)

        # Glossary
        glossary = data.get("glossary")
        if isinstance(glossary, dict):
            self._insert_section("glossary", layout, glossary=glossary)

        # Output format
        of = data.get("output_format")
        if of is not None:
            self._insert_section("output_format", layout, text=str(of))

        # ── "+ 添加字段" 按钮 ──
        self._add_section_btn = QPushButton("＋ " + self._t("Add Section"))
        self._add_section_btn.setProperty("chipButton", True)
        self._add_section_btn.setStyleSheet(_add_section_button_style())
        self._add_section_btn.clicked.connect(self._show_add_section_menu)
        layout.addWidget(self._add_section_btn)

        layout.addStretch()
        scroll.setWidget(content)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)
        self._tabs.addTab(page, "📝 " + self._t("Template Edit"))

    # ─── 容器创建 & 操作栏 ─────────────────────────────
    _SECTION_META = {
        "persona":           ("📋", "Persona"),
        "project_title":     ("📚", "Project Title"),
        "characters":        ("👤", "Characters"),
        "terminology":       ("📝", "Terminology"),
        "style_guide":       ("🎨", "Style Guide"),
        "translation_rules": ("📏", "Translation Rules"),
        "glossary":          ("📖", "Glossary"),
        "output_format":     ("📤", "Output Format"),
    }

    def _make_section_container(self, key: str) -> tuple:
        """创建带操作栏的容器 Widget，返回 (container, body_layout)。"""
        icon, label = self._SECTION_META.get(key, ("📌", key))
        container = QWidget()
        container.setProperty("sectionKey", key)
        container.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # 标题行
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        title_lbl = _section_label(f"{icon} {self._t(label)}")
        header.addWidget(title_lbl)
        header.addStretch()

        btn_up = QPushButton("▲")
        btn_up.setToolTip(self._t("Move Up"))
        btn_up.setStyleSheet(_op_button_style())
        btn_up.setFixedSize(28, 24)
        btn_up.clicked.connect(lambda: self._move_section(container, -1))

        btn_down = QPushButton("▼")
        btn_down.setToolTip(self._t("Move Down"))
        btn_down.setStyleSheet(_op_button_style())
        btn_down.setFixedSize(28, 24)
        btn_down.clicked.connect(lambda: self._move_section(container, 1))

        btn_del = QPushButton("✕")
        btn_del.setToolTip(self._t("Delete"))
        btn_del.setStyleSheet(_op_button_style(danger=True))
        btn_del.setFixedSize(28, 24)
        btn_del.clicked.connect(lambda: self._remove_section(container, key))

        header.addWidget(btn_up)
        header.addWidget(btn_down)
        header.addWidget(btn_del)
        outer.addLayout(header)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        outer.addLayout(body)
        outer.addWidget(_divider())

        return container, body

    def _insert_section(self, key: str, layout: QVBoxLayout, idx: int = -1, **kwargs):
        """创建并插入一个字段区域到 layout。"""
        container, body = self._make_section_container(key)

        # 根据 key 填充 body
        if key == "persona":
            self._fill_persona(body, kwargs.get("text", ""))
        elif key == "project_title":
            self._fill_project_title(body, kwargs.get("title", ""))
        elif key == "characters":
            self._fill_characters(body, kwargs.get("chars", []))
        elif key == "terminology":
            self._fill_terminology(body, kwargs.get("term", {}))
        elif key == "style_guide":
            self._fill_style_guide(body, kwargs.get("rules", []))
        elif key == "translation_rules":
            self._fill_translation_rules(body, kwargs.get("rules", []))
        elif key == "glossary":
            self._fill_glossary(body, kwargs.get("glossary", {}))
        elif key == "output_format":
            self._fill_output_format(body, kwargs.get("text", ""))

        if idx < 0:
            # 在"添加字段"按钮之前插入（如果有的话）
            if hasattr(self, '_add_section_btn') and self._add_section_btn is not None:
                btn_idx = layout.indexOf(self._add_section_btn)
                if btn_idx >= 0:
                    layout.insertWidget(btn_idx, container)
                else:
                    layout.addWidget(container)
            else:
                layout.addWidget(container)
            self._section_containers.append((key, container))
        else:
            layout.insertWidget(idx, container)
            self._section_containers.insert(idx, (key, container))

    # ─── 各字段的填充方法 ──────────────────────────────
    def _fill_persona(self, layout: QVBoxLayout, text: str = ""):
        self._persona_edit = _styled_text_edit(text)
        self._persona_edit.setFixedHeight(100)
        layout.addWidget(self._persona_edit)

    def _fill_project_title(self, layout: QVBoxLayout, title: str = ""):
        from PyQt6.QtWidgets import QLineEdit
        self._title_edit = QLineEdit(title)
        self._title_edit.setStyleSheet(_line_edit_style())
        layout.addWidget(self._title_edit)

    def _fill_characters(self, layout: QVBoxLayout, chars: list = None):
        if chars is None:
            chars = []
        self._char_table = QTableWidget(len(chars), 3)
        self._char_table.setHorizontalHeaderLabels([self._t("JP Name"), self._t("CN Name"), self._t("Nicknames")])
        self._char_table.horizontalHeader().setStretchLastSection(True)
        self._char_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._char_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._char_table.verticalHeader().setVisible(False)
        self._char_table.setAlternatingRowColors(True)
        self._char_table.setStyleSheet(_table_style(editable=True))
        for r, ch in enumerate(chars):
            self._char_table.setItem(r, 0, QTableWidgetItem(ch.get("jp_name", "")))
            self._char_table.setItem(r, 1, QTableWidgetItem(ch.get("cn_name", "")))
            nicks = ch.get("nicknames", [])
            nick_str = ", ".join(nicks) if isinstance(nicks, list) else str(nicks)
            self._char_table.setItem(r, 2, QTableWidgetItem(nick_str))
        self._char_table.verticalHeader().setDefaultSectionSize(28)
        self._char_table.setMinimumHeight(120)
        layout.addWidget(self._char_table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ " + self._t("Add Row"))
        add_btn.setProperty("chipButton", True)
        add_btn.clicked.connect(lambda: self._add_table_row(self._char_table, 3))
        del_btn = QPushButton("- " + self._t("Delete Row"))
        del_btn.setProperty("chipButton", True)
        del_btn.clicked.connect(lambda: self._del_table_row(self._char_table))
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _fill_terminology(self, layout: QVBoxLayout, term: dict = None):
        if term is None:
            term = {}
        entries = [{"original": k, "translation": v} for k, v in term.items()]
        self._term_table = _make_editable_glossary_table(entries)
        self._term_table.setMinimumHeight(100)
        layout.addWidget(self._term_table)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("+ " + self._t("Add Row"))
        add_btn.setProperty("chipButton", True)
        add_btn.clicked.connect(lambda: self._add_table_row(self._term_table, 2))
        del_btn = QPushButton("- " + self._t("Delete Row"))
        del_btn.setProperty("chipButton", True)
        del_btn.clicked.connect(lambda: self._del_table_row(self._term_table))
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _fill_style_guide(self, layout: QVBoxLayout, rules: list = None):
        layout.addWidget(_dim_label(self._t("One rule per line")))
        text = "\n".join(str(x) for x in rules) if rules else ""
        self._style_guide_edit = _styled_text_edit(text)
        self._style_guide_edit.setFixedHeight(100)
        layout.addWidget(self._style_guide_edit)

    def _fill_translation_rules(self, layout: QVBoxLayout, rules: list = None):
        layout.addWidget(_dim_label(self._t("One rule per line")))
        text = "\n".join(str(x) for x in rules) if rules else ""
        self._rules_edit = _styled_text_edit(text)
        self._rules_edit.setFixedHeight(100)
        layout.addWidget(self._rules_edit)

    def _fill_glossary(self, layout: QVBoxLayout, glossary: dict = None):
        if glossary is None:
            glossary = {}

        glossary_tabs = QTabWidget()
        glossary_tabs.setMinimumHeight(220)
        glossary_tabs.setStyleSheet(_prompt_tabs_style())
        self._glossary_tab_widget = glossary_tabs

        category_icons = {
            "Person": "👤", "Location": "📍", "Org": "🏢",
            "Item": "🔮", "Skill": "⚡", "Creature": "🐾",
        }

        all_cats = list(dict.fromkeys(
            [c for c in _GLOSSARY_CATEGORIES if c in glossary] +
            [c for c in glossary if c not in _GLOSSARY_CATEGORIES]
        ))
        if not all_cats:
            all_cats = list(_GLOSSARY_CATEGORIES)

        for cat_key in all_cats:
            entries = glossary.get(cat_key, [])
            if not isinstance(entries, list):
                entries = []
            icon = category_icons.get(cat_key, "📌")
            tab_page = QWidget()
            tab_lay = QVBoxLayout(tab_page)
            tab_lay.setContentsMargins(6, 6, 6, 6)
            tab_lay.setSpacing(6)

            tbl = _make_editable_glossary_table(entries)
            tbl.setMinimumHeight(120)
            self._glossary_tables[cat_key] = tbl
            tab_lay.addWidget(tbl)

            g_btn_row = QHBoxLayout()
            add_btn = QPushButton("+ " + self._t("Add Row"))
            add_btn.setProperty("chipButton", True)
            _tbl = tbl
            add_btn.clicked.connect(lambda checked=False, t=_tbl: self._add_table_row(t, 2))
            del_btn = QPushButton("- " + self._t("Delete Row"))
            del_btn.setProperty("chipButton", True)
            del_btn.clicked.connect(lambda checked=False, t=_tbl: self._del_table_row(t))
            g_btn_row.addWidget(add_btn)
            g_btn_row.addWidget(del_btn)
            g_btn_row.addStretch()
            tab_lay.addLayout(g_btn_row)

            glossary_tabs.addTab(tab_page, f"{icon} {self._t(cat_key)} ({len(entries)})")

        layout.addWidget(glossary_tabs)

    def _fill_output_format(self, layout: QVBoxLayout, text: str = ""):
        self._output_format_edit = _styled_text_edit(text)
        self._output_format_edit.setFixedHeight(60)
        layout.addWidget(self._output_format_edit)

    # ─── 字段操作：移动 & 删除 ─────────────────────────
    def _move_section(self, container: QWidget, direction: int):
        """direction: -1=上移, +1=下移"""
        idx = None
        for i, (k, c) in enumerate(self._section_containers):
            if c is container:
                idx = i
                break
        if idx is None:
            return
        new_idx = idx + direction
        if new_idx < 0 or new_idx >= len(self._section_containers):
            return

        # 交换 list
        self._section_containers[idx], self._section_containers[new_idx] = \
            self._section_containers[new_idx], self._section_containers[idx]

        # 从 layout 中移除并重新插入
        layout = self._template_layout
        layout.removeWidget(container)
        # 计算 new_idx 对应的 layout 位置
        _, other = self._section_containers[idx]  # 交换后 idx 位置是原来的邻居
        layout_pos = layout.indexOf(other)
        if direction < 0:
            # 上移：插到邻居前面
            layout.insertWidget(layout_pos, container)
        else:
            # 下移：插到邻居后面
            layout.insertWidget(layout_pos + 1, container)

    def _remove_section(self, container: QWidget, key: str):
        """删除字段区域并清空对应控件引用。"""
        # 从列表中移除
        self._section_containers = [(k, c) for k, c in self._section_containers if c is not container]

        # 从 layout 中移除
        self._template_layout.removeWidget(container)
        container.setParent(None)
        container.deleteLater()

        # 清空控件引用
        if key == "persona":
            self._persona_edit = None
        elif key == "project_title":
            self._title_edit = None
        elif key == "characters":
            self._char_table = None
        elif key == "terminology":
            self._term_table = None
        elif key == "style_guide":
            self._style_guide_edit = None
        elif key == "translation_rules":
            self._rules_edit = None
        elif key == "glossary":
            self._glossary_tables.clear()
            self._glossary_tab_widget = None
        elif key == "output_format":
            self._output_format_edit = None

    # ─── 添加字段菜单 ──────────────────────────────────
    _SECTION_DEFS = [
        ("persona",           "📋", "Persona"),
        ("project_title",     "📚", "Project Title"),
        ("characters",        "👤", "Characters"),
        ("terminology",       "📝", "Terminology"),
        ("style_guide",       "🎨", "Style Guide"),
        ("translation_rules", "📏", "Translation Rules"),
        ("glossary",          "📖", "Glossary"),
        ("output_format",     "📤", "Output Format"),
    ]

    def _get_existing_sections(self) -> set:
        return {k for k, _ in self._section_containers}

    def _show_add_section_menu(self):
        from PyQt6.QtWidgets import QMenu
        from PyQt6.QtGui import QAction
        menu = QMenu(self)
        menu.setStyleSheet(_menu_style())
        existing = self._get_existing_sections()
        has_items = False
        for key, icon, label in self._SECTION_DEFS:
            if key not in existing:
                action = QAction(f"{icon}  {self._t(label)}", self)
                action.triggered.connect(lambda checked=False, k=key: self._on_add_section(k))
                menu.addAction(action)
                has_items = True

        if not has_items:
            action = QAction(self._t("All sections added"), self)
            action.setEnabled(False)
            menu.addAction(action)

        menu.exec(self._add_section_btn.mapToGlobal(
            self._add_section_btn.rect().topLeft()
        ))

    def _on_add_section(self, key: str):
        """在"添加字段"按钮上方插入新的字段区域。"""
        self._insert_section(key, self._template_layout)

    # ─── 自由编辑 Tab ──────────────────────────────────
    def _build_free_tab(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(8, 8, 8, 8)
        page_layout.setSpacing(6)
        page_layout.addWidget(_dim_label(self._t("Edit the raw file content directly")))
        self._free_editor = _styled_text_edit(self._original_content)
        page_layout.addWidget(self._free_editor, 1)
        self._tabs.addTab(page, "📄 " + self._t("Raw Edit"))

    # ─── 表格行增删 ────────────────────────────────────
    @staticmethod
    def _add_table_row(table: QTableWidget, cols: int):
        row = table.rowCount()
        table.insertRow(row)
        for c in range(cols):
            table.setItem(row, c, QTableWidgetItem(""))

    @staticmethod
    def _del_table_row(table: QTableWidget):
        rows = sorted(set(idx.row() for idx in table.selectedIndexes()), reverse=True)
        if not rows:
            last = table.rowCount() - 1
            if last >= 0:
                rows = [last]
        for r in rows:
            table.removeRow(r)

    # ─── 从模板收集数据 ────────────────────────────────
    def _collect_template_data(self) -> dict:
        """从模板编辑控件收集数据，合并回 self._data。"""
        data = dict(self._data) if self._data else {}

        if self._persona_edit is not None:
            data["persona"] = self._persona_edit.toPlainText()

        if self._title_edit is not None:
            if "project_data" not in data:
                data["project_data"] = {}
            data["project_data"]["title"] = self._title_edit.text()

        if self._char_table is not None:
            chars = []
            for r in range(self._char_table.rowCount()):
                jp = (self._char_table.item(r, 0) or QTableWidgetItem("")).text()
                cn = (self._char_table.item(r, 1) or QTableWidgetItem("")).text()
                nicks_str = (self._char_table.item(r, 2) or QTableWidgetItem("")).text()
                nicks = [n.strip() for n in nicks_str.split(",") if n.strip()]
                if jp or cn:
                    chars.append({"jp_name": jp, "cn_name": cn, "nicknames": nicks})
            if "project_data" not in data:
                data["project_data"] = {}
            data["project_data"]["character_list"] = chars

        if self._term_table is not None:
            terms = {}
            for r in range(self._term_table.rowCount()):
                orig = (self._term_table.item(r, 0) or QTableWidgetItem("")).text()
                trans = (self._term_table.item(r, 1) or QTableWidgetItem("")).text()
                if orig:
                    terms[orig] = trans
            if "project_data" not in data:
                data["project_data"] = {}
            data["project_data"]["terminology"] = terms

        if self._style_guide_edit is not None:
            lines = [l for l in self._style_guide_edit.toPlainText().split("\n") if l.strip()]
            data["style_guide"] = lines

        if self._rules_edit is not None:
            lines = [l for l in self._rules_edit.toPlainText().split("\n") if l.strip()]
            data["translation_rules"] = lines

        if self._glossary_tables:
            glossary = data.get("glossary", {})
            if not isinstance(glossary, dict):
                glossary = {}
            for cat_key, tbl in self._glossary_tables.items():
                entries = []
                for r in range(tbl.rowCount()):
                    orig = (tbl.item(r, 0) or QTableWidgetItem("")).text()
                    trans = (tbl.item(r, 1) or QTableWidgetItem("")).text()
                    if orig:
                        entries.append({"original": orig, "translation": trans})
                glossary[cat_key] = entries
            data["glossary"] = glossary

        if self._output_format_edit is not None:
            data["output_format"] = self._output_format_edit.toPlainText()

        return data

    # ─── 保存 ──────────────────────────────────────────
    def _save(self):
        current_tab = self._tabs.currentIndex()

        # 判断用哪个 Tab 的内容
        if self._is_structured and current_tab == 0:
            # 模板编辑 → 收集数据 → 序列化
            data = self._collect_template_data()
            ext = os.path.splitext(self._file_path)[1].lower()
            try:
                if ext in (".yaml", ".yml"):
                    try:
                        import yaml
                        content = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
                    except ImportError:
                        content = json.dumps(data, indent=2, ensure_ascii=False)
                else:
                    content = json.dumps(data, indent=2, ensure_ascii=False)
            except Exception as e:
                self._status.setText(f"❌ {self._t('Serialize Error')}: {e}")
                self._status.setStyleSheet(_status_style("error"))
                return
        else:
            # 自由编辑
            content = self._free_editor.toPlainText()

            # 格式验证
            ext = os.path.splitext(self._file_path)[1].lower()
            if ext == ".json":
                try:
                    json.loads(content)
                except json.JSONDecodeError as e:
                    self._status.setText(f"❌ JSON {self._t('Format Error')}: {e}")
                    self._status.setStyleSheet(_status_style("error"))
                    return
            elif ext in (".yaml", ".yml"):
                try:
                    import yaml
                    yaml.safe_load(content)
                except ImportError:
                    pass
                except Exception as e:
                    self._status.setText(f"❌ YAML {self._t('Format Error')}: {e}")
                    self._status.setStyleSheet(_status_style("error"))
                    return

        # 写入文件
        try:
            with open(self._file_path, "w", encoding="utf-8") as f:
                f.write(content)
            self._status.setText(f"✅ {self._t('Saved successfully')}")
            self._status.setStyleSheet(_status_style("success"))
            self._original_content = content
            # 同步另一个 tab
            if self._is_structured and current_tab == 0:
                self._free_editor.setPlainText(content)
        except Exception as e:
            self._status.setText(f"❌ {self._t('Save failed')}: {e}")
            self._status.setStyleSheet(_status_style("error"))

    def get_was_modified(self) -> bool:
        if self._is_structured:
            # 简单比较自由编辑内容
            return self._free_editor.toPlainText() != self._original_content
        return self._free_editor.toPlainText() != self._original_content

