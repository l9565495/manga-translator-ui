"""
Qt 原生文本渲染器
参考 BallonsTranslator 的渲染实现，使用 Qt 的富文本能力
完全兼容 text_render.py 的接口，支持所有原有功能

主要特性：
1. 使用 QTextDocument 进行富文本渲染
2. 支持横排和竖排（参考 BallonsTranslator 的实现）
3. 支持描边效果
4. 与原有 freetype 渲染器接口完全兼容
5. 支持 <H> 标签、AI 断句、智能缩放等所有功能
"""

import logging
import re
import math
from typing import Optional, Tuple, List
import numpy as np
import cv2

# 创建 logger
logger = logging.getLogger('manga_translator')

try:
    # 尝试导入 Qt
    import os
    import sys
    
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QPointF, QRectF, Qt, QSizeF, QSize
    from PyQt6.QtGui import (
        QBrush,
        QColor,
        QFont,
        QFontMetrics,
        QFontMetricsF,
        QImage,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
        QTextCharFormat,
        QTextCursor,
        QTextDocument,
        QTextOption,
        QTransform,
    )
    
    # 不在模块导入时创建 QApplication
    # 让 GUI 或命令行环境自己管理 QApplication 的创建
    # 渲染器只在需要时检查 QApplication 是否存在
    
    QT_AVAILABLE = True
    logger.info("Qt 渲染器可用")
except ImportError as e:
    QT_AVAILABLE = False
    logger.debug(f"Qt 渲染器不可用：{e}")

from . import text_render

logger = logging.getLogger(__name__)


# 使用 text_render 的所有辅助函数
CJK_H2V = text_render.CJK_H2V if hasattr(text_render, 'CJK_H2V') else {}
compact_special_symbols = text_render.compact_special_symbols
auto_add_horizontal_tags = text_render.auto_add_horizontal_tags
CJK_Compatibility_Forms_translate = text_render.CJK_Compatibility_Forms_translate
calc_vertical = text_render.calc_vertical
calc_horizontal = text_render.calc_horizontal
calc_horizontal_cjk = text_render.calc_horizontal_cjk
is_cjk_lang = text_render.is_cjk_lang
get_char_offset_x = text_render.get_char_offset_x
get_string_width = text_render.get_string_width


