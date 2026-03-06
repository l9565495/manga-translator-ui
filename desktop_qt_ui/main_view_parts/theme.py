"""
Theme runtime helpers.

This module owns:
- current theme tracking
- palette generation
- application-level shared stylesheet
- lightweight repolish helpers for local widget stylesheets
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QWidget

from main_view_parts.theme_colors import get_theme_colors

_VALID_THEMES = {"light", "dark", "gray"}
_CURRENT_THEME = "light"


def _to_qcolor(value: str) -> QColor:
    """Parse Qt-safe colors, including CSS-like rgb()/rgba() strings."""
    color = QColor(value)
    if color.isValid():
        return color

    normalized = value.strip().lower()
    if normalized.startswith("rgba(") and normalized.endswith(")"):
        parts = [part.strip() for part in normalized[5:-1].split(",")]
        if len(parts) == 4:
            red = int(float(parts[0]))
            green = int(float(parts[1]))
            blue = int(float(parts[2]))
            alpha_raw = float(parts[3])
            alpha = int(round(alpha_raw * 255)) if alpha_raw <= 1 else int(round(alpha_raw))
            return QColor(red, green, blue, max(0, min(255, alpha)))

    if normalized.startswith("rgb(") and normalized.endswith(")"):
        parts = [part.strip() for part in normalized[4:-1].split(",")]
        if len(parts) == 3:
            red = int(float(parts[0]))
            green = int(float(parts[1]))
            blue = int(float(parts[2]))
            return QColor(red, green, blue)

    return QColor("#000000")


def set_current_theme(theme: str) -> None:
    global _CURRENT_THEME
    _CURRENT_THEME = theme if theme in _VALID_THEMES else "light"


def get_current_theme() -> str:
    return _CURRENT_THEME


def get_current_theme_colors() -> dict:
    return get_theme_colors(_CURRENT_THEME)


def build_theme_palette(theme: str) -> QPalette:
    c = get_theme_colors(theme)
    palette = QPalette()

    active_roles = {
        QPalette.ColorRole.Window: c["bg_window_shell"],
        QPalette.ColorRole.WindowText: c["text_primary"],
        QPalette.ColorRole.Base: c["bg_input"],
        QPalette.ColorRole.AlternateBase: c["bg_surface_soft"],
        QPalette.ColorRole.ToolTipBase: c["bg_dropdown"],
        QPalette.ColorRole.ToolTipText: c["text_accent"],
        QPalette.ColorRole.Text: c["text_primary"],
        QPalette.ColorRole.Button: c["bg_surface_raised"],
        QPalette.ColorRole.ButtonText: c["text_accent"],
        QPalette.ColorRole.BrightText: c["text_bright"],
        QPalette.ColorRole.Light: c["bg_gradient_end"],
        QPalette.ColorRole.Midlight: c["border_input_hover"],
        QPalette.ColorRole.Dark: c["bg_gradient_start"],
        QPalette.ColorRole.Mid: c["border_list"],
        QPalette.ColorRole.Shadow: c["bg_gradient_start"],
        QPalette.ColorRole.Highlight: c["cta_gradient_start"],
        QPalette.ColorRole.HighlightedText: c["cta_text"],
        QPalette.ColorRole.Link: c["divider_accent_start"],
        QPalette.ColorRole.LinkVisited: c["divider_accent_end"],
        QPalette.ColorRole.PlaceholderText: c["text_muted"],
    }

    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        for role, value in active_roles.items():
            palette.setColor(group, role, _to_qcolor(value))

    disabled_roles = {
        QPalette.ColorRole.WindowText: c["text_disabled"],
        QPalette.ColorRole.Text: c["text_disabled"],
        QPalette.ColorRole.ButtonText: c["text_disabled"],
        QPalette.ColorRole.PlaceholderText: c["text_disabled"],
        QPalette.ColorRole.Button: c["btn_disabled_bg"],
        QPalette.ColorRole.Base: c["bg_input"],
        QPalette.ColorRole.Highlight: c["btn_disabled_border"],
        QPalette.ColorRole.HighlightedText: c["text_muted"],
    }
    for role, value in disabled_roles.items():
        palette.setColor(QPalette.ColorGroup.Disabled, role, _to_qcolor(value))

    accent_role = getattr(QPalette.ColorRole, "Accent", None)
    if accent_role is not None:
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            palette.setColor(group, accent_role, _to_qcolor(c["cta_gradient_start"]))
        palette.setColor(QPalette.ColorGroup.Disabled, accent_role, _to_qcolor(c["btn_disabled_border"]))

    return palette


def generate_application_stylesheet(theme: str) -> str:
    c = get_theme_colors(theme)
    return f"""
        QMainWindow, QDialog {{
            background: {c["bg_window_shell"]};
        }}
        QWidget {{
            font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
            font-size: 12px;
            color: {c["text_primary"]};
        }}
        QWidget:disabled {{
            color: {c["text_disabled"]};
        }}

        QToolTip {{
            background-color: {c["bg_surface_raised"]};
            color: {c["text_accent"]};
            border: 1px solid {c["border_card"]};
            border-radius: 10px;
            padding: 8px 12px;
            font-size: 12px;
            font-weight: 600;
        }}

        QMenu {{
            background: {c["bg_dropdown"]};
            color: {c["text_accent"]};
            border: 1px solid {c["border_card"]};
            border-radius: 10px;
            padding: 6px 4px;
        }}
        QMenu::item {{
            padding: 7px 16px;
            margin: 1px 4px;
            border-radius: 6px;
        }}
        QMenu::item:selected {{
            background: {c["tab_hover"]};
            color: {c["text_bright"]};
        }}
        QMenu::separator {{
            height: 1px;
            margin: 5px 10px;
            background: {c["divider_sub_line"]};
        }}

        QGroupBox {{
            background: {c["bg_card"]};
            border: 1px solid {c["bg_card_border"]};
            border-radius: 12px;
            margin-top: 12px;
            padding: 12px;
            font-weight: 600;
            color: {c["text_card_title"]};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            margin-left: 10px;
            padding: 0 8px;
            background: transparent;
            color: {c["text_card_title"]};
        }}

        QLineEdit,
        QTextEdit,
        QPlainTextEdit,
        QComboBox,
        QSpinBox,
        QDoubleSpinBox {{
            background: {c["bg_input"]};
            border: 1px solid {c["border_input"]};
            border-radius: 8px;
            color: {c["text_accent"]};
            padding: 7px 10px;
            selection-background-color: {c["dropdown_selection"]};
            selection-color: {c["list_item_selected_text"]};
        }}
        QLineEdit:hover,
        QTextEdit:hover,
        QPlainTextEdit:hover,
        QComboBox:hover,
        QSpinBox:hover,
        QDoubleSpinBox:hover {{
            border-color: {c["border_input_hover"]};
        }}
        QLineEdit:focus,
        QTextEdit:focus,
        QPlainTextEdit:focus,
        QComboBox:focus,
        QSpinBox:focus,
        QDoubleSpinBox:focus {{
            border-color: {c["border_input_focus"]};
            background: {c["bg_input_focus"]};
        }}
        QComboBox {{
            padding-right: 24px;
            min-height: 22px;
        }}
        QComboBox::drop-down {{
            border: none;
            width: 24px;
        }}
        QComboBox QAbstractItemView {{
            background: {c["bg_dropdown"]};
            color: {c["text_accent"]};
            border: 1px solid {c["border_input"]};
            selection-background-color: {c["dropdown_selection"]};
            selection-color: {c["list_item_selected_text"]};
            outline: none;
        }}

        QPushButton,
        QToolButton {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            border-radius: 10px;
            color: {c["btn_soft_text"]};
            padding: 7px 12px;
            font-weight: 700;
        }}
        QPushButton:hover,
        QToolButton:hover {{
            background: {c["btn_soft_hover"]};
            border-color: {c["border_input_hover"]};
        }}
        QPushButton:pressed,
        QToolButton:pressed {{
            background: {c["btn_soft_pressed"]};
            border-color: {c["btn_soft_checked_border"]};
        }}
        QPushButton:disabled,
        QToolButton:disabled {{
            background: {c["btn_disabled_bg"]};
            border-color: {c["btn_disabled_border"]};
            color: {c["text_disabled"]};
        }}
        QPushButton:checked,
        QToolButton:checked {{
            background: {c["btn_soft_checked_bg"]};
            border-color: {c["btn_soft_checked_border"]};
            color: {c["btn_soft_text"]};
        }}

        QPushButton[chipButton="true"],
        QToolButton[chipButton="true"] {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            color: {c["btn_soft_text"]};
            padding: 6px 10px;
            font-weight: 600;
        }}
        QPushButton[chipButton="true"]:hover,
        QToolButton[chipButton="true"]:hover {{
            background: {c["btn_soft_hover"]};
            border-color: {c["border_input_hover"]};
            color: {c["btn_soft_text"]};
        }}

        QPushButton[variant="accent"],
        QToolButton[variant="accent"] {{
            background: {c["btn_primary_bg"]};
            border: 1px solid {c["btn_primary_border"]};
            color: {c["btn_primary_text"]};
            border-radius: 10px;
            font-weight: 700;
        }}
        QPushButton[variant="accent"]:hover,
        QToolButton[variant="accent"]:hover {{
            background: {c["btn_primary_hover"]};
        }}
        QPushButton[variant="accent"]:pressed,
        QToolButton[variant="accent"]:pressed {{
            background: {c["btn_primary_pressed"]};
        }}

        QPushButton[variant="danger"],
        QToolButton[variant="danger"] {{
            background: {c["danger_bg"]};
            border: 1px solid {c["danger_border"]};
            color: {c["danger_text"]};
            font-weight: 700;
        }}
        QPushButton[variant="danger"]:hover,
        QToolButton[variant="danger"]:hover {{
            background: {c["danger_hover"]};
        }}

        QCheckBox {{
            spacing: 8px;
        }}
        QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 1px solid {c["checkbox_border"]};
            background: {c["checkbox_bg"]};
        }}
        QCheckBox::indicator:checked {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 {c["checkbox_checked_start"]}, stop:1 {c["checkbox_checked_end"]});
            border-color: {c["checkbox_checked_border"]};
        }}
        QCheckBox::indicator:hover {{
            border-color: {c["checkbox_hover_border"]};
        }}

        QSlider::groove:horizontal {{
            background: {c["slider_groove"]};
            height: 4px;
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 {c["slider_handle_start"]}, stop:1 {c["slider_handle_end"]});
            width: 14px;
            height: 14px;
            margin: -5px 0;
            border-radius: 7px;
            border: 1px solid {c["slider_handle_border"]};
        }}
        QSlider::handle:horizontal:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 {c["slider_handle_hover_start"]}, stop:1 {c["slider_handle_hover_end"]});
        }}

        QTabWidget::pane {{
            border: 1px solid {c["border_card"]};
            border-radius: 10px;
            background: {c["bg_panel"]};
        }}
        QTabBar::tab {{
            background: {c["tab_bg"]};
            border: 1px solid {c["border_tab"]};
            border-bottom: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            color: {c["text_muted"]};
            padding: 8px 14px;
            margin-right: 3px;
            font-weight: 600;
        }}
        QTabBar::tab:selected {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {c["tab_selected_start"]}, stop:1 {c["tab_selected_end"]});
            color: {c["text_bright"]};
            border-color: {c["border_tab_selected"]};
        }}
        QTabBar::tab:hover:!selected {{
            background: {c["tab_hover"]};
            color: {c["text_accent"]};
        }}

        QListWidget,
        QListView,
        QTreeWidget,
        QTreeView,
        QTableWidget,
        QTableView {{
            background: {c["bg_list"]};
            border: 1px solid {c["border_list"]};
            border-radius: 10px;
            color: {c["text_accent"]};
            outline: none;
        }}
        QListWidget::item,
        QListView::item,
        QTreeWidget::item,
        QTreeView::item {{
            padding: 6px 8px;
            border-radius: 6px;
        }}
        QListWidget::item:hover,
        QListView::item:hover,
        QTreeWidget::item:hover,
        QTreeView::item:hover {{
            background: {c["list_item_hover"]};
        }}
        QListWidget::item:selected,
        QListView::item:selected,
        QTreeWidget::item:selected,
        QTreeView::item:selected,
        QTableView::item:selected,
        QTableWidget::item:selected {{
            background: {c["list_item_selected"]};
            color: {c["list_item_selected_text"]};
        }}
        QHeaderView::section {{
            background: {c["bg_surface_soft"]};
            color: {c["text_secondary"]};
            border: none;
            border-bottom: 1px solid {c["border_subtle"]};
            padding: 8px 10px;
            font-weight: 600;
        }}

        QScrollArea {{
            background: transparent;
            border: none;
        }}
        QScrollBar:vertical,
        QScrollBar:horizontal {{
            background: {c["bg_scroll"]};
            border: none;
            border-radius: 6px;
        }}
        QScrollBar:vertical {{
            width: 10px;
        }}
        QScrollBar:horizontal {{
            height: 10px;
        }}
        QScrollBar::handle:vertical,
        QScrollBar::handle:horizontal {{
            background: {c["scroll_handle"]};
            border-radius: 6px;
            min-height: 24px;
            min-width: 24px;
        }}
        QScrollBar::handle:vertical:hover,
        QScrollBar::handle:horizontal:hover {{
            background: {c["scroll_handle_hover"]};
        }}
        QScrollBar::add-line,
        QScrollBar::sub-line {{
            width: 0px;
            height: 0px;
        }}

        QSplitter::handle {{
            background: {c["splitter_handle"]};
        }}
        QSplitter::handle:hover {{
            background: {c["splitter_handle_hover"]};
        }}

        QLabel[status="success"] {{
            color: {c["success_color"]};
        }}
        QLabel[status="error"] {{
            color: {c["danger_bg"]};
        }}
    """


def repolish_widget(widget: QWidget) -> None:
    try:
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)
        widget.update()
    except RuntimeError:
        return


def refresh_widget_tree(widget: QWidget) -> None:
    """Lightweight compatibility helper for widgets with direct local QSS."""
    repolish_widget(widget)
    for child in widget.findChildren(QWidget):
        try:
            if child.styleSheet():
                repolish_widget(child)
        except RuntimeError:
            continue


def apply_widget_stylesheet(widget: QWidget, stylesheet: str) -> None:
    """Apply a local stylesheet without walking the entire widget tree."""
    if widget.styleSheet() != stylesheet:
        widget.setStyleSheet(stylesheet)
    repolish_widget(widget)


def apply_application_theme(theme: str, app: QApplication | None = None) -> None:
    app = app or QApplication.instance()
    if app is None:
        return

    set_current_theme(theme)
    palette = build_theme_palette(theme)
    app.setPalette(palette)
    app.setStyleSheet(generate_application_stylesheet(theme))
