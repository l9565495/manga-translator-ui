import os
import re
import cv2
import numpy as np
from typing import List
from shapely import affinity
from shapely.geometry import Polygon
from tqdm import tqdm

from . import text_render
from .text_render_eng import render_textblock_list_eng
from .text_render_pillow_eng import render_textblock_list_eng as render_textblock_list_eng_pillow
from ..utils import (
    BASE_PATH,
    TextBlock,
    color_difference,
    get_logger,
    rotate_polygons,
)
from ..config import Config

logger = get_logger('render')

def parse_font_paths(path: str, default: List[str] = None) -> List[str]:
    if path:
        parsed = path.split(',')
        parsed = list(filter(lambda p: os.path.isfile(p), parsed))
    else:
        parsed = default or []
    return parsed

def fg_bg_compare(fg, bg):
    fg_avg = np.mean(fg)
    if color_difference(fg, bg) < 30:
        bg = (255, 255, 255) if fg_avg <= 127 else (0, 0, 0)
    return fg, bg

def count_text_length(text: str) -> float:
    """Calculate text length, treating っッぁぃぅぇぉ as 0.5 characters"""
    half_width_chars = 'っッぁぃぅぇぉ'  
    length = 0.0
    for char in text.strip():
        if char in half_width_chars:
            length += 0.5
        else:
            length += 1.0
    return length