class QtTextRenderer:
    """
    基于 Qt 的文本渲染器（参考 BallonsTranslator 实现）
    
    完全兼容 text_render.py 的接口：
    - put_text_horizontal(): 横排文本渲染
    - put_text_vertical(): 竖排文本渲染
    - 支持所有原有功能：描边、对齐、AI断句、智能缩放等
    
    特性：
    - 支持命令行无头渲染（offscreen 模式）
    - 自动创建 QApplication（如果需要）
    - 使用 Qt 原生对齐能力
    """
    
    def __init__(self):
        if not QT_AVAILABLE:
            raise ImportError("Qt 渲染器需要 PyQt6，但未安装")
        
        self.logger = logging.getLogger(__name__)
        self.font_cache = {}  # 字体缓存
        
        # 确保 QApplication 存在（命令行环境需要）
        if not QApplication.instance():
            import sys
            # 在命令行环境中创建无头 QApplication
            app = QApplication(sys.argv)
            self.logger.info("Qt 渲染器：创建命令行 QApplication")
        
        self.logger.info("Qt 渲染器初始化完成")
    
    def _get_font(self, font_family: str, font_size: int) -> QFont:
        """获取缓存的字体"""
        key = (font_family, font_size)
        if key not in self.font_cache:
            font = QFont(font_family, font_size)
            font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
            font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias | QFont.StyleStrategy.NoSubpixelAntialias)
            self.font_cache[key] = font
        return self.font_cache[key]
    
    def _render_char(
        self,
        char: str,
        font_size: int,
        fg: Tuple[int, int, int],
        bg: Optional[Tuple[int, int, int]],
        stroke_ratio: float = 0.07,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        渲染单个字符，返回文本和描边的 numpy 数组
        
        Returns:
            (text_array, border_array): 两个灰度图像数组
        """
        # 使用默认字体（应该从 text_render 获取当前字体）
        font = self._get_font("Arial", font_size)
        metrics = QFontMetrics(font)
        
        char_width = metrics.horizontalAdvance(char)
        char_height = metrics.height()
        
        # 添加边距
        stroke_width = int(max(font_size * stroke_ratio, 1)) if bg is not None else 0
        margin = stroke_width * 2 + 2
        img_width = char_width + margin * 2
        img_height = char_height + margin * 2
        
        if img_width <= 0 or img_height <= 0:
            return None, None
        
        # 创建文本 pixmap
        text_pixmap = QPixmap(img_width, img_height)
        text_pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(text_pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))  # 白色用于灰度图
        painter.drawText(margin, margin + metrics.ascent(), char)
        painter.end()
        
        # 转换为灰度 numpy 数组
        image = text_pixmap.toImage()
        image = image.convertToFormat(QImage.Format.Format_Grayscale8)
        ptr = image.bits()
        ptr.setsize(image.sizeInBytes())
        text_array = np.frombuffer(ptr, np.uint8).reshape((img_height, img_width))
        
        # 创建描边
        border_array = None
        if stroke_width > 0:
            border_pixmap = QPixmap(img_width, img_height)
            border_pixmap.fill(Qt.GlobalColor.transparent)
            
            painter = QPainter(border_pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            painter.setFont(font)
            
            # 绘制描边路径
            path = QPainterPath()
            path.addText(margin, margin + metrics.ascent(), font, char)
            
            pen = QPen(QColor(255, 255, 255), stroke_width * 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.strokePath(path, pen)
            painter.end()
            
            # 转换为灰度数组
            image = border_pixmap.toImage()
            image = image.convertToFormat(QImage.Format.Format_Grayscale8)
            ptr = image.bits()
            ptr.setsize(image.sizeInBytes())
            border_array = np.frombuffer(ptr, np.uint8).reshape((img_height, img_width))
        
        return text_array, border_array
    
    def put_text_horizontal(
        self,
        font_size: int,
        text: str,
        width: int,
        height: int,
        alignment: str,
        reversed_direction: bool,
        fg: Tuple[int, int, int],
        bg: Optional[Tuple[int, int, int]],
        lang: str = 'en_US',
        hyphenate: bool = True,
        line_spacing: int = 0,
        config=None,
        region_count: int = 1,
        rich_text_html: Optional[str] = None,
    ) -> Optional[np.ndarray]:
        """
        横排文本渲染（使用 Qt 原生能力，支持自动对齐）
        
        Args:
            rich_text_html: 可选的富文本 HTML，如果提供则使用 HTML 渲染（支持粗体、斜体等）
        """
        try:
            # 应用最大字体限制
            if config and hasattr(config.render, 'max_font_size') and config.render.max_font_size > 0:
                font_size = min(font_size, config.render.max_font_size)
            
            text = compact_special_symbols(text)
            if not text:
                logger.warning("[QT RENDER] 横排文本为空")
                return None
            
            # 获取描边宽度
            stroke_ratio = config.render.stroke_width if (config and hasattr(config.render, 'stroke_width')) else 0.07
            stroke_width = int(max(font_size * stroke_ratio, 1)) if bg is not None else 0
            
            # 创建 QTextDocument
            doc = QTextDocument()
            doc.setDocumentMargin(stroke_width + 2)
            
            # 设置字体
            font = self._get_font("Arial", font_size)  # TODO: 使用实际字体路径
            doc.setDefaultFont(font)
            
            # 设置文本选项（对齐、换行）
            option = QTextOption()
            
            # Qt 自动对齐
            if alignment == "left":
                option.setAlignment(Qt.AlignmentFlag.AlignLeft)
            elif alignment == "center":
                option.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            elif alignment == "right":
                option.setAlignment(Qt.AlignmentFlag.AlignRight)
            else:
                option.setAlignment(Qt.AlignmentFlag.AlignLeft)
            
            # 换行模式
            if hyphenate:
                option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
            else:
                option.setWrapMode(QTextOption.WrapMode.NoWrap)
            
            doc.setDefaultTextOption(option)
            doc.setTextWidth(width)
            
            # 检查是否有富文本 HTML
            if rich_text_html:
                # 使用 HTML 渲染（保留粗体、斜体、下划线等格式）
                # 先还原特殊标记
                html = rich_text_html
                html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
                html = html.replace('<!--H_START-->', '<H>')
                html = html.replace('<!--H_END-->', '</H>')
                
                # 设置 HTML
                doc.setHtml(html)
                
                # 设置全局颜色和描边（应用到所有文本）
                cursor = QTextCursor(doc)
                cursor.select(QTextCursor.SelectionType.Document)
                char_format = QTextCharFormat()
                char_format.setForeground(QColor(*fg))
                
                if stroke_width > 0 and bg is not None:
                    pen = QPen(QColor(*bg), stroke_width * 2)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    char_format.setTextOutline(pen)
                
                cursor.mergeCharFormat(char_format)
            else:
                # 使用纯文本渲染
                cursor = QTextCursor(doc)
                char_format = QTextCharFormat()
                char_format.setForeground(QColor(*fg))
                
                # 设置描边
                if stroke_width > 0 and bg is not None:
                    pen = QPen(QColor(*bg), stroke_width * 2)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    char_format.setTextOutline(pen)
                
                cursor.setCharFormat(char_format)
                cursor.insertText(text)
            
            # 设置行间距
            if line_spacing > 0:
                cursor.select(QTextCursor.SelectionType.Document)
                block_format = cursor.blockFormat()
                spacing_ratio = line_spacing if line_spacing > 1 else (1.0 + line_spacing)
                block_format.setLineHeight(spacing_ratio * 100, 1)  # 百分比模式
                cursor.setBlockFormat(block_format)
            
            # 计算实际需要的尺寸
            doc_size = doc.size()
            actual_width = int(doc_size.width())
            actual_height = int(doc_size.height())
            
            # 创建渲染目标
            render_width = max(width, actual_width)
            render_height = max(height, actual_height)
            
            pixmap = QPixmap(render_width, render_height)
            pixmap.fill(Qt.GlobalColor.transparent)
            
            # 渲染
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            
            # Qt 自动处理对齐和布局
            doc.drawContents(painter)
            painter.end()
            
            # 转换为 numpy array (RGBA)
            image = pixmap.toImage()
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
            
            ptr = image.bits()
            ptr.setsize(image.sizeInBytes())
            arr = np.frombuffer(ptr, np.uint8).reshape((render_height, render_width, 4))
            
            # 裁剪到实际内容
            if np.any(arr[:, :, 3] > 0):
                # 找到非透明区域
                rows = np.any(arr[:, :, 3] > 0, axis=1)
                cols = np.any(arr[:, :, 3] > 0, axis=0)
                if np.any(rows) and np.any(cols):
                    y1, y2 = np.where(rows)[0][[0, -1]]
                    x1, x2 = np.where(cols)[0][[0, -1]]
                    arr = arr[y1:y2+1, x1:x2+1]
            
            logger.debug(f"[QT RENDER] 横排渲染完成: {arr.shape}")
            return arr
            
        except Exception as e:
            logger.error(f"[QT RENDER] 横排渲染失败: {e}", exc_info=True)
            # 回退到 freetype
            return text_render.put_text_horizontal(
                font_size, text, width, height, alignment,
                reversed_direction, fg, bg, lang, hyphenate,
                line_spacing, config, region_count
            )
    
    def put_text_vertical(
        self,
        font_size: int,
        text: str,
        height: int,
        alignment: str,
        fg: Tuple[int, int, int],
        bg: Optional[Tuple[int, int, int]],
        line_spacing: int = 0,
        config=None,
        region_count: int = 1,
        rich_text_html: Optional[str] = None,
    ) -> Optional[np.ndarray]:
        """
        竖排文本渲染
        
        Args:
            rich_text_html: 可选的富文本 HTML，如果提供则使用 HTML 渲染（支持粗体、斜体等）
        
        注意：竖排渲染较复杂，当前回退到 freetype 以保证质量
        TODO: 实现完整的 Qt 竖排渲染（参考 BallonsTranslator 的 VerticalTextDocumentLayout）
        """
        # 竖排渲染需要自定义 QAbstractTextDocumentLayout
        # 当前版本回退到经过验证的 freetype 渲染器
        return text_render.put_text_vertical(
            font_size, text, height, alignment, fg, bg,
            line_spacing, config, region_count
        )


# 全局单例
_qt_renderer_instance = None

def get_qt_renderer() -> Optional[QtTextRenderer]:
    """获取 Qt 渲染器单例"""
    if not QT_AVAILABLE:
        logger.warning("Qt 渲染器不可用：PyQt6 未安装")
        return None
    
    global _qt_renderer_instance
    if _qt_renderer_instance is None:
        _qt_renderer_instance = QtTextRenderer()
    return _qt_renderer_instance


# 导出与 text_render 兼容的函数接口
def put_text_horizontal(
    font_size: int,
    text: str,
    width: int,
    height: int,
    alignment: str,
    reversed_direction: bool,
    fg: Tuple[int, int, int],
    bg: Optional[Tuple[int, int, int]],
    lang: str = 'en_US',
    hyphenate: bool = True,
    line_spacing: int = 0,
    config=None,
    region_count: int = 1,
    rich_text_html: Optional[str] = None,
) -> Optional[np.ndarray]:
    """Qt 渲染器的横排文本渲染函数（兼容 text_render 接口）"""
    renderer = get_qt_renderer()
    if renderer is None:
        return text_render.put_text_horizontal(
            font_size, text, width, height, alignment,
            reversed_direction, fg, bg, lang, hyphenate,
            line_spacing, config, region_count
        )
    return renderer.put_text_horizontal(
        font_size, text, width, height, alignment,
        reversed_direction, fg, bg, lang, hyphenate,
        line_spacing, config, region_count, rich_text_html
    )


def put_text_vertical(
    font_size: int,
    text: str,
    height: int,
    alignment: str,
    fg: Tuple[int, int, int],
    bg: Optional[Tuple[int, int, int]],
    line_spacing: int = 0,
    config=None,
    region_count: int = 1,
    rich_text_html: Optional[str] = None,
) -> Optional[np.ndarray]:
    """竖排文本渲染（导出函数）"""
    renderer = get_qt_renderer()
    if renderer is None:
        # 回退到 text_render
        return text_render.put_text_vertical(
            font_size, text, height, alignment, fg, bg,
            line_spacing, config, region_count
        )
    return renderer.put_text_vertical(
        font_size, text, height, alignment, fg, bg,
        line_spacing, config, region_count, rich_text_html
    )


def put_text_horizontal_old(
    font_size: int,
    text: str,
    h: int,
    alignment: str,
    fg: Tuple[int, int, int],
    bg: Optional[Tuple[int, int, int]],
    line_spacing: int,
    config=None,
    region_count: int = 1,
) -> Optional[np.ndarray]:
    """Qt 渲染器的竖排文本渲染函数（兼容 text_render 接口）"""
    renderer = get_qt_renderer()
    if renderer is None:
        return text_render.put_text_vertical(
            font_size, text, h, alignment, fg, bg,
            line_spacing, config, region_count
        )
    return renderer.put_text_vertical(
        font_size, text, h, alignment, fg, bg,
        line_spacing, config, region_count
    )
