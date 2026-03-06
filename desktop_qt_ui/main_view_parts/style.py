from main_view_parts.style_generator import generate_main_view_style
from main_view_parts.theme import apply_widget_stylesheet


def apply_reference_ui_style(self, theme: str = "dark"):
    """主界面局部样式：根据主题应用配色。"""
    apply_widget_stylesheet(self, generate_main_view_style(theme))