def resize_regions_to_font_size(img: np.ndarray, text_regions: List['TextBlock'], config: Config):
    mode = config.render.layout_mode

    dst_points_list = []
    for region_idx, region in enumerate(text_regions):
        if region is None:
            dst_points_list.append(None)
            continue

        # 如果 translation 为空,直接返回 min_rect,避免触发复杂的布局计算
        if not region.translation or not region.translation.strip():
            dst_points_list.append(region.min_rect)
            continue

        original_region_font_size = region.font_size if region.font_size > 0 else round((img.shape[0] + img.shape[1]) / 200)

        # 保存原始字体大小到region对象，用于JSON导出
        if not hasattr(region, 'original_font_size'):
            region.original_font_size = original_region_font_size


        font_size_offset = config.render.font_size_offset
        min_font_size = max(config.render.font_size_minimum if config.render.font_size_minimum > 0 else 1, 1)
        target_font_size = max(original_region_font_size + font_size_offset, min_font_size)

        # 保存应用偏移量后的字体大小，用于JSON导出
        region.offset_applied_font_size = int(target_font_size)


        # --- Mode 1: disable_all (unchanged) ---
        if mode == 'disable_all':
            # Calculate total font scale (font_scale_ratio + max_font_size limit)
            final_font_size = int(target_font_size * config.render.font_scale_ratio)
            total_font_scale = config.render.font_scale_ratio

            if config.render.max_font_size > 0 and final_font_size > config.render.max_font_size:
                total_font_scale *= config.render.max_font_size / final_font_size
                final_font_size = config.render.max_font_size

            # Scale region to match final font size
            dst_points = region.min_rect
            if total_font_scale != 1.0:
                try:
                    poly = Polygon(region.unrotated_min_rect[0])
                    scaled_poly = affinity.scale(poly, xfact=total_font_scale, yfact=total_font_scale, origin='center')
                    scaled_points = np.array(scaled_poly.exterior.coords[:4])
                    dst_points = rotate_polygons(region.center, scaled_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                except Exception as e:
                    logger.warning(f"Failed to scale region for font_scale_ratio: {e}")

            region.font_size = final_font_size
            dst_points_list.append(dst_points)
            continue

        # --- Mode 2: strict ---
        elif mode == 'strict':
            font_size = target_font_size
            min_shrink_font_size = max(min_font_size, 8)

            # Step 1: 先缩小字体直到文本能放进文本框
            iteration_count = 0
            while font_size >= min_shrink_font_size:
                iteration_count += 1
                if region.horizontal:
                    lines, _ = text_render.calc_horizontal(font_size, region.translation, max_width=region.unrotated_size[0], max_height=region.unrotated_size[1], language=region.target_lang)
                    if len(lines) <= len(region.texts):
                        break
                else:
                    lines, _ = text_render.calc_vertical(font_size, region.translation, max_height=region.unrotated_size[1])
                    if len(lines) <= len(region.texts):
                        break
                font_size -= 1

            # Step 2: 尝试扩大字体以更好地填充空间（但不超过初始大小）
            # 从当前能放下的字体大小开始，逐步增加
            max_fitting_font_size = font_size
            test_font_size = font_size + 1

            while test_font_size <= target_font_size:
                if region.horizontal:
                    test_lines, _ = text_render.calc_horizontal(test_font_size, region.translation, max_width=region.unrotated_size[0], max_height=region.unrotated_size[1], language=region.target_lang)
                    if len(test_lines) <= len(region.texts):
                        max_fitting_font_size = test_font_size
                        test_font_size += 1
                    else:
                        break
                else:
                    test_lines, _ = text_render.calc_vertical(test_font_size, region.translation, max_height=region.unrotated_size[1])
                    if len(test_lines) <= len(region.texts):
                        max_fitting_font_size = test_font_size
                        test_font_size += 1
                    else:
                        break

            # Calculate total font scale (font_scale_ratio + max_font_size limit)
            final_font_size = int(max(max_fitting_font_size, min_shrink_font_size) * config.render.font_scale_ratio)
            total_font_scale = config.render.font_scale_ratio

            if config.render.max_font_size > 0 and final_font_size > config.render.max_font_size:
                total_font_scale *= config.render.max_font_size / final_font_size
                final_font_size = config.render.max_font_size

            # Scale region to match final font size
            dst_points = region.min_rect
            if total_font_scale != 1.0:
                try:
                    poly = Polygon(region.unrotated_min_rect[0])
                    scaled_poly = affinity.scale(poly, xfact=total_font_scale, yfact=total_font_scale, origin='center')
                    scaled_points = np.array(scaled_poly.exterior.coords[:4])
                    dst_points = rotate_polygons(region.center, scaled_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                except Exception as e:
                    logger.warning(f"Failed to scale region for font_scale_ratio: {e}")

            region.font_size = final_font_size
            dst_points_list.append(dst_points)
            continue

        # --- Mode 3: default (uses old logic, unchanged) ---
        elif mode == 'default':

            font_size_fixed = config.render.font_size
            font_size_offset = config.render.font_size_offset
            font_size_minimum = config.render.font_size_minimum


            if font_size_minimum == -1:
                font_size_minimum = round((img.shape[0] + img.shape[1]) / 200)
            font_size_minimum = max(1, font_size_minimum)

            original_region_font_size = region.font_size
            if original_region_font_size <= 0:
                original_region_font_size = font_size_minimum

            if font_size_fixed is not None:
                target_font_size = font_size_fixed
            else:
                target_font_size = original_region_font_size + font_size_offset

            target_font_size = max(target_font_size, font_size_minimum, 1)

            orig_text = getattr(region, "text_raw", region.text)
            char_count_orig = count_text_length(orig_text)
            char_count_trans = count_text_length(region.translation.strip())

            if char_count_orig > 0 and char_count_trans > char_count_orig:
                increase_percentage = (char_count_trans - char_count_orig) / char_count_orig
                font_increase_ratio = 1 + (increase_percentage * 0.3)
                font_increase_ratio = min(1.5, max(1.0, font_increase_ratio))
                target_font_size = int(target_font_size * font_increase_ratio)
                target_scale = max(1, min(1 + increase_percentage * 0.3, 2))
            else:
                target_scale = 1

            font_size_scale = (((target_font_size - original_region_font_size) / original_region_font_size) * 0.4 + 1) if original_region_font_size > 0 else 1.0
            final_scale = max(font_size_scale, target_scale)
            final_scale = max(1, min(final_scale, 1.1))

            if final_scale > 1.001:
                try:
                    poly = Polygon(region.unrotated_min_rect[0])
                    poly = affinity.scale(poly, xfact=final_scale, yfact=final_scale, origin='center')
                    scaled_unrotated_points = np.array(poly.exterior.coords[:4])
                    dst_points = rotate_polygons(region.center, scaled_unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                    dst_points = dst_points.reshape((-1, 4, 2))
                except Exception as e:
                    dst_points = region.min_rect
            else:
                dst_points = region.min_rect

            # Calculate total font scale (font_scale_ratio + max_font_size limit)
            final_font_size = int(target_font_size * config.render.font_scale_ratio)
            total_font_scale = config.render.font_scale_ratio

            if config.render.max_font_size > 0 and final_font_size > config.render.max_font_size:
                total_font_scale *= config.render.max_font_size / final_font_size
                final_font_size = config.render.max_font_size

            # Scale dst_points to match final font size
            if total_font_scale != 1.0:
                try:
                    poly = Polygon(dst_points.reshape(-1, 2))
                    scaled_poly = affinity.scale(poly, xfact=total_font_scale, yfact=total_font_scale, origin='center')
                    dst_points = np.array(scaled_poly.exterior.coords[:4]).reshape(-1, 4, 2)
                except Exception as e:
                    logger.warning(f"Failed to scale region for font_scale_ratio: {e}")

            region.font_size = final_font_size
            dst_points_list.append(dst_points)
            continue

        # --- Mode 4: smart_scaling ---
        elif mode == 'smart_scaling':
            # Check if AI line breaking is enabled.
            if config.render.disable_auto_wrap:
                # --- FINAL UNIFIED ALGORITHM for AI ON ---
                try:
                    # Calculate required dimensions using current font size (fixed layout)
                    bubble_width, bubble_height = region.unrotated_size

                    # Defensive check for invalid bubble sizes
                    if not (isinstance(bubble_width, (int, float)) and np.isfinite(bubble_width) and bubble_width > 0 and
                            isinstance(bubble_height, (int, float)) and np.isfinite(bubble_height) and bubble_height > 0):
                        logger.warning(f"Invalid bubble size for region: w={bubble_width}, h={bubble_height}. Skipping smart scaling for this region.")
                        dst_points_list.append(region.min_rect)
                        final_font_size = int(max(target_font_size, min_font_size) * config.render.font_scale_ratio)
                        if config.render.max_font_size > 0:
                            final_font_size = min(final_font_size, config.render.max_font_size)
                        region.font_size = final_font_size
                        continue

                    # Create base polygon for scaling
                    try:
                        unrotated_base_poly = Polygon(region.unrotated_min_rect[0])
                    except Exception:
                        unrotated_base_poly = Polygon([(0, 0), (bubble_width, 0), (bubble_width, bubble_height), (0, bubble_height)])

                    # Calculate required width and height (no auto wrap)
                    required_width = 0
                    required_height = 0

                    if region.horizontal:
                        lines, widths = text_render.calc_horizontal(target_font_size, region.translation, max_width=99999, max_height=99999, language=region.target_lang)
                        if widths:
                            spacing_y = int(target_font_size * (config.render.line_spacing or 0.01))
                            required_width = max(widths)
                            required_height = target_font_size * len(lines) + spacing_y * max(0, len(lines) - 1)
                    else: # Vertical
                        # Convert [BR] tags to \n for vertical text
                        text_for_calc = re.sub(r'\s*(\[BR\]|<br>|【BR】)\s*', '\n', region.translation, flags=re.IGNORECASE)
                        
                        # Apply auto_add_horizontal_tags if enabled
                        if config.render.auto_rotate_symbols:
                            text_for_calc = text_render.auto_add_horizontal_tags(text_for_calc)
                        
                        lines, heights = text_render.calc_vertical(target_font_size, text_for_calc, max_height=99999)
                        if heights:
                            spacing_x = int(target_font_size * (config.render.line_spacing or 0.2))
                            required_height = max(heights)
                            required_width = target_font_size * len(lines) + spacing_x * max(0, len(lines) - 1)

                    # Check for overflow in either dimension
                    width_overflow = max(0, required_width - bubble_width)
                    height_overflow = max(0, required_height - bubble_height)

                    dst_points = region.min_rect

                    if width_overflow > 0 or height_overflow > 0:
                        # 独立缩放宽度和高度（单列/单行和多列/多行都使用相同逻辑）
                        width_scale_factor = 1.0
                        height_scale_factor = 1.0

                        if width_overflow > 0:
                            width_scale_needed = required_width / bubble_width if bubble_width > 0 else 1.0
                            diff_ratio_w = width_scale_needed - 1.0
                            box_expansion_ratio_w = diff_ratio_w / 2
                            width_scale_factor = 1 + min(box_expansion_ratio_w, 1.0)

                        if height_overflow > 0:
                            height_scale_needed = required_height / bubble_height if bubble_height > 0 else 1.0
                            diff_ratio_h = height_scale_needed - 1.0
                            box_expansion_ratio_h = diff_ratio_h / 2
                            height_scale_factor = 1 + min(box_expansion_ratio_h, 1.0)

                        try:
                            scaled_unrotated_poly = affinity.scale(unrotated_base_poly, xfact=width_scale_factor, yfact=height_scale_factor, origin='center')
                            scaled_unrotated_points = np.array(scaled_unrotated_poly.exterior.coords[:4])
                            dst_points = rotate_polygons(region.center, scaled_unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                        except Exception as e:
                            logger.warning(f"Failed to apply independent scaling: {e}")

                        # 字体缩放基于最大的溢出维度
                        scale_needed = max(required_width / bubble_width if bubble_width > 0 else 1.0,
                                         required_height / bubble_height if bubble_height > 0 else 1.0)
                        diff_ratio = scale_needed - 1.0
                        font_shrink_ratio = diff_ratio / 2 / (1 + diff_ratio)
                        font_scale_factor = 1 - min(font_shrink_ratio, 0.5)
                        target_font_size = int(target_font_size * font_scale_factor)
                    else:
                        # No overflow, can enlarge font to fit better
                        if required_width > 0 and required_height > 0:
                            width_scale_factor = bubble_width / required_width
                            height_scale_factor = bubble_height / required_height
                            font_scale_factor = min(width_scale_factor, height_scale_factor)
                            target_font_size = int(target_font_size * font_scale_factor)

                        try:
                            unrotated_points = np.array(unrotated_base_poly.exterior.coords[:4])
                            dst_points = rotate_polygons(region.center, unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                        except Exception as e:
                            logger.warning(f"Failed to use base polygon: {e}")

                except Exception as e:
                    logger.error(f"Error in new smart_scaling algorithm: {e}")
                    # Fallback to a safe state
                    target_font_size = region.offset_applied_font_size
                    dst_points = region.min_rect

                # Calculate total font scale (font_scale_ratio + max_font_size limit)
                final_font_size = int(max(target_font_size, min_font_size) * config.render.font_scale_ratio)
                total_font_scale = config.render.font_scale_ratio

                if config.render.max_font_size > 0 and final_font_size > config.render.max_font_size:
                    total_font_scale *= config.render.max_font_size / final_font_size
                    final_font_size = config.render.max_font_size

                # Scale dst_points to match final font size
                if total_font_scale != 1.0:
                    try:
                        poly = Polygon(dst_points.reshape(-1, 2))
                        scaled_poly = affinity.scale(poly, xfact=total_font_scale, yfact=total_font_scale, origin='center')
                        dst_points = np.array(scaled_poly.exterior.coords[:4]).reshape(-1, 4, 2)
                    except Exception as e:
                        logger.warning(f"Failed to scale region for font_scale_ratio: {e}")
                region.font_size = final_font_size
                dst_points_list.append(dst_points)
                continue

            else:
                # --- ORIGINAL smart_scaling LOGIC for AI OFF ---
                # This is the old logic based on diff_ratio, preserved for when AI splitting is off.
                if len(region.lines) > 1:
                    from shapely.ops import unary_union
                    try:
                        unrotated_polygons = []
                        for i, p in enumerate(region.lines):
                            unrotated_p = rotate_polygons(region.center, p.reshape(1, -1, 2), region.angle, to_int=False)
                            unrotated_polygons.append(Polygon(unrotated_p.reshape(-1, 2)))
                        union_poly = unary_union(unrotated_polygons)
                        original_area = union_poly.area
                        unrotated_base_poly = union_poly.envelope
                    except Exception as e:
                        logger.warning(f"Failed to compute union of polygons: {e}")
                        original_area = region.unrotated_size[0] * region.unrotated_size[1]
                        unrotated_base_poly = Polygon(region.unrotated_min_rect[0])
                else:
                    original_area = region.unrotated_size[0] * region.unrotated_size[1]
                    unrotated_base_poly = Polygon(region.unrotated_min_rect[0])

                required_area = 0
                if region.horizontal:
                    lines, widths = text_render.calc_horizontal(target_font_size, region.translation, max_width=99999, max_height=99999, language=region.target_lang)
                    if widths:
                        required_width = max(widths)
                        required_height = len(lines) * (target_font_size * (1 + (config.render.line_spacing or 0.01)))
                        required_area = required_width * required_height
                else: # Vertical
                    lines, heights = text_render.calc_vertical(target_font_size, region.translation, max_height=99999)
                    if heights:
                        required_height = max(heights)
                        required_width = len(lines) * (target_font_size * (1 + (config.render.line_spacing or 0.2)))
                        required_area = required_width * required_height

                dst_points = region.min_rect
                diff_ratio = 0
                if original_area > 0 and required_area > 0:
                    diff_ratio = (required_area - original_area) / original_area

                if diff_ratio > 0:
                    box_expansion_ratio = diff_ratio / 2
                    box_scale_factor = 1 + min(box_expansion_ratio, 1.0)
                    font_shrink_ratio = diff_ratio / 2 / (1 + diff_ratio)
                    font_scale_factor = 1 - min(font_shrink_ratio, 0.5)
                    try:
                        scaled_unrotated_poly = affinity.scale(unrotated_base_poly, xfact=box_scale_factor, yfact=box_scale_factor, origin='center')
                        scaled_unrotated_points = np.array(scaled_unrotated_poly.exterior.coords[:4])
                        dst_points = rotate_polygons(region.center, scaled_unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                    except Exception as e:
                        logger.warning(f"Failed to apply dynamic scaling: {e}")
                    target_font_size = int(target_font_size * font_scale_factor)
                elif diff_ratio < 0:
                    try:
                        area_ratio = original_area / required_area
                        font_scale_factor = np.sqrt(area_ratio)
                        target_font_size = int(target_font_size * font_scale_factor)
                        unrotated_points = np.array(unrotated_base_poly.exterior.coords[:4])
                        dst_points = rotate_polygons(region.center, unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                    except Exception as e:
                        logger.warning(f"Failed to apply font enlargement: {e}")
                else:
                    try:
                        unrotated_points = np.array(unrotated_base_poly.exterior.coords[:4])
                        dst_points = rotate_polygons(region.center, unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                    except Exception as e:
                        logger.warning(f"Failed to use base polygon: {e}")

                # Calculate total font scale (font_scale_ratio + max_font_size limit)
                final_font_size = int(target_font_size * config.render.font_scale_ratio)
                total_font_scale = config.render.font_scale_ratio

                if config.render.max_font_size > 0 and final_font_size > config.render.max_font_size:
                    total_font_scale *= config.render.max_font_size / final_font_size
                    final_font_size = config.render.max_font_size

                # Scale dst_points to match final font size
                if total_font_scale != 1.0:
                    try:
                        poly = Polygon(dst_points.reshape(-1, 2))
                        scaled_poly = affinity.scale(poly, xfact=total_font_scale, yfact=total_font_scale, origin='center')
                        dst_points = np.array(scaled_poly.exterior.coords[:4]).reshape(-1, 4, 2)
                    except Exception as e:
                        logger.warning(f"Failed to scale region for font_scale_ratio: {e}")

                region.font_size = final_font_size
                dst_points_list.append(dst_points)
                continue

        # --- Fallback for any other modes (e.g., 'fixed_font') ---
        else:
            # Calculate total font scale (font_scale_ratio + max_font_size limit)
            final_font_size = int(min(target_font_size, 512) * config.render.font_scale_ratio)
            total_font_scale = config.render.font_scale_ratio

            if config.render.max_font_size > 0 and final_font_size > config.render.max_font_size:
                total_font_scale *= config.render.max_font_size / final_font_size
                final_font_size = config.render.max_font_size

            # Scale region to match final font size
            dst_points = region.min_rect
            if total_font_scale != 1.0:
                try:
                    poly = Polygon(region.unrotated_min_rect[0])
                    scaled_poly = affinity.scale(poly, xfact=total_font_scale, yfact=total_font_scale, origin='center')
                    scaled_points = np.array(scaled_poly.exterior.coords[:4])
                    dst_points = rotate_polygons(region.center, scaled_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                except Exception as e:
                    logger.warning(f"Failed to scale region for font_scale_ratio: {e}")

            region.font_size = final_font_size
            dst_points_list.append(dst_points)
            continue

    return dst_points_list


async def dispatch(
    img: np.ndarray,
    text_regions: List[TextBlock],
    font_path: str = '',
    config: Config = None
    ) -> np.ndarray:

    if config is None:
        from ..config import Config
        config = Config()

    text_render.set_font(font_path)
    text_regions = list(filter(lambda region: region.translation, text_regions))

    dst_points_list = resize_regions_to_font_size(img, text_regions, config)

    for region, dst_points in tqdm(zip(text_regions, dst_points_list), '[render]', total=len(text_regions)):
        img = render(img, region, dst_points, not config.render.no_hyphenation, config.render.line_spacing, config.render.disable_font_border, config)
    return img

def render(
    img,
    region: TextBlock,
    dst_points,
    hyphenate,
    line_spacing,
    disable_font_border,
    config: Config
):
    # --- START BRUTEFORCE COLOR FIX ---
    fg = (0, 0, 0) # Default to black
    try:
        # Priority 1: Check for the original hex string from the UI
        if hasattr(region, 'font_color') and isinstance(region.font_color, str) and region.font_color.startswith('#'):
            hex_c = region.font_color
            if len(hex_c) == 7:
                r = int(hex_c[1:3], 16)
                g = int(hex_c[3:5], 16)
                b = int(hex_c[5:7], 16)
                fg = (r, g, b)
        # Priority 2: Check for a pre-converted tuple
        elif hasattr(region, 'fg_colors') and isinstance(region.fg_colors, (tuple, list)) and len(region.fg_colors) == 3:
            fg = tuple(region.fg_colors)
        # Last resort: Use the method
        else:
            fg, _ = region.get_font_colors()
    except Exception as e:
        # If anything fails, fg remains black
        pass

    # Get background color separately
    _, bg = region.get_font_colors()
    # --- END BRUTEFORCE COLOR FIX ---

    # Convert hex color string to RGB tuple, if necessary
    if isinstance(fg, str) and fg.startswith('#') and len(fg) == 7:
        try:
            r = int(fg[1:3], 16)
            g = int(fg[3:5], 16)
            b = int(fg[5:7], 16)
            fg = (r, g, b)
        except ValueError:
            fg = (0, 0, 0)  # Default to black on error
    elif not isinstance(fg, (tuple, list)):
        fg = (0, 0, 0) # Default to black if format is unexpected

    fg, bg = fg_bg_compare(fg, bg)

    # Centralized text preprocessing
    text_to_render = region.get_translation_for_rendering()
    # If AI line breaking is enabled, standardize all break tags ([BR], <br>, and 【BR】) to \n
    if config and config.render.disable_auto_wrap:
        text_to_render = re.sub(r'\s*(\[BR\]|<br>|【BR】)\s*', '\n', text_to_render, flags=re.IGNORECASE)

    # Automatically add horizontal tags for vertical text
    if region.vertical and config.render.auto_rotate_symbols:
        text_to_render = text_render.auto_add_horizontal_tags(text_to_render)

    if disable_font_border :
        bg = None

    middle_pts = (dst_points[:, [1, 2, 3, 0]] + dst_points) / 2
    norm_h = np.linalg.norm(middle_pts[:, 1] - middle_pts[:, 3], axis=1)
    norm_v = np.linalg.norm(middle_pts[:, 2] - middle_pts[:, 0], axis=1)
    r_orig = np.mean(norm_h / norm_v)

    forced_direction = region._direction if hasattr(region, "_direction") else region.direction
    if forced_direction != "auto":
        if forced_direction in ["horizontal", "h"]:
            render_horizontally = True
        elif forced_direction in ["vertical", "v"]:
            render_horizontally = False
        else:
            render_horizontally = region.horizontal
    else:
        render_horizontally = region.horizontal

    # 如果最终判断为横排,删除所有 <H> 标签,防止打印出来
    if render_horizontally:
        text_to_render = re.sub(r'<H>(.*?)</H>', r'\1', text_to_render, flags=re.IGNORECASE | re.DOTALL)

    if render_horizontally:
        temp_box = text_render.put_text_horizontal(
            region.font_size,
            text_to_render,
            round(norm_h[0]),
            round(norm_v[0]),
            region.alignment,
            region.direction == 'hl',
            fg,
            bg,
            region.target_lang,
            hyphenate,
            line_spacing,
            config,
            len(region.lines)  # Pass region count
        )
    else:
        temp_box = text_render.put_text_vertical(
            region.font_size,
            text_to_render,
            round(norm_v[0]),
            region.alignment,
            fg,
            bg,
            line_spacing,
            config,
            len(region.lines)  # Pass region count
        )
    h, w, _ = temp_box.shape
    if h == 0 or w == 0:
        logger.warning(f"Skipping rendering for region with invalid dimensions (w={w}, h={h}). Text: '{region.translation}'")
        return img
    r_temp = w / h

    box = None
    if region.horizontal:
        if r_temp > r_orig:
            h_ext = int((w / r_orig - h) // 2) if r_orig > 0 else 0
            if h_ext >= 0:
                box = np.zeros((h + h_ext * 2, w, 4), dtype=np.uint8)
                # Center vertically when enabled
                if config and config.render.center_text_in_bubble and config.render.disable_auto_wrap:
                    box[h_ext:h_ext+h, 0:w] = temp_box
                else:
                    box[0:h, 0:w] = temp_box
            else:
                box = temp_box.copy()
        else:
            w_ext = int((h * r_orig - w) // 2)
            if w_ext >= 0:
                box = np.zeros((h, w + w_ext * 2, 4), dtype=np.uint8)
                # Center horizontally when enabled
                if config and config.render.center_text_in_bubble and config.render.disable_auto_wrap:
                    box[0:h, w_ext:w_ext+w] = temp_box
                else:
                    box[0:h, 0:w] = temp_box
            else:
                box = temp_box.copy()
    else:
        if r_temp > r_orig:
            h_ext = int(w / (2 * r_orig) - h / 2) if r_orig > 0 else 0
            if h_ext >= 0:
                box = np.zeros((h + h_ext * 2, w, 4), dtype=np.uint8)
                # Center vertically when enabled
                if config and config.render.center_text_in_bubble and config.render.disable_auto_wrap:
                    box[h_ext:h_ext+h, 0:w] = temp_box
                else:
                    box[0:h, 0:w] = temp_box
            else:
                box = temp_box.copy()
        else:
            w_ext = int((h * r_orig - w) / 2)
            if w_ext >= 0:
                box = np.zeros((h, w + w_ext * 2, 4), dtype=np.uint8)
                # Center horizontally (always active for vertical text)
                box[0:h, w_ext:w_ext+w] = temp_box
            else:
                box = temp_box.copy()

    src_points = np.array([[0, 0], [box.shape[1], 0], [box.shape[1], box.shape[0]], [0, box.shape[0]]]).astype(np.float32)

    M, _ = cv2.findHomography(src_points, dst_points, cv2.RANSAC, 5.0)
    # 使用INTER_LANCZOS4获得最高质量的插值,避免字体模糊
    rgba_region = cv2.warpPerspective(box, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    x, y, w, h = cv2.boundingRect(np.round(dst_points).astype(np.int64))
    canvas_region = rgba_region[y:y+h, x:x+w, :3]
    mask_region = rgba_region[y:y+h, x:x+w, 3:4].astype(np.float32) / 255.0
    img[y:y+h, x:x+w] = np.clip((img[y:y+h, x:x+w].astype(np.float32) * (1 - mask_region) + canvas_region.astype(np.float32) * mask_region), 0, 255).astype(np.uint8)
    return img

async def dispatch_eng_render(img_canvas: np.ndarray, original_img: np.ndarray, text_regions: List[TextBlock], font_path: str = '', line_spacing: int = 0, disable_font_border: bool = False) -> np.ndarray:
    if len(text_regions) == 0:
        return img_canvas

    if not font_path:
        font_path = os.path.join(BASE_PATH, 'fonts/comic shanns 2.ttf')
    text_render.set_font(font_path)

    return render_textblock_list_eng(img_canvas, text_regions, line_spacing=line_spacing, size_tol=1.2, original_img=original_img, downscale_constraint=0.8,disable_font_border=disable_font_border)

async def dispatch_eng_render_pillow(img_canvas: np.ndarray, original_img: np.ndarray, text_regions: List[TextBlock], font_path: str = '', line_spacing: int = 0, disable_font_border: bool = False) -> np.ndarray:
    if len(text_regions) == 0:
        return img_canvas

    if not font_path:
        font_path = os.path.join(BASE_PATH, 'fonts/NotoSansMonoCJK-VF.ttf.ttc')
    text_render.set_font(font_path)

    return render_textblock_list_eng_pillow(font_path, img_canvas, text_regions, original_img=original_img, downscale_constraint=0.95)