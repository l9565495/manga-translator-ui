import os
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
    logger.debug(f"[排版调试] 开始处理区域，排版模式: {mode}，总区域数: {len(text_regions)}")

    dst_points_list = []
    for region in text_regions:
        if region is None:
            dst_points_list.append(None)
            continue
        original_region_font_size = region.font_size if region.font_size > 0 else round((img.shape[0] + img.shape[1]) / 200)

        font_size_offset = config.render.font_size_offset
        min_font_size = max(config.render.font_size_minimum if config.render.font_size_minimum > 0 else 1, 1)
        target_font_size = max(original_region_font_size + font_size_offset, min_font_size)

        # --- Mode 1: disable_all (unchanged) ---
        if mode == 'disable_all':
            logger.debug(f"[排版调试-disable_all] 区域{region.blk_id if hasattr(region, 'blk_id') else '未知'}: 不调整尺寸")
            logger.debug(f"[排版调试-disable_all] 原始字体大小: {original_region_font_size}, 目标字体大小: {target_font_size}")
            logger.debug(f"[排版调试-disable_all] 原始文本框尺寸: {region.unrotated_size}")
            logger.debug(f"[排版调试-disable_all] 翻译文本: '{region.translation}'")
            region.font_size = int(target_font_size)
            dst_points_list.append(region.min_rect)
            logger.debug(f"[排版调试-disable_all] 最终字体大小: {region.font_size}, 使用原始文本框")
            continue

        # --- Mode 2: strict (unchanged) ---
        elif mode == 'strict':
            logger.debug(f"[排版调试-strict] 区域{region.blk_id if hasattr(region, 'blk_id') else '未知'}: 严格模式字体调整")
            logger.debug(f"[排版调试-strict] 原始字体大小: {original_region_font_size}, 目标字体大小: {target_font_size}")
            logger.debug(f"[排版调试-strict] 原始文本框尺寸: {region.unrotated_size}")
            logger.debug(f"[排版调试-strict] 翻译文本: '{region.translation}'")
            logger.debug(f"[排版调试-strict] 文本方向: {'水平' if region.horizontal else '垂直'}")
            font_size = target_font_size
            min_shrink_font_size = max(min_font_size, 8)
            logger.debug(f"[排版调试-strict] 最小字体大小限制: {min_shrink_font_size}")
            iteration_count = 0
            while font_size >= min_shrink_font_size:
                iteration_count += 1
                if region.horizontal:
                    lines, _ = text_render.calc_horizontal(font_size, region.translation, max_width=region.unrotated_size[0], max_height=region.unrotated_size[1], language=region.target_lang)
                    logger.debug(f"[排版调试-strict] 迭代{iteration_count}: 字体大小{font_size}, 计算行数{len(lines)}, 原始行数{len(region.texts)}")
                    if len(lines) <= len(region.texts):
                        break
                else:
                    lines, _ = text_render.calc_vertical(font_size, region.translation, max_height=region.unrotated_size[1])
                    logger.debug(f"[排版调试-strict] 迭代{iteration_count}: 字体大小{font_size}, 计算行数{len(lines)}, 原始行数{len(region.texts)}")
                    if len(lines) <= len(region.texts):
                        break
                font_size -= 1
            region.font_size = int(max(font_size, min_shrink_font_size))
            dst_points_list.append(region.min_rect)
            logger.debug(f"[排版调试-strict] 最终字体大小: {region.font_size}, 使用原始文本框")
            continue

        # --- Mode 3: default (uses old logic, unchanged) ---
        elif mode == 'default':
            logger.debug(f"[排版调试-default] 区域{region.blk_id if hasattr(region, 'blk_id') else '未知'}: 默认模式动态调整")
            logger.debug(f"[排版调试-default] 原始字体大小: {original_region_font_size}, 目标字体大小: {target_font_size}")
            logger.debug(f"[排版调试-default] 原始文本框尺寸: {region.unrotated_size}")
            logger.debug(f"[排版调试-default] 翻译文本: '{region.translation}'")

            font_size_fixed = config.render.font_size
            font_size_offset = config.render.font_size_offset
            font_size_minimum = config.render.font_size_minimum

            logger.debug(f"[排版调试-default] 配置 - 固定字体大小: {font_size_fixed}, 字体偏移: {font_size_offset}, 最小字体: {font_size_minimum}")

            if font_size_minimum == -1:
                font_size_minimum = round((img.shape[0] + img.shape[1]) / 200)
                logger.debug(f"[排版调试-default] 自动计算最小字体大小: {font_size_minimum}")
            font_size_minimum = max(1, font_size_minimum)

            original_region_font_size = region.font_size
            if original_region_font_size <= 0:
                original_region_font_size = font_size_minimum
                logger.debug(f"[排版调试-default] 使用最小字体大小作为原始字体大小: {original_region_font_size}")

            if font_size_fixed is not None:
                target_font_size = font_size_fixed
                logger.debug(f"[排版调试-default] 使用固定字体大小: {target_font_size}")
            else:
                target_font_size = original_region_font_size + font_size_offset
                logger.debug(f"[排版调试-default] 计算目标字体大小: {original_region_font_size} + {font_size_offset} = {target_font_size}")

            target_font_size = max(target_font_size, font_size_minimum, 1)
            logger.debug(f"[排版调试-default] 应用最小限制后目标字体大小: {target_font_size}")

            orig_text = getattr(region, "text_raw", region.text)
            char_count_orig = count_text_length(orig_text)
            char_count_trans = count_text_length(region.translation.strip())
            logger.debug(f"[排版调试-default] 字符统计 - 原文长度: {char_count_orig}, 译文长度: {char_count_trans}")

            if char_count_orig > 0 and char_count_trans > char_count_orig:
                increase_percentage = (char_count_trans - char_count_orig) / char_count_orig
                font_increase_ratio = 1 + (increase_percentage * 0.3)
                font_increase_ratio = min(1.5, max(1.0, font_increase_ratio))
                logger.debug(f"[排版调试-default] 文本增长比例: {increase_percentage:.3f}, 字体增长比例: {font_increase_ratio:.3f}")
                target_font_size = int(target_font_size * font_increase_ratio)
                target_scale = max(1, min(1 + increase_percentage * 0.3, 2))
                logger.debug(f"[排版调试-default] 调整后目标字体大小: {target_font_size}, 目标缩放: {target_scale:.3f}")
            else:
                target_scale = 1
                logger.debug(f"[排版调试-default] 无需字体增长，目标缩放: {target_scale}")

            font_size_scale = (((target_font_size - original_region_font_size) / original_region_font_size) * 0.4 + 1) if original_region_font_size > 0 else 1.0
            final_scale = max(font_size_scale, target_scale)
            final_scale = max(1, min(final_scale, 1.1))
            logger.debug(f"[排版调试-default] 字体大小缩放: {font_size_scale:.3f}, 最终缩放: {final_scale:.3f}")

            if final_scale > 1.001:
                logger.debug(f"[排版调试-default] 需要缩放文本框，缩放系数: {final_scale:.3f}")
                try:
                    poly = Polygon(region.unrotated_min_rect[0])
                    poly = affinity.scale(poly, xfact=final_scale, yfact=final_scale, origin='center')
                    scaled_unrotated_points = np.array(poly.exterior.coords[:4])
                    dst_points = rotate_polygons(region.center, scaled_unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                    dst_points = dst_points.reshape((-1, 4, 2))
                    logger.debug(f"[排版调试-default] 成功应用文本框缩放")
                except Exception as e:
                    dst_points = region.min_rect
                    logger.debug(f"[排版调试-default] 缩放失败，使用原始文本框: {e}")
            else:
                dst_points = region.min_rect
                logger.debug(f"[排版调试-default] 无需缩放，使用原始文本框")

            dst_points_list.append(dst_points)
            region.font_size = int(target_font_size)
            logger.debug(f"[排版调试-default] 最终字体大小: {region.font_size}")
            continue

        # --- Mode 4: smart_scaling (MODIFIED with user-defined logic) ---
        elif mode == 'smart_scaling':
            logger.debug(f"[排版调试-smart_scaling] 区域{region.blk_id if hasattr(region, 'blk_id') else '未知'}: 智能缩放模式")
            logger.debug(f"[排版调试-smart_scaling] 原始字体大小: {original_region_font_size}, 目标字体大小: {target_font_size}")
            logger.debug(f"[排版调试-smart_scaling] 原始文本框尺寸: {region.unrotated_size}")
            logger.debug(f"[排版调试-smart_scaling] 翻译文本: '{region.translation}'")
            logger.debug(f"[排版调试-smart_scaling] 多边形数量: {len(region.lines)}")
            logger.debug(f"[排版调试-smart_scaling] 文本方向: {'水平' if region.horizontal else '垂直'}")

            # Per user request, use different logic based on number of polygons
            if len(region.lines) > 1:
                logger.debug(f"[排版调试-smart_scaling-多边形] 进入多边形区域处理分支")
                # For multi-polygon regions, use the new dynamic heuristic
                from shapely.ops import unary_union

                # 1. Un-rotate all polygons and compute their union to get the true area and base shape
                try:
                    unrotated_polygons = []
                    for i, p in enumerate(region.lines):
                        # Reshape to (1, -1, 2) for rotate_polygons function
                        unrotated_p = rotate_polygons(region.center, p.reshape(1, -1, 2), region.angle, to_int=False)
                        unrotated_polygons.append(Polygon(unrotated_p.reshape(-1, 2)))
                        logger.debug(f"[排版调试-smart_scaling-多边形] 多边形{i+1}已去旋转，面积: {unrotated_polygons[-1].area:.2f}")

                    union_poly = unary_union(unrotated_polygons)
                    original_area = union_poly.area
                    # Use the envelope (axis-aligned bounding box) of the unrotated union as the base for scaling
                    unrotated_base_poly = union_poly.envelope
                    logger.debug(f"[排版调试-smart_scaling-多边形] 合并后原始面积: {original_area:.2f}")
                    logger.debug(f"[排版调试-smart_scaling-多边形] 使用外接矩形作为基础多边形")
                except Exception as e:
                    logger.warning(f"Failed to compute union of polygons: {e}")
                    original_area = region.unrotated_size[0] * region.unrotated_size[1]
                    unrotated_base_poly = Polygon(region.unrotated_min_rect[0])
                    logger.debug(f"[排版调试-smart_scaling-多边形] 回退到简单矩形，面积: {original_area:.2f}")

                # 2. Calculate required area for the text
                required_area = 0
                if region.horizontal:
                    lines, widths = text_render.calc_horizontal(target_font_size, region.translation, max_width=99999, max_height=99999, language=region.target_lang)
                    if widths:
                        required_width = max(widths)
                        required_height = len(lines) * (target_font_size * (1 + (config.render.line_spacing or 0.01)))
                        required_area = required_width * required_height
                        logger.debug(f"[排版调试-smart_scaling-多边形] 水平文本需求: 宽度{required_width:.2f}, 高度{required_height:.2f}, 面积{required_area:.2f}")
                        logger.debug(f"[排版调试-smart_scaling-多边形] 计算行数: {len(lines)}, 行宽度: {widths}")
                else: # Vertical
                    lines, heights = text_render.calc_vertical(target_font_size, region.translation, max_height=99999)
                    if heights:
                        required_height = max(heights)
                        required_width = len(lines) * (target_font_size * (1 + (config.render.line_spacing or 0.2)))
                        required_area = required_width * required_height
                        logger.debug(f"[排版调试-smart_scaling-多边形] 垂直文本需求: 宽度{required_width:.2f}, 高度{required_height:.2f}, 面积{required_area:.2f}")
                        logger.debug(f"[排版调试-smart_scaling-多边形] 计算行数: {len(lines)}, 行高度: {heights}")

                dst_points = region.min_rect # Default

                # 3. Compare areas and apply scaling heuristic
                diff_ratio = 0
                if original_area > 0 and required_area > 0:
                    diff_ratio = (required_area - original_area) / original_area
                    logger.debug(f"[排版调试-smart_scaling-多边形] 面积差异比例: {diff_ratio:.3f} (需求/原始: {required_area:.2f}/{original_area:.2f})")

                if diff_ratio > 0:
                    logger.debug(f"[排版调试-smart_scaling-多边形] 需要扩展，进入扩展分支")
                    # Box expansion ratio
                    box_expansion_ratio = diff_ratio / 2
                    box_scale_factor = 1 + min(box_expansion_ratio, 1.0) # Cap at 2x size

                    # Font shrink ratio
                    font_shrink_ratio = diff_ratio / 2 / (1 + diff_ratio)
                    font_scale_factor = 1 - min(font_shrink_ratio, 0.5) # Cap at 50% shrink
                    logger.debug(f"[排版调试-smart_scaling-多边形] 文本框扩展比例: {box_expansion_ratio:.3f}, 缩放系数: {box_scale_factor:.3f}")
                    logger.debug(f"[排版调试-smart_scaling-多边形] 字体收缩比例: {font_shrink_ratio:.3f}, 缩放系数: {font_scale_factor:.3f}")

                    # Apply scaling to the unrotated base polygon
                    try:
                        scaled_unrotated_poly = affinity.scale(unrotated_base_poly, xfact=box_scale_factor, yfact=box_scale_factor, origin='center')
                        scaled_unrotated_points = np.array(scaled_unrotated_poly.exterior.coords[:4])

                        # Rotate the scaled shape back to its original orientation
                        dst_points = rotate_polygons(region.center, scaled_unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                        logger.debug(f"[排版调试-smart_scaling-多边形] 成功应用多边形缩放")
                    except Exception as e:
                        logger.warning(f"Failed to apply dynamic scaling: {e}")
                        logger.debug(f"[排版调试-smart_scaling-多边形] 缩放失败，使用原始文本框")

                    target_font_size = int(target_font_size * font_scale_factor)
                    logger.debug(f"[排版调试-smart_scaling-多边形] 调整后字体大小: {target_font_size}")
                elif diff_ratio < 0:
                    logger.debug(f"[排版调试-smart_scaling-多边形] 文本较小，进入字体放大分支")
                    # If text is smaller, enlarge font to fill the box
                    try:
                        area_ratio = original_area / required_area
                        font_scale_factor = np.sqrt(area_ratio)
                        target_font_size = int(target_font_size * font_scale_factor)
                        unrotated_points = np.array(unrotated_base_poly.exterior.coords[:4])
                        dst_points = rotate_polygons(region.center, unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                        logger.debug(f"[排版调试-smart_scaling-多边形] 面积比例: {area_ratio:.3f}, 字体缩放系数: {font_scale_factor:.3f}")
                        logger.debug(f"[排版调试-smart_scaling-多边形] 调整后字体大小: {target_font_size}")
                    except Exception as e:
                        logger.warning(f"Failed to apply font enlargement: {e}")
                        logger.debug(f"[排版调试-smart_scaling-多边形] 字体放大失败")
                else:
                    logger.debug(f"[排版调试-smart_scaling-多边形] 无需调整，使用基础多边形")
                    # If no scaling is needed, still use the calculated base polygon for rendering
                    try:
                        unrotated_points = np.array(unrotated_base_poly.exterior.coords[:4])
                        dst_points = rotate_polygons(region.center, unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                    except Exception as e:
                        logger.warning(f"Failed to use base polygon: {e}")
                        logger.debug(f"[排版调试-smart_scaling-多边形] 使用基础多边形失败")

                dst_points_list.append(dst_points)
                region.font_size = int(target_font_size)
                logger.debug(f"[排版调试-smart_scaling-多边形] 最终字体大小: {region.font_size}")
                continue

            else: # For single-polygon regions, use the new dynamic heuristic
                logger.debug(f"[排版调试-smart_scaling-单边形] 进入单边形区域处理分支")
                # 1. Calculate original area
                original_area = region.unrotated_size[0] * region.unrotated_size[1]
                logger.debug(f"[排版调试-smart_scaling-单边形] 原始面积: {original_area:.2f} (尺寸: {region.unrotated_size})")

                # 2. Calculate required area
                required_area = 0
                if region.horizontal:
                    lines, widths = text_render.calc_horizontal(target_font_size, region.translation, max_width=99999, max_height=99999, language=region.target_lang)
                    if widths:
                        required_width = max(widths)
                        required_height = len(lines) * (target_font_size * (1 + (config.render.line_spacing or 0.01)))
                        required_area = required_width * required_height
                        logger.debug(f"[排版调试-smart_scaling-单边形] 水平文本需求: 宽度{required_width:.2f}, 高度{required_height:.2f}, 面积{required_area:.2f}")
                        logger.debug(f"[排版调试-smart_scaling-单边形] 计算行数: {len(lines)}, 行宽度: {widths}")
                else: # Vertical
                    lines, heights = text_render.calc_vertical(target_font_size, region.translation, max_height=99999)
                    if heights:
                        required_height = max(heights)
                        required_width = len(lines) * (target_font_size * (1 + (config.render.line_spacing or 0.2)))
                        required_area = required_width * required_height
                        logger.debug(f"[排版调试-smart_scaling-单边形] 垂直文本需求: 宽度{required_width:.2f}, 高度{required_height:.2f}, 面积{required_area:.2f}")
                        logger.debug(f"[排版调试-smart_scaling-单边形] 计算行数: {len(lines)}, 行高度: {heights}")

                dst_points = region.min_rect # Default

                # 3. Compare and apply user's dynamic heuristic
                diff_ratio = 0
                if original_area > 0 and required_area > 0:
                    diff_ratio = (required_area - original_area) / original_area
                    logger.debug(f"[排版调试-smart_scaling-单边形] 面积差异比例: {diff_ratio:.3f} (需求/原始: {required_area:.2f}/{original_area:.2f})")

                if diff_ratio > 0:
                    logger.debug(f"[排版调试-smart_scaling-单边形] 需要扩展，进入扩展分支")
                    # Box expansion ratio
                    box_expansion_ratio = diff_ratio / 2
                    box_scale_factor = 1 + min(box_expansion_ratio, 1.0) # Cap at 2x size

                    # Font shrink ratio
                    font_shrink_ratio = diff_ratio / 2 / (1 + diff_ratio)
                    font_scale_factor = 1 - min(font_shrink_ratio, 0.5) # Cap at 50% shrink
                    logger.debug(f"[排版调试-smart_scaling-单边形] 文本框扩展比例: {box_expansion_ratio:.3f}, 缩放系数: {box_scale_factor:.3f}")
                    logger.debug(f"[排版调试-smart_scaling-单边形] 字体收缩比例: {font_shrink_ratio:.3f}, 缩放系数: {font_scale_factor:.3f}")

                    # Apply scaling
                    try:
                        poly = Polygon(region.unrotated_min_rect[0])
                        poly = affinity.scale(poly, xfact=box_scale_factor, yfact=box_scale_factor, origin='center')
                        scaled_unrotated_points = np.array(poly.exterior.coords[:4])
                        dst_points = rotate_polygons(region.center, scaled_unrotated_points.reshape(1, -1), -region.angle, to_int=False).reshape(-1, 4, 2)
                        logger.debug(f"[排版调试-smart_scaling-单边形] 成功应用动态缩放")
                    except Exception as e:
                        logger.warning(f"Failed to apply dynamic scaling: {e}")
                        logger.debug(f"[排版调试-smart_scaling-单边形] 缩放失败，使用原始文本框")

                    target_font_size = int(target_font_size * font_scale_factor)
                    logger.debug(f"[排版调试-smart_scaling-单边形] 调整后字体大小: {target_font_size}")
                elif diff_ratio < 0:
                    logger.debug(f"[排版调试-smart_scaling-单边形] 文本较小，进入字体放大分支")
                    # If text is smaller, enlarge font to fill the box
                    try:
                        area_ratio = original_area / required_area
                        font_scale_factor = np.sqrt(area_ratio)
                        target_font_size = int(target_font_size * font_scale_factor)
                        logger.debug(f"[排版调试-smart_scaling-单边形] 面积比例: {area_ratio:.3f}, 字体缩放系数: {font_scale_factor:.3f}")
                        logger.debug(f"[排版调试-smart_scaling-单边形] 调整后字体大小: {target_font_size}")
                    except Exception as e:
                        logger.warning(f"Failed to apply font enlargement: {e}")
                        logger.debug(f"[排版调试-smart_scaling-单边形] 字体放大失败")
                else:
                    logger.debug(f"[排版调试-smart_scaling-单边形] 无需调整")

                dst_points_list.append(dst_points)
                region.font_size = int(target_font_size)
                logger.debug(f"[排版调试-smart_scaling-单边形] 最终字体大小: {region.font_size}")
                continue

        # --- Fallback for any other modes (e.g., 'fixed_font') ---
        else:
            logger.debug(f"[排版调试-fallback] 区域{region.blk_id if hasattr(region, 'blk_id') else '未知'}: 未知模式 '{mode}'，使用回退处理")
            logger.debug(f"[排版调试-fallback] 原始字体大小: {original_region_font_size}, 目标字体大小: {target_font_size}")
            logger.debug(f"[排版调试-fallback] 原始文本框尺寸: {region.unrotated_size}")
            logger.debug(f"[排版调试-fallback] 翻译文本: '{region.translation}'")
            dst_points_list.append(region.min_rect)
            region.font_size = int(min(target_font_size, 512))
            logger.debug(f"[排版调试-fallback] 最终字体大小: {region.font_size} (限制在512以下)")
            continue

    logger.debug(f"[排版调试] 完成所有区域处理，共处理 {len(text_regions)} 个区域")
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
    logger.debug(f"[渲染调试] 开始渲染区域{region.blk_id if hasattr(region, 'blk_id') else '未知'}")
    logger.debug(f"[渲染调试] 文本内容: '{region.get_translation_for_rendering()}'")
    logger.debug(f"[渲染调试] 字体大小: {region.font_size}")
    logger.debug(f"[渲染调试] 目标点坐标: {dst_points.shape if hasattr(dst_points, 'shape') else type(dst_points)}")
    logger.debug(f"[渲染调试] 连字符处理: {hyphenate}, 行间距: {line_spacing}, 禁用字体边框: {disable_font_border}")
    logger.debug(f"[渲染调试] 当前排版模式: {config.render.layout_mode}")
    # --- START BRUTEFORCE COLOR FIX ---
    fg = (0, 0, 0) # Default to black
    logger.debug(f"[渲染调试-颜色] 开始处理颜色配置")
    try:
        # Priority 1: Check for the original hex string from the UI
        if hasattr(region, 'font_color') and isinstance(region.font_color, str) and region.font_color.startswith('#'):
            hex_c = region.font_color
            if len(hex_c) == 7:
                r = int(hex_c[1:3], 16)
                g = int(hex_c[3:5], 16)
                b = int(hex_c[5:7], 16)
                fg = (r, g, b)
                logger.debug(f"[渲染调试-颜色] 使用十六进制前景色: {hex_c} -> RGB{fg}")
        # Priority 2: Check for a pre-converted tuple
        elif hasattr(region, 'fg_colors') and isinstance(region.fg_colors, (tuple, list)) and len(region.fg_colors) == 3:
            fg = tuple(region.fg_colors)
            logger.debug(f"[渲染调试-颜色] 使用预转换前景色: RGB{fg}")
        # Last resort: Use the method
        else:
            fg, _ = region.get_font_colors()
            logger.debug(f"[渲染调试-颜色] 使用方法获取前景色: RGB{fg}")
    except Exception as e:
        # If anything fails, fg remains black
        logger.debug(f"[渲染调试-颜色] 获取前景色失败，使用默认黑色: {e}")
        pass

    # Get background color separately
    _, bg = region.get_font_colors()
    logger.debug(f"[渲染调试-颜色] 背景色: RGB{bg}")
    # --- END BRUTEFORCE COLOR FIX ---

    # Convert hex color string to RGB tuple, if necessary
    if isinstance(fg, str) and fg.startswith('#') and len(fg) == 7:
        try:
            r = int(fg[1:3], 16)
            g = int(fg[3:5], 16)
            b = int(fg[5:7], 16)
            fg = (r, g, b)
            logger.debug(f"[渲染调试-颜色] 再次转换十六进制颜色: RGB{fg}")
        except ValueError:
            fg = (0, 0, 0)  # Default to black on error
            logger.debug(f"[渲染调试-颜色] 十六进制转换失败，使用默认黑色")
    elif not isinstance(fg, (tuple, list)):
        fg = (0, 0, 0) # Default to black if format is unexpected
        logger.debug(f"[渲染调试-颜色] 颜色格式异常，使用默认黑色")

    fg, bg = fg_bg_compare(fg, bg)
    logger.debug(f"[渲染调试-颜色] 颜色对比调整后 - 前景色: RGB{fg}, 背景色: RGB{bg}")

    if disable_font_border :
        bg = None
        logger.debug(f"[渲染调试-颜色] 禁用字体边框，背景色设为None")

    middle_pts = (dst_points[:, [1, 2, 3, 0]] + dst_points) / 2
    norm_h = np.linalg.norm(middle_pts[:, 1] - middle_pts[:, 3], axis=1)
    norm_v = np.linalg.norm(middle_pts[:, 2] - middle_pts[:, 0], axis=1)
    r_orig = np.mean(norm_h / norm_v)
    logger.debug(f"[渲染调试-尺寸] 计算中点和法向量")
    logger.debug(f"[渲染调试-尺寸] 水平法向量: {norm_h}")
    logger.debug(f"[渲染调试-尺寸] 垂直法向量: {norm_v}")
    logger.debug(f"[渲染调试-尺寸] 原始宽高比: {r_orig:.3f}")

    forced_direction = region._direction if hasattr(region, "_direction") else region.direction
    logger.debug(f"[渲染调试-方向] 强制方向设置: {forced_direction}")
    logger.debug(f"[渲染调试-方向] 区域原始水平属性: {region.horizontal}")
    if forced_direction != "auto":
        if forced_direction in ["horizontal", "h"]:
            render_horizontally = True
            logger.debug(f"[渲染调试-方向] 强制使用水平渲染")
        elif forced_direction in ["vertical", "v"]:
            render_horizontally = False
            logger.debug(f"[渲染调试-方向] 强制使用垂直渲染")
        else:
            render_horizontally = region.horizontal
            logger.debug(f"[渲染调试-方向] 使用区域原始方向: {'水平' if render_horizontally else '垂直'}")
    else:
        render_horizontally = region.horizontal
        logger.debug(f"[渲染调试-方向] 自动选择方向: {'水平' if render_horizontally else '垂直'}")

    logger.debug(f"[渲染调试-文本渲染] 开始{'水平' if render_horizontally else '垂直'}文本渲染")
    logger.debug(f"[渲染调试-文本渲染] 渲染区域尺寸: 宽度{round(norm_h[0])}, 高度{round(norm_v[0])}")
    logger.debug(f"[渲染调试-文本渲染] 对齐方式: {region.alignment}")
    logger.debug(f"[渲染调试-文本渲染] 文本方向: {'从右到左' if region.direction == 'hl' else '从左到右'}")
    logger.debug(f"[渲染调试-文本渲染] 目标语言: {region.target_lang}")

    if render_horizontally:
        temp_box = text_render.put_text_horizontal(
            region.font_size,
            region.get_translation_for_rendering(),
            round(norm_h[0]),
            round(norm_v[0]),
            region.alignment,
            region.direction == 'hl',
            fg,
            bg,
            region.target_lang,
            hyphenate,
            line_spacing,
            config
        )
        logger.debug(f"[渲染调试-文本渲染] 水平渲染完成")
    else:
        temp_box = text_render.put_text_vertical(
            region.font_size,
            region.get_translation_for_rendering(),
            round(norm_v[0]),
            region.alignment,
            fg,
            bg,
            line_spacing,
        )
        logger.debug(f"[渲染调试-文本渲染] 垂直渲染完成")
    h, w, _ = temp_box.shape
    logger.debug(f"[渲染调试-尺寸] 渲染完成，临时文本框尺寸: 宽度{w}, 高度{h}")
    if h == 0 or w == 0:
        logger.warning(f"Skipping rendering for region with invalid dimensions (w={w}, h={h}). Text: '{region.translation}'")
        logger.debug(f"[渲染调试-错误] 跳过无效尺寸的区域")
        return img
    r_temp = w / h
    logger.debug(f"[渲染调试-尺寸] 临时文本框宽高比: {r_temp:.3f}")

    box = None
    logger.debug(f"[渲染调试-变形] 开始文本框变形处理")
    logger.debug(f"[渲染调试-变形] 文本方向: {'水平' if region.horizontal else '垂直'}")
    logger.debug(f"[渲染调试-变形] 临时文本框比例{r_temp:.3f} vs 原始比例{r_orig:.3f}")
    if region.horizontal:
        if r_temp > r_orig:
            h_ext = int((w / r_orig - h) // 2) if r_orig > 0 else 0
            logger.debug(f"[渲染调试-变形-水平] 需要高度扩展: {h_ext}")
            if h_ext >= 0:
                box = np.zeros((h + h_ext * 2, w, 4), dtype=np.uint8)
                box[h_ext:h_ext+h, 0:w] = temp_box
                logger.debug(f"[渲染调试-变形-水平] 扩展后尺寸: {box.shape[1]}x{box.shape[0]}")
            else:
                box = temp_box.copy()
                logger.debug(f"[渲染调试-变形-水平] 使用原始尺寸")
        else:
            w_ext = int((h * r_orig - w) // 2)
            logger.debug(f"[渲染调试-变形-水平] 需要宽度扩展: {w_ext}")
            if w_ext >= 0:
                box = np.zeros((h, w + w_ext * 2, 4), dtype=np.uint8)
                box[0:h, 0:w] = temp_box
                logger.debug(f"[渲染调试-变形-水平] 扩展后尺寸: {box.shape[1]}x{box.shape[0]}")
            else:
                box = temp_box.copy()
                logger.debug(f"[渲染调试-变形-水平] 使用原始尺寸")
    else:
        if r_temp > r_orig:
            h_ext = int(w / (2 * r_orig) - h / 2) if r_orig > 0 else 0
            logger.debug(f"[渲染调试-变形-垂直] 需要高度扩展: {h_ext}")
            if h_ext >= 0:
                box = np.zeros((h + h_ext * 2, w, 4), dtype=np.uint8)
                box[0:h, 0:w] = temp_box
                logger.debug(f"[渲染调试-变形-垂直] 扩展后尺寸: {box.shape[1]}x{box.shape[0]}")
            else:
                box = temp_box.copy()
                logger.debug(f"[渲染调试-变形-垂直] 使用原始尺寸")
        else:
            w_ext = int((h * r_orig - w) / 2)
            logger.debug(f"[渲染调试-变形-垂直] 需要宽度扩展: {w_ext}")
            if w_ext >= 0:
                box = np.zeros((h, w + w_ext * 2, 4), dtype=np.uint8)
                box[0:h, w_ext:w_ext+w] = temp_box
                logger.debug(f"[渲染调试-变形-垂直] 扩展后尺寸: {box.shape[1]}x{box.shape[0]}")
            else:
                box = temp_box.copy()
                logger.debug(f"[渲染调试-变形-垂直] 使用原始尺寸")   

    src_points = np.array([[0, 0], [box.shape[1], 0], [box.shape[1], box.shape[0]], [0, box.shape[0]]]).astype(np.float32)
    logger.debug(f"[渲染调试-变换] 源点坐标: {src_points}")
    logger.debug(f"[渲染调试-变换] 目标点坐标: {dst_points}")

    M, _ = cv2.findHomography(src_points, dst_points, cv2.RANSAC, 5.0)
    logger.debug(f"[渲染调试-变换] 同态变换矩阵计算完成")
    rgba_region = cv2.warpPerspective(box, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    logger.debug(f"[渲染调试-变换] 透视变换完成，输出尺寸: {rgba_region.shape}")
    x, y, w, h = cv2.boundingRect(np.round(dst_points).astype(np.int64))
    logger.debug(f"[渲染调试-变换] 边界矩形: x={x}, y={y}, w={w}, h={h}")
    canvas_region = rgba_region[y:y+h, x:x+w, :3]
    mask_region = rgba_region[y:y+h, x:x+w, 3:4].astype(np.float32) / 255.0
    logger.debug(f"[渲染调试-变换] 提取渲染区域，尺寸: {canvas_region.shape}")
    img[y:y+h, x:x+w] = np.clip((img[y:y+h, x:x+w].astype(np.float32) * (1 - mask_region) + canvas_region.astype(np.float32) * mask_region), 0, 255).astype(np.uint8)
    logger.debug(f"[渲染调试-变换] 渲染区域已合并到原图")
    logger.debug(f"[渲染调试] 区域{region.blk_id if hasattr(region, 'blk_id') else '未知'}渲染完成")
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