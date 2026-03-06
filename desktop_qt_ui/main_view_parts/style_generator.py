"""
Unified stylesheet generators for the Qt desktop UI.
"""

from __future__ import annotations

from main_view_parts.theme_colors import get_theme_colors


def generate_main_view_style(theme: str = "dark") -> str:
    c = get_theme_colors(theme)
    return f"""
        #main_view_root {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 {c["bg_gradient_start"]},
                                        stop:0.45 {c["bg_gradient_mid"]},
                                        stop:1 {c["bg_gradient_end"]});
        }}
        #main_view_root QWidget {{
            background: transparent;
        }}
        #main_view_root QWidget#content_page_translation,
        #main_view_root QWidget#content_page_settings,
        #main_view_root QWidget#content_page_env,
        #main_view_root QWidget#content_page_prompts,
        #main_view_root QWidget#content_page_fonts {{
            background: transparent;
        }}
        #main_view_root QLabel {{
            color: {c["text_primary"]};
        }}

        #main_view_splitter::handle:horizontal {{
            background: {c["splitter_handle"]};
            width: 6px;
            margin: 6px 0;
            border-radius: 3px;
        }}
        #main_view_splitter::handle:horizontal:hover {{
            background: {c["splitter_handle_hover"]};
        }}

        #sidebar_panel {{
            background: {c["bg_sidebar"]};
            border-right: 1px solid {c["border_sidebar"]};
        }}
        #sidebar_brand {{
            color: {c["text_brand"]};
            font-size: 17px;
            font-weight: 800;
            padding: 8px 6px 10px 6px;
        }}
        #sidebar_divider {{
            background: {c["divider_sidebar"]};
            max-height: 1px;
            border: none;
            margin: 8px 2px;
        }}
        #sidebar_group_label {{
            color: {c["text_sidebar_group"]};
            font-size: 10px;
            font-weight: 700;
            padding: 8px 6px 2px 6px;
        }}
        #sidebar_panel QPushButton[navButton="true"],
        #sidebar_panel QPushButton[navActionButton="true"] {{
            background: transparent;
            border: 1px solid transparent;
            border-radius: 10px;
            color: {c["text_secondary"]};
            text-align: left;
            padding: 10px 12px;
            font-size: 13px;
            font-weight: 600;
        }}
        #sidebar_panel QPushButton[navButton="true"]:hover,
        #sidebar_panel QPushButton[navActionButton="true"]:hover {{
            background: {c["nav_hover_bg"]};
            border-color: {c["nav_hover_border"]};
            color: {c["text_accent"]};
        }}
        #sidebar_panel QPushButton[navButton="true"]:checked {{
            background: {c["nav_checked_bg"]};
            border-color: {c["nav_checked_border"]};
            color: {c["text_bright"]};
        }}
        #sidebar_panel QPushButton[navActionButton="true"] {{
            margin-top: 2px;
        }}

        #content_panel {{
            background: transparent;
        }}
        #content_vertical_splitter::handle:vertical {{
            background: {c["splitter_handle"]};
            height: 6px;
            margin: 0 18px;
            border-radius: 3px;
        }}
        #content_vertical_splitter::handle:vertical:hover {{
            background: {c["splitter_handle_hover"]};
        }}

        #header_card,
        QGroupBox#section_card,
        #settings_desc_panel,
        #log_container {{
            background: {c["bg_header_card"]};
            border: 1px solid {c["border_card"]};
            border-radius: 14px;
        }}
        QGroupBox#section_card {{
            margin-top: 12px;
            padding: 12px;
        }}
        QGroupBox#section_card::title {{
            color: {c["text_desc_name"]};
            font-size: 13px;
            font-weight: 700;
        }}
        #page_title {{
            color: {c["text_page_title"]};
            font-size: 18px;
            font-weight: 800;
        }}
        #page_subtitle {{
            color: {c["text_page_subtitle"]};
            font-size: 12px;
        }}
        #row_label {{
            color: {c["text_row_label"]};
            font-size: 12px;
            font-weight: 700;
        }}
        #inline_toolbar {{
            background: transparent;
        }}

        #translation_file_list,
        #asset_list {{
            background: {c["bg_list"]};
            border: 1px solid {c["border_list"]};
            border-radius: 12px;
            padding: 6px;
        }}
        #translation_file_list::item,
        #asset_list::item {{
            border-radius: 8px;
            padding: 4px;
            margin: 1px 0;
        }}
        #translation_file_list::item:hover,
        #asset_list::item:hover {{
            background: {c["list_item_hover"]};
        }}
        #translation_file_list::item:selected,
        #asset_list::item:selected {{
            background: {c["list_item_selected"]};
        }}
        #translation_file_list QWidget#file_item_root,
        #asset_list QWidget#file_item_root {{
            background: transparent;
            border-radius: 8px;
        }}
        #translation_file_list QLabel#file_item_name_label,
        #asset_list QLabel#file_item_name_label {{
            color: {c["text_accent"]};
            font-weight: 600;
        }}
        #translation_file_list QPushButton#file_item_remove_button,
        #asset_list QPushButton#file_item_remove_button {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            color: {c["btn_soft_text"]};
            border-radius: 10px;
            min-width: 20px;
            max-width: 20px;
            min-height: 20px;
            max-height: 20px;
            padding: 0px;
            font-size: 11px;
            font-weight: 700;
        }}
        #translation_file_list QPushButton#file_item_remove_button:hover,
        #asset_list QPushButton#file_item_remove_button:hover {{
            background: {c["danger_bg"]};
            border-color: {c["danger_border"]};
            color: {c["danger_text"]};
        }}

        #main_view_root QLineEdit,
        #main_view_root QComboBox {{
            background: {c["bg_input"]};
            border: 1px solid {c["border_input"]};
            border-radius: 9px;
            color: {c["text_accent"]};
            padding: 7px 10px;
            min-height: 22px;
        }}
        #main_view_root QLineEdit:hover,
        #main_view_root QComboBox:hover {{
            border-color: {c["border_input_hover"]};
        }}
        #main_view_root QLineEdit:focus,
        #main_view_root QComboBox:focus {{
            border-color: {c["border_input_focus"]};
            background: {c["bg_input_focus"]};
        }}
        #main_view_root QComboBox {{
            padding-right: 24px;
        }}
        #main_view_root QComboBox::drop-down {{
            width: 24px;
            border: none;
        }}
        #main_view_root QComboBox QAbstractItemView {{
            background: {c["bg_dropdown"]};
            color: {c["text_accent"]};
            border: 1px solid {c["border_input"]};
            selection-background-color: {c["dropdown_selection"]};
            selection-color: {c["list_item_selected_text"]};
        }}

        #main_view_root QPushButton {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            border-radius: 10px;
            color: {c["btn_soft_text"]};
            padding: 8px 12px;
            font-weight: 700;
        }}
        #main_view_root QPushButton:hover {{
            background: {c["btn_soft_hover"]};
            border-color: {c["border_input_hover"]};
        }}
        #main_view_root QPushButton:pressed {{
            background: {c["btn_soft_pressed"]};
            border-color: {c["btn_soft_checked_border"]};
        }}
        #main_view_root QPushButton[chipButton="true"] {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            color: {c["btn_soft_text"]};
            font-weight: 600;
            padding: 7px 10px;
        }}
        #main_view_root QPushButton[chipButton="true"]:hover {{
            background: {c["btn_soft_hover"]};
            border-color: {c["border_input_hover"]};
            color: {c["btn_soft_text"]};
        }}
        #main_view_root QPushButton[primaryAction="true"] {{
            border-radius: 12px;
            padding: 10px 18px;
            font-weight: 800;
        }}
        #start_translation_button {{
            min-height: 44px;
            border-radius: 12px;
            padding: 10px 18px;
            font-size: 14px;
            font-weight: 800;
            background: {c["btn_primary_bg"]};
            border: 1px solid {c["btn_primary_border"]};
            color: {c["btn_primary_text"]};
        }}
        #start_translation_button:hover {{
            background: {c["btn_primary_hover"]};
        }}
        #start_translation_button:pressed {{
            background: {c["btn_primary_pressed"]};
        }}
        #start_translation_button[translationState="stop"] {{
            background: {c["danger_bg"]};
            border: 1px solid {c["danger_border"]};
            color: {c["danger_text"]};
        }}
        #start_translation_button[translationState="stop"]:hover {{
            background: {c["danger_hover"]};
        }}
        #start_translation_button[translationState="stopping"] {{
            background: {c["btn_disabled_bg"]};
            border-color: {c["btn_disabled_border"]};
            color: {c["text_disabled"]};
        }}

        #translation_progress_bar {{
            min-height: 24px;
            border-radius: 8px;
            text-align: center;
            padding: 0px 4px;
        }}
        #translation_progress_bar[progressState="idle"] {{
            background: {c["bg_input"]};
            border: 1px solid {c["border_list"]};
            color: {c["text_muted"]};
        }}
        #translation_progress_bar[progressState="idle"]::chunk {{
            background: {c["scroll_handle"]};
            border-radius: 8px;
        }}
        #translation_progress_bar[progressState="active"] {{
            background: {c["bg_input_focus"]};
            border: 1px solid {c["cta_border"]};
            color: {c["text_bright"]};
        }}
        #translation_progress_bar[progressState="active"]::chunk {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 {c["cta_gradient_start"]}, stop:1 {c["cta_gradient_end"]});
            border-radius: 8px;
        }}

        #settings_tabs::pane,
        #settings_tab_widget::pane {{
            border: 1px solid {c["border_card"]};
            border-radius: 12px;
            background: {c["bg_panel"]};
            padding: 2px;
        }}
        #settings_tabs > QTabBar::tab,
        #settings_tab_widget > QTabBar::tab {{
            background: {c["tab_bg"]};
            border: 1px solid {c["border_tab"]};
            border-bottom: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            color: {c["text_muted"]};
            padding: 9px 16px;
            margin-right: 3px;
            font-weight: 700;
        }}
        #settings_tabs > QTabBar::tab:selected,
        #settings_tab_widget > QTabBar::tab:selected {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {c["tab_selected_start"]}, stop:1 {c["tab_selected_end"]});
            color: {c["text_bright"]};
            border-color: {c["border_tab_selected"]};
        }}
        #settings_tabs > QTabBar::tab:hover:!selected,
        #settings_tab_widget > QTabBar::tab:hover:!selected {{
            background: {c["tab_hover"]};
            color: {c["text_accent"]};
        }}

        #settings_scroll_area {{
            background: transparent;
            border: none;
        }}
        #settings_scroll_content {{
            background: transparent;
        }}
        #settings_scroll_content QLabel {{
            color: {c["text_settings_label"]};
            font-size: 12px;
            padding: 2px 0px;
        }}
        #settings_scroll_content QLabel#settings_form_label {{
            color: {c["text_row_label"]};
            font-weight: 700;
        }}
        #settings_scroll_content QLineEdit,
        #settings_scroll_content QComboBox {{
            background: {c["bg_settings_input"]};
            border: 1px solid {c["border_settings_input"]};
            border-radius: 8px;
            color: {c["text_accent"]};
            padding: 7px 10px;
        }}
        #settings_scroll_content QLineEdit:hover,
        #settings_scroll_content QComboBox:hover {{
            border-color: {c["border_settings_input_hover"]};
        }}
        #settings_scroll_content QLineEdit:focus,
        #settings_scroll_content QComboBox:focus {{
            border-color: {c["border_input_focus"]};
            background: {c["bg_input_focus"]};
        }}
        #settings_scroll_content QPushButton {{
            background: {c["btn_settings_bg"]};
            border: 1px solid {c["btn_settings_border"]};
            color: {c["text_secondary"]};
            padding: 6px 12px;
            border-radius: 7px;
            font-size: 12px;
            font-weight: 600;
        }}
        #settings_scroll_content QPushButton:hover {{
            background: {c["btn_settings_hover"]};
            border-color: {c["btn_settings_hover_border"]};
        }}

        #settings_desc_panel {{
            background: {c["settings_desc_panel_bg"]};
            border: 1px solid {c["desc_panel_border"]};
            border-radius: 14px;
        }}
        #settings_desc_header {{
            color: {c["text_desc_header"]};
            font-size: 14px;
            font-weight: 800;
        }}
        #settings_desc_divider {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                        stop:0 {c["divider_desc"]}, stop:1 {c["divider_desc_end"]});
            max-height: 1px;
            border: none;
        }}
        #settings_desc_name {{
            color: {c["text_desc_name"]};
            font-size: 15px;
            font-weight: 800;
            padding-top: 4px;
        }}
        #settings_desc_key {{
            color: {c["text_desc_key"]};
            font-size: 11px;
            font-family: "Consolas", "Microsoft YaHei UI", monospace;
            padding: 2px 0px;
        }}
        #settings_desc_text {{
            color: {c["text_desc_text"]};
            font-size: 13px;
            padding: 6px 0px;
        }}
        #settings_body_splitter::handle:horizontal {{
            background: {c["splitter_handle"]};
            width: 6px;
            margin: 18px 0;
            border-radius: 3px;
        }}
        #settings_body_splitter::handle:horizontal:hover {{
            background: {c["splitter_handle_hover"]};
        }}

        #font_preview_name {{
            color: {c["text_desc_name"]};
            font-size: 15px;
            font-weight: 800;
        }}
        #font_preview_text {{
            color: {c["text_primary"]};
            padding: 4px 2px;
        }}

        #main_view_root QScrollBar:vertical,
        #main_view_root QScrollBar:horizontal {{
            background: {c["bg_scroll"]};
            border-radius: 6px;
            border: none;
        }}
        #main_view_root QScrollBar::handle:vertical,
        #main_view_root QScrollBar::handle:horizontal {{
            background: {c["scroll_handle"]};
            border-radius: 6px;
        }}
        #main_view_root QScrollBar::handle:vertical:hover,
        #main_view_root QScrollBar::handle:horizontal:hover {{
            background: {c["scroll_handle_hover"]};
        }}
        #main_view_root QScrollBar::add-line,
        #main_view_root QScrollBar::sub-line {{
            width: 0px;
            height: 0px;
        }}
        #main_view_root QMenu {{
            background: {c["bg_surface_raised"]};
            color: {c["text_accent"]};
            border: 1px solid {c["border_card"]};
            border-radius: 10px;
            padding: 6px 4px;
        }}
        #main_view_root QMenu::item {{
            background: transparent;
            color: {c["text_accent"]};
            padding: 7px 14px;
            margin: 1px 4px;
            border-radius: 6px;
        }}
        #main_view_root QMenu::item:selected {{
            background: {c["tab_hover"]};
            color: {c["text_bright"]};
        }}
    """


