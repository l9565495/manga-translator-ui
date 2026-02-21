import logging
import os

import cv2
import numpy as np
from manga_translator.config import Config, RenderConfig
from manga_translator.rendering import text_render
from manga_translator.rendering.text_render import (
    set_font,
)
from manga_translator.utils import TextBlock
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QImage, QPixmap, QPolygonF

logger = logging.getLogger('manga_translator')


def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    import os
    import sys
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    return os.path.join(base_path, relative_path)

def resolve_font_path(font_path: str) -> str:
    """Resolve absolute/relative font path for both dev and packaged runtime.

    When an absolute path does not exist on the current machine (e.g., the path
    was saved on a different machine or the install directory changed), we fall
    back to searching for the font file by name inside the local fonts/ directory.
    """
    if not font_path:
        return ''
    if os.path.exists(font_path):
        return font_path

    # 路径不存在时（含绝对路径盘符不同的情况），用文件名在 fonts/ 目录里继续找
    font_basename = os.path.basename(font_path)
    candidates = (
        resource_path(os.path.join('fonts', font_basename)),
        resource_path(font_basename),
    )
    if not os.path.isabs(font_path):
        # 相对路径还额外尝试直接 join
        candidates = (
            resource_path(font_path),
        ) + candidates

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return ''

def apply_font_for_render(font_path: str) -> str:
    """Apply font for current render call; fallback to built-in default."""
    resolved_font_path = resolve_font_path(font_path)
    try:
        if resolved_font_path:
            set_font(resolved_font_path)
        else:
            set_font(text_render.DEFAULT_FONT)
    except Exception:
        set_font(text_render.DEFAULT_FONT)
        return ''
    return resolved_font_path

def update_font_config(font_filename: str):
    """兼容旧调用：更新字体配置（现转为按路径解析设置）。"""
    apply_font_for_render(font_filename)