def generate_editor_style(theme: str = "dark") -> str:
    c = get_theme_colors(theme)
    return f"""
        #editor_view_root {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 {c["bg_gradient_start"]},
                                        stop:0.45 {c["bg_gradient_mid"]},
                                        stop:1 {c["bg_gradient_end"]});
        }}
        #editor_view_root QWidget {{
            background: transparent;
        }}

        #editor_toolbar {{
            background: {c["bg_toolbar"]};
            border-bottom: 1px solid {c["bg_toolbar_border"]};
        }}
        #editor_toolbar QToolButton {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            border-radius: 10px;
            color: {c["btn_soft_text"]};
            padding: 4px 11px;
            font-size: 11px;
            font-weight: 700;
            min-height: 20px;
            max-height: 28px;
        }}
        #editor_toolbar QToolButton:hover {{
            background: {c["btn_soft_hover"]};
            border-color: {c["border_input_hover"]};
            color: {c["btn_soft_text"]};
        }}
        #editor_toolbar QToolButton:pressed {{
            background: {c["btn_soft_pressed"]};
            border-color: {c["btn_soft_checked_border"]};
            color: {c["btn_soft_text"]};
        }}
        #editor_toolbar QToolButton:checked {{
            background: {c["btn_soft_checked_bg"]};
            border-color: {c["btn_soft_checked_border"]};
            color: {c["btn_soft_text"]};
        }}
        #editor_toolbar QToolButton[variant="accent"],
        #editor_toolbar QToolButton[primaryAction="true"] {{
            background: {c["btn_primary_bg"]};
            border: 1px solid {c["btn_primary_border"]};
            color: {c["btn_primary_text"]};
            border-radius: 9px;
            padding: 5px 14px;
            min-height: 22px;
            font-size: 12px;
            font-weight: 800;
        }}
        #editor_toolbar QToolButton[variant="accent"]:hover,
        #editor_toolbar QToolButton[primaryAction="true"]:hover {{
            background: {c["btn_primary_hover"]};
        }}
        #editor_toolbar QToolButton[variant="accent"]:pressed,
        #editor_toolbar QToolButton[primaryAction="true"]:pressed {{
            background: {c["btn_primary_pressed"]};
        }}
        #editor_export_button {{
            min-width: 98px;
        }}
        #editor_toolbar QLabel {{
            color: {c["text_secondary"]};
            font-size: 11px;
            padding: 0 2px;
        }}
        #editor_toolbar QComboBox {{
            background: {c["bg_input"]};
            border: 1px solid {c["border_input"]};
            border-radius: 7px;
            color: {c["text_accent"]};
            padding: 3px 20px 3px 6px;
            min-height: 18px;
            max-height: 26px;
            font-size: 11px;
        }}
        #editor_toolbar QComboBox:hover {{
            border-color: {c["border_input_hover"]};
        }}
        #editor_toolbar QComboBox:focus {{
            border-color: {c["border_input_focus"]};
            background: {c["bg_input_focus"]};
        }}
        #editor_toolbar QComboBox QAbstractItemView {{
            background: {c["bg_dropdown"]};
            color: {c["text_accent"]};
            border: 1px solid {c["border_input"]};
            selection-background-color: {c["dropdown_selection"]};
            selection-color: {c["list_item_selected_text"]};
        }}
        #editor_toolbar QSlider::groove:horizontal {{
            background: {c["slider_groove"]};
            height: 4px;
            border-radius: 2px;
        }}
        #editor_toolbar QSlider::handle:horizontal {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 {c["slider_handle_start"]}, stop:1 {c["slider_handle_end"]});
            width: 14px;
            height: 14px;
            margin: -5px 0;
            border-radius: 7px;
            border: 1px solid {c["slider_handle_border"]};
        }}
        #editor_toolbar QSlider::handle:horizontal:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 {c["slider_handle_hover_start"]}, stop:1 {c["slider_handle_hover_end"]});
        }}
        #editor_toolbar QFrame#editor_toolbar_separator {{
            color: {c["separator_color"]};
        }}

        #editor_main_splitter::handle:horizontal {{
            background: {c["splitter_handle"]};
            width: 6px;
            margin: 12px 0;
            border-radius: 3px;
        }}
        #editor_main_splitter::handle:horizontal:hover {{
            background: {c["splitter_handle_hover"]};
        }}

        #editor_left_tabs::pane {{
            border: 1px solid {c["border_card"]};
            border-radius: 12px;
            background: {c["bg_panel"]};
            padding: 3px;
        }}
        #editor_left_tabs > QTabBar::tab {{
            background: {c["tab_bg"]};
            border: 1px solid {c["border_tab"]};
            border-bottom: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            color: {c["text_muted"]};
            padding: 8px 12px;
            margin-right: 3px;
            font-weight: 700;
        }}
        #editor_left_tabs > QTabBar::tab:selected {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                        stop:0 {c["tab_selected_start"]}, stop:1 {c["tab_selected_end"]});
            color: {c["text_bright"]};
            border-color: {c["border_tab_selected"]};
        }}
        #editor_left_tabs > QTabBar::tab:hover:!selected {{
            background: {c["tab_hover"]};
            color: {c["text_accent"]};
        }}

        #editor_translation_page,
        #editor_property_panel {{
            background: transparent;
        }}
        #editor_search_bar {{
            background: {c["bg_surface_soft"]};
            border: 1px solid {c["border_subtle"]};
            border-radius: 10px;
        }}
        #editor_search_bar QPushButton {{
            min-height: 28px;
            padding: 5px 10px;
        }}

        #editor_view_root QGroupBox {{
            background: {c["bg_card"]};
            border: 1px solid {c["bg_card_border"]};
            border-radius: 12px;
            margin-top: 10px;
            padding: 10px;
            font-weight: 700;
            color: {c["text_card_title"]};
        }}
        #editor_view_root QGroupBox::title {{
            padding: 0 8px;
            margin-left: 10px;
            color: {c["text_card_title"]};
        }}

        #editor_property_scroll {{
            background: transparent;
            border: none;
        }}
        #editor_property_content {{
            background: transparent;
        }}
        #editor_property_content QLabel {{
            color: {c["text_secondary"]};
            font-size: 12px;
        }}
        #editor_property_content QLabel#editor_brush_size_value_label {{
            color: {c["text_muted"]};
            font-size: 11px;
            font-weight: 700;
        }}
        QWidget#color_picker_root {{
            background: {c["bg_input"]};
            border: 1px solid {c["border_input"]};
            border-radius: 10px;
        }}
        QWidget#color_picker_root:hover {{
            border-color: {c["border_input_hover"]};
        }}
        QWidget#color_picker_root QLabel#color_picker_rgb_label {{
            color: {c["text_muted"]};
        }}
        QWidget#color_picker_root QToolButton#color_picker_saved_button {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            color: {c["btn_soft_text"]};
            border-radius: 8px;
        }}
        QWidget#color_picker_root QToolButton#color_picker_saved_button:hover {{
            background: {c["btn_soft_hover"]};
            border-color: {c["border_input_hover"]};
        }}

        #editor_view_root QLineEdit,
        #editor_view_root QComboBox,
        #editor_view_root QSpinBox,
        #editor_view_root QDoubleSpinBox {{
            background: {c["bg_input"]};
            border: 1px solid {c["border_input"]};
            border-radius: 8px;
            color: {c["text_accent"]};
            padding: 6px 8px;
            min-height: 18px;
        }}
        #editor_view_root QLineEdit:hover,
        #editor_view_root QComboBox:hover,
        #editor_view_root QSpinBox:hover,
        #editor_view_root QDoubleSpinBox:hover {{
            border-color: {c["border_input_hover"]};
        }}
        #editor_view_root QLineEdit:focus,
        #editor_view_root QComboBox:focus,
        #editor_view_root QSpinBox:focus,
        #editor_view_root QDoubleSpinBox:focus {{
            border-color: {c["border_input_focus"]};
            background: {c["bg_input_focus"]};
        }}
        #editor_view_root QTextEdit {{
            background: {c["bg_text_edit"]};
            border: 1px solid {c["border_settings_input"]};
            border-radius: 10px;
            color: {c["text_accent"]};
            padding: 8px;
        }}
        #editor_view_root QTextEdit:focus {{
            border-color: {c["border_input_focus"]};
            background: {c["bg_input_focus"]};
        }}

        #editor_view_root QPushButton {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            border-radius: 10px;
            color: {c["btn_soft_text"]};
            padding: 6px 10px;
            font-weight: 700;
        }}
        #editor_view_root QPushButton:hover {{
            background: {c["btn_soft_hover"]};
            border-color: {c["border_input_hover"]};
        }}
        #editor_view_root QPushButton:pressed {{
            background: {c["btn_soft_pressed"]};
            border-color: {c["btn_soft_checked_border"]};
        }}
        #editor_view_root QPushButton:disabled {{
            background: {c["btn_disabled_bg"]};
            border-color: {c["btn_disabled_border"]};
            color: {c["text_disabled"]};
        }}
        #editor_view_root QPushButton:checked {{
            background: {c["btn_soft_checked_bg"]};
            border-color: {c["btn_soft_checked_border"]};
            color: {c["btn_soft_text"]};
        }}
        #editor_view_root QPushButton[chipButton="true"] {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            color: {c["btn_soft_text"]};
            font-weight: 600;
            padding: 5px 8px;
        }}
        #editor_view_root QPushButton[chipButton="true"]:hover {{
            background: {c["btn_soft_hover"]};
            border-color: {c["border_input_hover"]};
            color: {c["btn_soft_text"]};
        }}
        #editor_view_root QPushButton[softAction="true"] {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            border-radius: 10px;
            color: {c["btn_soft_text"]};
            padding: 7px 11px;
            font-weight: 700;
            min-height: 30px;
        }}
        #editor_view_root QPushButton[softAction="true"]:hover {{
            background: {c["btn_soft_hover"]};
            border-color: {c["border_input_hover"]};
            color: {c["btn_soft_text"]};
        }}
        #editor_view_root QPushButton[softAction="true"]:pressed {{
            background: {c["btn_soft_pressed"]};
            border-color: {c["btn_soft_checked_border"]};
            color: {c["btn_soft_text"]};
        }}
        #editor_view_root QPushButton[softAction="true"]:checked {{
            background: {c["btn_soft_checked_bg"]};
            border-color: {c["btn_soft_checked_border"]};
            color: {c["btn_soft_text"]};
        }}
        #editor_view_root QPushButton[primaryAction="true"] {{
            background: {c["btn_primary_bg"]};
            border: 1px solid {c["btn_primary_border"]};
            border-radius: 10px;
            color: {c["btn_primary_text"]};
            padding: 7px 12px;
            font-size: 12px;
            font-weight: 800;
            min-height: 30px;
        }}
        #editor_view_root QPushButton[primaryAction="true"]:hover {{
            background: {c["btn_primary_hover"]};
        }}
        #editor_view_root QPushButton[primaryAction="true"]:pressed {{
            background: {c["btn_primary_pressed"]};
        }}
        #editor_view_root QPushButton[variant="danger"] {{
            background: {c["danger_bg"]};
            border: 1px solid {c["danger_border"]};
            color: {c["danger_text"]};
        }}
        #editor_view_root QPushButton[variant="danger"]:hover {{
            background: {c["danger_hover"]};
        }}
        #editor_view_root QPushButton[editorToolButton="true"] {{
            min-width: 0px;
            padding: 7px 10px;
        }}
        #editor_translate_button,
        #editor_recognize_button,
        #editor_copy_action_button,
        #editor_paste_action_button,
        #editor_delete_action_button,
        #editor_clear_masks_button {{
            min-height: 32px;
        }}
        #editor_apply_button {{
            background: {c["btn_primary_bg"]};
            border: 1px solid {c["btn_primary_border"]};
            color: {c["btn_primary_text"]};
            border-radius: 12px;
            font-size: 12px;
            font-weight: 800;
        }}
        #editor_apply_button:hover {{
            background: {c["btn_primary_hover"]};
        }}
        #editor_apply_button:pressed {{
            background: {c["btn_primary_pressed"]};
        }}

        #editor_center_panel {{
            background: {c["bg_canvas_overlay"]};
            border: 1px solid {c["border_card"]};
            border-radius: 12px;
        }}
        QGraphicsView#editor_graphics_view {{
            background: {c["bg_canvas"]};
            border: 1px solid {c["border_subtle"]};
            border-radius: 10px;
        }}
        QGraphicsView#editor_graphics_view:focus {{
            border-color: {c["border_input_focus"]};
        }}

        #editor_right_panel {{
            background: {c["bg_sidebar"]};
            border-left: 1px solid {c["border_sidebar"]};
        }}
        #editor_file_actions {{
            background: transparent;
        }}
        #editor_file_list,
        #editor_region_list {{
            background: {c["bg_list"]};
            border: 1px solid {c["border_list"]};
            border-radius: 12px;
            padding: 6px;
            outline: none;
        }}
        #editor_file_list::item,
        #editor_region_list::item {{
            border-radius: 8px;
            padding: 4px;
            margin: 1px 0;
        }}
        #editor_file_list::item:hover,
        #editor_region_list::item:hover {{
            background: {c["list_item_hover"]};
        }}
        #editor_file_list::item:selected,
        #editor_region_list::item:selected {{
            background: {c["list_item_selected"]};
        }}
        #editor_file_list QWidget#file_item_root {{
            background: transparent;
        }}
        #editor_file_list QLabel#file_item_name_label {{
            color: {c["text_accent"]};
            font-weight: 600;
        }}
        #editor_file_list QPushButton#file_item_remove_button {{
            background: {c["btn_soft_bg"]};
            border: 1px solid {c["btn_soft_border"]};
            color: {c["btn_soft_text"]};
            border-radius: 10px;
            min-width: 20px;
            max-width: 20px;
            min-height: 20px;
            max-height: 20px;
            padding: 0px;
        }}
        #editor_file_list QPushButton#file_item_remove_button:hover {{
            background: {c["danger_bg"]};
            border-color: {c["danger_border"]};
            color: {c["danger_text"]};
        }}

        #editor_view_root QCheckBox {{
            spacing: 8px;
            color: {c["text_primary"]};
        }}
        #editor_view_root QCheckBox::indicator {{
            width: 18px;
            height: 18px;
            border-radius: 4px;
            border: 1px solid {c["checkbox_border"]};
            background: {c["checkbox_bg"]};
        }}
        #editor_view_root QCheckBox::indicator:checked {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 {c["checkbox_checked_start"]}, stop:1 {c["checkbox_checked_end"]});
            border-color: {c["checkbox_checked_border"]};
        }}
        #editor_view_root QCheckBox::indicator:hover {{
            border-color: {c["checkbox_hover_border"]};
        }}

        #editor_view_root QSlider::groove:horizontal {{
            background: {c["slider_groove"]};
            height: 4px;
            border-radius: 2px;
        }}
        #editor_view_root QSlider::handle:horizontal {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 {c["slider_handle_start"]}, stop:1 {c["slider_handle_end"]});
            width: 16px;
            height: 16px;
            margin: -6px 0;
            border-radius: 8px;
            border: 1px solid {c["slider_handle_border"]};
        }}
        #editor_view_root QSlider::handle:horizontal:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                        stop:0 {c["slider_handle_hover_start"]}, stop:1 {c["slider_handle_hover_end"]});
        }}

        #editor_view_root QListWidget,
        #editor_view_root QTreeWidget,
        #editor_view_root QTreeView,
        #editor_view_root QListView {{
            background: {c["bg_list"]};
            border: 1px solid {c["border_list"]};
            border-radius: 10px;
            color: {c["text_accent"]};
        }}
        #editor_view_root QScrollBar:vertical,
        #editor_view_root QScrollBar:horizontal {{
            background: {c["bg_scroll"]};
            border-radius: 6px;
        }}
        #editor_view_root QScrollBar::handle:vertical,
        #editor_view_root QScrollBar::handle:horizontal {{
            background: {c["scroll_handle"]};
            border-radius: 6px;
        }}
        #editor_view_root QScrollBar::handle:vertical:hover,
        #editor_view_root QScrollBar::handle:horizontal:hover {{
            background: {c["scroll_handle_hover"]};
        }}
        #editor_view_root QScrollBar::add-line,
        #editor_view_root QScrollBar::sub-line {{
            width: 0px;
            height: 0px;
        }}
        #editor_view_root QMenu {{
            background: {c["bg_surface_raised"]};
            color: {c["text_accent"]};
            border: 1px solid {c["border_card"]};
            border-radius: 10px;
            padding: 6px 4px;
        }}
        #editor_view_root QMenu::item {{
            background: transparent;
            color: {c["text_accent"]};
            padding: 7px 14px;
            margin: 1px 4px;
            border-radius: 6px;
        }}
        #editor_view_root QMenu::item:selected {{
            background: {c["tab_hover"]};
            color: {c["text_bright"]};
        }}
    """