def render_text_for_region(text_block: TextBlock, dst_points: np.ndarray, transform, render_params: dict, pure_zoom: float = 1.0, total_regions: int = 1):
    """
    为单个区域渲染文本的核心函数
    返回一个包含 (QPixmap, QPointF) 的元组用于绘制，或者在失败时返回 None
    """
    original_translation = text_block.translation
    try:
        # --- 1. 文本预处理 ---
        text_to_render = original_translation or text_block.text
        if not text_to_render:
            logger.debug("[EDITOR RENDER SKIPPED] Text is empty")
            return None

        text_block.translation = text_to_render

        # 区域级字体优先：render_params.font_path -> text_block.font_path -> 默认字体
        region_font_path = render_params.get('font_path') or getattr(text_block, 'font_path', '')
        resolved_font_path = apply_font_for_render(region_font_path)
        if not resolved_font_path and region_font_path:
            logger.warning(f"[EDITOR RENDER] Font path not found: {region_font_path}, fallback to default font")

        # --- 2. 渲染 ---
        disable_font_border = render_params.get('disable_font_border', False)
        
        middle_pts = (dst_points[:, [1, 2, 3, 0]] + dst_points) / 2
        norm_h = np.linalg.norm(middle_pts[:, 1] - middle_pts[:, 3], axis=1)
        norm_v = np.linalg.norm(middle_pts[:, 2] - middle_pts[:, 0], axis=1)

        render_w = round(norm_h[0])
        render_h = round(norm_v[0])
        font_size = text_block.font_size

        # 从 text_block 获取默认颜色
        fg_color, bg_color_default = text_block.get_font_colors()
        
        # 优先使用 render_params 中用户设置的描边颜色
        bg_color = render_params.get('text_stroke_color', bg_color_default)
        logger.debug(f"[EDITOR RENDER] 描边颜色: text_stroke_color={render_params.get('text_stroke_color')}, bg_color_default={bg_color_default}, 最终使用={bg_color}")
        
        # 从 render_params 中获取描边宽度
        stroke_width = render_params.get('text_stroke_width', None)
        
        if disable_font_border:
            bg_color = None

        if render_w <= 0 or render_h <= 0:
            logger.debug(f"[EDITOR RENDER SKIPPED] Invalid render dimensions: width={render_w}, height={render_h}")
            return None

        config_data = render_params.copy()
        if config_data.get('direction') == 'v':
            config_data['direction'] = 'vertical'
        elif config_data.get('direction') == 'h':
            config_data['direction'] = 'horizontal'

        if 'font_color' in config_data and isinstance(config_data['font_color'], list):
            try:
                rgb = config_data['font_color']
                config_data['font_color'] = f'#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}'
            except (IndexError, TypeError):
                config_data.pop('font_color')
        
        # 将后端参数名映射回RenderConfig期望的字段名
        if 'text_stroke_width' in config_data:
            config_data['stroke_width'] = config_data.pop('text_stroke_width')
        if 'text_stroke_color' in config_data:
            config_data['bg_color'] = config_data.pop('text_stroke_color')

        config_obj = Config(render=RenderConfig(**config_data)) if config_data else Config()
        line_spacing_multiplier = render_params.get('line_spacing', 1.0)
        
        # 将倍率转换为实际比例：横排基础 0.01，竖排基础 0.2
        is_horizontal = text_block.horizontal
        base_spacing = 0.01 if is_horizontal else 0.2
        line_spacing_from_params = base_spacing * line_spacing_multiplier

        # 获取区域数（lines数组的长度），用于智能排版模式的换行判断
        region_count = 1
        if hasattr(text_block, 'lines') and text_block.lines is not None:
            try:
                region_count = len(text_block.lines)
            except:
                region_count = 1

        # 将当前text_block传递给config，用于方向不匹配检测
        if config_obj:
            config_obj._current_region = text_block

        # 使用 freetype 渲染器（稳定可靠）
        if text_block.horizontal:
            rendered_surface = text_render.put_text_horizontal(
                font_size, 
                text_block.get_translation_for_rendering(), 
                render_w, 
                render_h, 
                text_block.alignment, 
                text_block.direction == 'hl', 
                fg_color, 
                bg_color, 
                text_block.target_lang, 
                True, 
                line_spacing_from_params, 
                config=config_obj, 
                region_count=region_count,
                stroke_width=stroke_width
            )
        else:
            rendered_surface = text_render.put_text_vertical(
                font_size, 
                text_block.get_translation_for_rendering(), 
                render_h, 
                text_block.alignment, 
                fg_color, 
                bg_color, 
                line_spacing_from_params, 
                config=config_obj, 
                region_count=region_count,
                stroke_width=stroke_width
            )

        if rendered_surface is None or rendered_surface.size == 0:
            logger.debug(f"[EDITOR RENDER SKIPPED] Rendered surface is None or empty. Text: '{text_block.translation[:50] if hasattr(text_block, 'translation') else 'N/A'}...'")
            return None
        
        # --- 3. 宽高比校正 (与后端渲染逻辑完全同步) ---
        h_temp, w_temp, _ = rendered_surface.shape
        if h_temp == 0 or w_temp == 0:
            logger.debug(f"[EDITOR RENDER SKIPPED] Rendered surface has zero dimensions: width={w_temp}, height={h_temp}")
            return None
        r_temp = w_temp / h_temp
        
        middle_pts = (dst_points[:, [1, 2, 3, 0]] + dst_points) / 2
        norm_h = np.linalg.norm(middle_pts[:, 1] - middle_pts[:, 3], axis=1)
        norm_v = np.linalg.norm(middle_pts[:, 2] - middle_pts[:, 0], axis=1)
        r_orig = np.mean(norm_h / norm_v)

        box = None
        if text_block.horizontal:
            if r_temp > r_orig:
                h_ext = int((w_temp / r_orig - h_temp) // 2) if r_orig > 0 else 0
                if h_ext >= 0:
                    box = np.zeros((h_temp + h_ext * 2, w_temp, 4), dtype=np.uint8)
                    # 垂直方向：根据center_text_in_bubble决定是否居中
                    if config_obj.render.center_text_in_bubble:
                        # 居中开启：垂直居中
                        box[h_ext:h_ext+h_temp, 0:w_temp] = rendered_surface
                    else:
                        # 默认：贴顶部
                        box[0:h_temp, 0:w_temp] = rendered_surface
                else:
                    box = rendered_surface.copy()
            else:
                w_ext = int((h_temp * r_orig - w_temp) // 2)
                if w_ext >= 0:
                    box = np.zeros((h_temp, w_temp + w_ext * 2, 4), dtype=np.uint8)
                    # 横排文本默认水平居中
                    box[0:h_temp, w_ext:w_ext+w_temp] = rendered_surface
                else:
                    box = rendered_surface.copy()
        else: # Vertical
            if r_temp > r_orig:
                h_ext = int(w_temp / (2 * r_orig) - h_temp / 2) if r_orig > 0 else 0
                if h_ext >= 0:
                    box = np.zeros((h_temp + h_ext * 2, w_temp, 4), dtype=np.uint8)
                    # 竖排文本垂直方向：根据center_text_in_bubble决定是否居中
                    if config_obj.render.center_text_in_bubble:
                        # 居中开启：垂直居中
                        box[h_ext:h_ext+h_temp, 0:w_temp] = rendered_surface
                    else:
                        # 默认：贴顶部
                        box[0:h_temp, 0:w_temp] = rendered_surface
                else:
                    box = rendered_surface.copy()
            else:
                w_ext = int((h_temp * r_orig - w_temp) / 2)
                if w_ext >= 0:
                    box = np.zeros((h_temp, w_temp + w_ext * 2, 4), dtype=np.uint8)
                    # 竖排文本水平居中
                    box[0:h_temp, w_ext:w_ext+w_temp] = rendered_surface
                else:
                    box = rendered_surface.copy()

        if box is None:
            box = rendered_surface.copy()

        # --- 4. 坐标变换与扭曲 (Warping) ---
        src_points = np.float32([[0, 0], [box.shape[1], 0], [box.shape[1], box.shape[0]], [0, box.shape[0]]])

        # 将图像坐标转换为视图(屏幕)坐标
        qpoly = transform.map(QPolygonF([QPointF(p[0], p[1]) for p in dst_points[0]]))
        dst_points_screen = np.float32([ [p.x(), p.y()] for p in qpoly ])

        # 计算屏幕上的最小边界框
        x_s, y_s, w_s, h_s = cv2.boundingRect(np.round(dst_points_screen).astype(np.int32))
        if w_s <= 0 or h_s <= 0:
            logger.debug(f"[EDITOR RENDER SKIPPED] Screen bounding box has invalid dimensions: x={x_s}, y={y_s}, width={w_s}, height={h_s}. Text may be outside visible area.")
            return None

        # 将目标点偏移到边界框的局部坐标
        dst_points_warp = dst_points_screen - [x_s, y_s]

        matrix, _ = cv2.findHomography(src_points, dst_points_warp, cv2.RANSAC, 5.0)
        if matrix is None:
            logger.debug("[EDITOR RENDER SKIPPED] Failed to compute homography matrix for text transformation")
            return None

        warped_image = cv2.warpPerspective(box, matrix, (w_s, h_s), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(0,0,0,0))

        # --- 5. 转换为QPixmap并返回绘制信息 ---
        h, w, ch = warped_image.shape
        if ch == 4:
            # Convert RGBA to BGRA for QImage Format_ARGB32
            bgra_image = warped_image.copy()
            bgra_image[:, :, [0, 2]] = bgra_image[:, :, [2, 0]]  # Swap R and B channels
            # 【关键修复】使用.copy()确保QImage拥有自己的内存，防止numpy数组被回收后崩溃
            final_image = QImage(bgra_image.data, w, h, w * 4, QImage.Format.Format_ARGB32).copy()
            final_pixmap = QPixmap.fromImage(final_image)
            # 返回pixmap和它在屏幕(视图)上的绘制位置
            return (final_pixmap, QPointF(x_s, y_s))

    except Exception as e:
        logger.debug(f"Error during backend text rendering: {e}")
        return None
    finally:
        text_block.translation = original_translation
