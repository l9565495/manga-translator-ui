import re
import time
import asyncio
import json
from typing import List, Tuple, Dict, Any
from abc import abstractmethod
import numpy as np
import cv2

from ..utils import InfererModule, ModelWrapper, repeating_sequence, is_valuable_text

try:
    import readline
except Exception:
    readline = None

VALID_LANGUAGES = {
    'CHS': 'Chinese (Simplified)',
    'CHT': 'Chinese (Traditional)',
    'CSY': 'Czech',
    'NLD': 'Dutch',
    'ENG': 'English',
    'FRA': 'French',
    'DEU': 'German',
    'HUN': 'Hungarian',
    'ITA': 'Italian',
    'JPN': 'Japanese',
    'KOR': 'Korean',
    'POL': 'Polish',
    'PTB': 'Portuguese (Brazil)',
    'ROM': 'Romanian',
    'RUS': 'Russian',
    'ESP': 'Spanish',
    'TRK': 'Turkish',
    'UKR': 'Ukrainian',
    'VIN': 'Vietnamese',
    'ARA': 'Arabic',
    'CNR': 'Montenegrin',
    'SRP': 'Serbian',
    'HRV': 'Croatian',
    'THA': 'Thai',
    'IND': 'Indonesian',
    'FIL': 'Filipino (Tagalog)'
}

ISO_639_1_TO_VALID_LANGUAGES = {
    'zh': 'CHS',
    'ja': 'JPN',
    'en': 'ENG',
    'ko': 'KOR',
    'vi': 'VIN',
    'cs': 'CSY',
    'nl': 'NLD',
    'fr': 'FRA',
    'de': 'DEU',
    'hu': 'HUN',
    'it': 'ITA',
    'pl': 'POL',
    'pt': 'PTB',
    'ro': 'ROM',
    'ru': 'RUS',
    'es': 'ESP',
    'tr': 'TRK',
    'uk': 'UKR',
    'vi': 'VIN',
    'ar': 'ARA',
    'cnr': 'CNR',
    'sr': 'SRP',
    'hr': 'HRV',
    'th': 'THA',
    'id': 'IND',
    'tl': 'FIL'
}

class InvalidServerResponse(Exception):
    pass

class MissingAPIKeyException(Exception):
    pass

class LanguageUnsupportedException(Exception):
    def __init__(self, language_code: str, translator: str = None, supported_languages: List[str] = None):
        error = 'Language not supported for %s: "%s"' % (translator if translator else 'chosen translator', language_code)
        if supported_languages:
            error += '. Supported languages: "%s"' % ','.join(supported_languages)
        super().__init__(error)

class BRMarkersValidationException(Exception):
    """AI断句检查失败异常"""
    def __init__(self, missing_count: int, total_count: int, tolerance: int):
        self.missing_count = missing_count
        self.total_count = total_count
        self.tolerance = tolerance
        super().__init__(
            f"AI断句检查失败：{missing_count}/{total_count} 条翻译缺失[BR]标记（容忍度：{tolerance}）"
        )

class MultimodalUnsupportedException(Exception):
    """模型不支持多模态输入异常"""
    def __init__(self, model_name: str, translator: str):
        self.model_name = model_name
        self.translator = translator
        super().__init__(
            f"模型 {model_name} 不支持多模态输入（图片+文本）"
        )

def draw_text_boxes_on_image(image, text_regions: List[Any], text_order: List[int], 
                             upscaled_size: Tuple[int, int] = None):
    """
    在图片上绘制带编号的文本框
    
    Args:
        image: 原始图片 (numpy array 或 PIL Image)
        text_regions: 文本区域列表，每个区域应该有 xyxy 或 min_rect 属性
        text_order: 文本顺序列表，对应每个文本框的编号
        upscaled_size: 超分后的图片尺寸 (height, width)，用于坐标转换。如果为None则不转换
    
    Returns:
        绘制了文本框的图片（与输入类型相同）
    """
    if image is None or len(text_regions) == 0:
        return image
    
    # 检查是否为PIL Image，如果是则转换为numpy数组
    from PIL import Image as PILImage
    is_pil = isinstance(image, PILImage.Image)
    if is_pil:
        # 处理各种图片模式，统一转换为RGB
        pil_image = image
        if pil_image.mode == "P":
            pil_image = pil_image.convert("RGBA" if "transparency" in pil_image.info else "RGB")
        if pil_image.mode == "RGBA":
            background = PILImage.new('RGB', pil_image.size, (255, 255, 255))
            background.paste(pil_image, mask=pil_image.split()[-1])
            pil_image = background
        elif pil_image.mode in ("LA", "L", "1", "CMYK"):
            if pil_image.mode == "LA":
                pil_image = pil_image.convert("RGBA")
                background = PILImage.new('RGB', pil_image.size, (255, 255, 255))
                background.paste(pil_image, mask=pil_image.split()[-1])
                pil_image = background
            else:
                pil_image = pil_image.convert("RGB")
        elif pil_image.mode != "RGB":
            pil_image = pil_image.convert("RGB")
        canvas = np.array(pil_image)
    else:
        canvas = image.copy()
    
    h, w = canvas.shape[:2]
    
    # 计算坐标缩放比例（超分坐标 -> 原图坐标）
    scale_x, scale_y = 1.0, 1.0
    if upscaled_size is not None:
        upscaled_h, upscaled_w = upscaled_size
        if upscaled_w > 0 and upscaled_h > 0:
            scale_x = w / upscaled_w
            scale_y = h / upscaled_h
    
    # 计算线宽
    lw = max(round(sum(canvas.shape[:2]) / 2 * 0.003), 2)
    
    # 定义多种颜色（RGB格式）
    colors = [
        (255, 0, 0),     # 红
        (0, 255, 0),     # 绿
        (0, 0, 255),     # 蓝
        (255, 165, 0),   # 橙
        (128, 0, 128),   # 紫
        (0, 255, 255),   # 青
        (255, 0, 255),   # 品红
        (255, 255, 0),   # 黄
        (0, 128, 0),     # 深绿
        (128, 0, 0),     # 深红
    ]
    
    # 先收集所有框的边界信息
    all_boxes = []
    for region in text_regions:
        if hasattr(region, 'xyxy'):
            x1, y1, x2, y2 = region.xyxy
            x1, x2 = x1 * scale_x, x2 * scale_x
            y1, y2 = y1 * scale_y, y2 * scale_y
            all_boxes.append((int(x1), int(y1), int(x2), int(y2)))
        elif hasattr(region, 'min_rect'):
            pts = region.min_rect.astype(np.float64)
            pts[:, 0] *= scale_x
            pts[:, 1] *= scale_y
            bx1, by1 = int(pts[:, 0].min()), int(pts[:, 1].min())
            bx2, by2 = int(pts[:, 0].max()), int(pts[:, 1].max())
            all_boxes.append((bx1, by1, bx2, by2))
    
    def check_overlap(lx, ly, lw_size, lh_size, exclude_idx):
        """检查标签区域是否与其他框重叠"""
        label_rect = (lx, ly - lh_size, lx + lw_size, ly)
        for i, (bx1, by1, bx2, by2) in enumerate(all_boxes):
            if i == exclude_idx:
                continue
            # 检查矩形是否重叠
            if not (label_rect[2] < bx1 or label_rect[0] > bx2 or label_rect[3] < by1 or label_rect[1] > by2):
                return True
        return False
    
    # 遍历每个文本区域并绘制
    for idx, region in enumerate(text_regions):
        if idx >= len(text_order):
            break
            
        order_num = text_order[idx]
        color = colors[idx % len(colors)]
        
        # 获取文本框坐标并转换
        # 边框向外扩展，避免粗边框覆盖文字内容
        expand = lw  # 向外扩展的像素数（等于线宽）
        
        if hasattr(region, 'xyxy'):
            x1, y1, x2, y2 = region.xyxy
            x1, x2 = x1 * scale_x, x2 * scale_x
            y1, y2 = y1 * scale_y, y2 * scale_y
            # 向外扩展边框
            box_x1, box_y1 = int(x1) - expand, int(y1) - expand
            box_x2, box_y2 = int(x2) + expand, int(y2) + expand
            cv2.rectangle(canvas, (box_x1, box_y1), (box_x2, box_y2), color, lw)
        elif hasattr(region, 'min_rect'):
            pts = region.min_rect.astype(np.float64)
            pts[:, 0] *= scale_x
            pts[:, 1] *= scale_y
            # 计算中心点，向外扩展多边形
            center_x = pts[:, 0].mean()
            center_y = pts[:, 1].mean()
            for i in range(len(pts)):
                dx = pts[i, 0] - center_x
                dy = pts[i, 1] - center_y
                dist = np.sqrt(dx*dx + dy*dy)
                if dist > 0:
                    pts[i, 0] += (dx / dist) * expand
                    pts[i, 1] += (dy / dist) * expand
            pts = pts.astype(np.int32)
            cv2.polylines(canvas, [pts], True, color, lw)
            box_x1, box_y1 = int(pts[:, 0].min()), int(pts[:, 1].min())
            box_x2, box_y2 = int(pts[:, 0].max()), int(pts[:, 1].max())
        else:
            continue
        
        # 绘制编号标签
        label_text = str(order_num)
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = max(lw / 2, 0.6)
        font_thickness = max(lw, 2)
        
        (text_width, text_height), _ = cv2.getTextSize(label_text, font, font_scale, font_thickness)
        margin = 3
        
        # 四个候选位置：上、下、左、右
        candidates = [
            (box_x1, box_y1 - margin),                          # 上
            (box_x1, box_y2 + text_height + margin),            # 下
            (box_x1 - text_width - margin, box_y1 + text_height), # 左
            (box_x2 + margin, box_y1 + text_height),            # 右
        ]
        
        # 选择不重叠且在图片范围内的位置
        label_x, label_y = candidates[0]  # 默认上方
        for cx, cy in candidates:
            # 检查是否在图片范围内
            if cx < 0 or cy - text_height < 0 or cx + text_width > w or cy > h:
                continue
            # 检查是否与其他框重叠
            if not check_overlap(cx, cy, text_width, text_height, idx):
                label_x, label_y = cx, cy
                break
        
        # 最终边界检查
        label_x = max(0, min(label_x, w - text_width))
        label_y = max(text_height, min(label_y, h))
        
        # 绘制编号文本（带黑色描边）
        cv2.putText(canvas, label_text, (label_x, label_y), font, font_scale, (0, 0, 0), font_thickness + 2, cv2.LINE_AA)
        cv2.putText(canvas, label_text, (label_x, label_y), font, font_scale, color, font_thickness, cv2.LINE_AA)
    
    # 如果输入是PIL Image，转换回PIL格式
    if is_pil:
        return PILImage.fromarray(canvas)
    return canvas


class MTPEAdapter():
    async def dispatch(self, queries: List[str], translations: List[str]) -> List[str]:
        # TODO: Make it work in windows (e.g. through os.startfile)
        if not readline:
            print('MTPE is currently only supported on linux')
            return translations
        new_translations = []
        print('Running Machine Translation Post Editing (MTPE)')
        for i, (query, translation) in enumerate(zip(queries, translations)):
            print(f'\n[{i + 1}/{len(queries)}] {query}:')
            readline.set_startup_hook(lambda: readline.insert_text(translation.replace('\n', '\\n')))
            new_translation = ''
            try:
                new_translation = input(' -> ').replace('\\n', '\n')
            finally:
                readline.set_startup_hook()
            new_translations.append(new_translation)
        print()
        return new_translations

class CommonTranslator(InfererModule):
    # Translator has to support all languages listed in here. The language codes will be resolved into
    # _LANGUAGE_CODE_MAP[lang_code] automatically if _LANGUAGE_CODE_MAP is a dict.
    # If it is a list it will simply return the language code as is.
    _LANGUAGE_CODE_MAP = {}

    # The amount of repeats upon detecting an invalid translation.
    # Use with _is_translation_invalid and _modify_invalid_translation_query.
    _INVALID_REPEAT_COUNT = 0

    # Will sleep for the rest of the minute if the request count is over this number.
    _MAX_REQUESTS_PER_MINUTE = -1

    def __init__(self):
        super().__init__()
        self.mtpe_adapter = MTPEAdapter()
        self._last_request_ts = 0
        self.enable_post_translation_check = False
        self.post_check_repetition_threshold = 5
        self.post_check_max_retry_attempts = 2
        self.attempts = -1
        self._MAX_SPLIT_ATTEMPTS = 3  # 最大分割层级
        self._SPLIT_THRESHOLD = 2  # 重试N次后触发分割
        self._global_attempt_count = 0  # 全局尝试计数器
        self._max_total_attempts = -1  # 全局最大尝试次数
        self._cancel_check_callback = None  # 取消检查回调
    
    def set_cancel_check_callback(self, callback):
        """设置取消检查回调"""
        self._cancel_check_callback = callback
    
    def _check_cancelled(self):
        """检查任务是否被取消"""
        if self._cancel_check_callback and self._cancel_check_callback():
            raise asyncio.CancelledError("Translation cancelled by user")

    def _get_retry_temperature(self, base_temperature: float, retry_attempt: int, retry_reason: str = "") -> float:
        """
        根据重试次数和原因动态调整温度，帮助模型跳出错误模式
        
        Args:
            base_temperature: 基础温度（首次请求使用）
            retry_attempt: 当前重试次数（0表示首次请求）
            retry_reason: 重试原因（模型输出问题才提高温度，网络/链接错误不提高）
            
        Returns:
            调整后的温度值
        """
        if retry_attempt <= 0:
            return base_temperature
        
        # 只有模型输出问题才提高温度（数量不匹配、质量检查失败、BR检查失败）
        # 网络错误、链接错误、返回空内容等不需要提高温度
        should_increase_temp = (
            "Translation count mismatch" in retry_reason or
            "Quality check failed" in retry_reason or 
            "BR markers missing" in retry_reason
        )
        
        if not should_increase_temp:
            return base_temperature
        
        # 每次重试增加 0.2，最高不超过 1.0
        adjusted_temp = base_temperature + (retry_attempt * 0.2)
        return min(adjusted_temp, 1.0)

    def _get_retry_hint(self, attempt: int, reason: str = "") -> str:
        """
        生成重试提示信息，用于避免模型服务器缓存导致的重复错误
        
        Args:
            attempt: 当前尝试次数
            reason: 重试原因（可选）
            
        Returns:
            重试提示字符串
        """
        hints = [
            f"[Retry attempt #{attempt}]",
            f"[This is attempt #{attempt}, please provide a different response]",
            f"[Attempt {attempt}: Previous response had issues, please try again]",
            f"[Retry #{attempt}: Please ensure quality this time]",
            f"[Attempt {attempt} - Previous attempts failed quality check]"
        ]
        
        # 根据尝试次数选择不同的提示（循环使用）
        base_hint = hints[(attempt - 1) % len(hints)]
        
        # 如果提供了原因，添加到提示中
        if reason:
            return f"{base_hint} Reason: {reason}\n\n"
        else:
            return f"{base_hint}\n\n"
    
    def _build_user_prompt_for_texts(self, texts: List[str], ctx=None, prev_context: str = "", retry_attempt: int = 0, retry_reason: str = "") -> str:
        """
        统一的用户提示词构建方法（纯文本翻译）
        适用于 openai.py 和 gemini.py

        Args:
            texts: 要翻译的文本列表
            ctx: 上下文对象（可选）
            prev_context: 历史上下文（可选）
            retry_attempt: 重试次数（可选，用于避免缓存）
            retry_reason: 重试原因（可选）

        Returns:
            构建好的用户提示词字符串
        """
        # 检查是否开启AI断句
        enable_ai_break = False
        if ctx and hasattr(ctx, 'config') and ctx.config and hasattr(ctx.config, 'render'):
            enable_ai_break = getattr(ctx.config.render, 'disable_auto_wrap', False)

        prompt = ""

        # 添加重试提示到最前面（如果是重试）
        if retry_attempt > 0:
            prompt += self._get_retry_hint(retry_attempt, retry_reason) + "\n"

        # 添加多页上下文（如果有）
        if prev_context:
            prompt += f"{prev_context}\n\n---\n\n"
            self.logger.info(f"[历史上下文] 长度: {len(prev_context)} 字符")
            self.logger.info(f"[历史上下文内容]\n{prev_context[:500]}...")
        else:
            self.logger.info(f"[历史上下文] 无历史上下文（可能是第一张图片或context_size=0）")

        prompt += "Please translate the following manga text regions. The input is provided as a JSON array:\n\n"

        input_data = []
        for i, text in enumerate(texts):
            text_to_translate = text.replace('\n', ' ').replace('\ufffd', '')
            item = {
                "id": i + 1,
                "text": text_to_translate
            }
            # 只有开启AI断句时才添加区域信息
            if enable_ai_break and ctx and hasattr(ctx, 'text_regions') and ctx.text_regions and i < len(ctx.text_regions):
                region = ctx.text_regions[i]
                region_count = len(region.lines) if hasattr(region, 'lines') else 1
                item["original_region_count"] = region_count
            
            input_data.append(item)

        prompt += json.dumps(input_data, ensure_ascii=False, indent=2)

        prompt += "\n\nCRITICAL: Provide translations in the exact same order as the input array. Your output must be a JSON array of strings corresponding to the IDs."

        return prompt

    def _build_unified_user_prompt(self, batch_data: List[Dict], ctx=None, prev_context: str = "", retry_attempt: int = 0, retry_reason: str = "", is_image_mode: bool = True) -> str:
        """
        统一的用户提示词构建方法（支持多模态和纯文本）
        Unified user prompt builder for both multimodal and text-only modes.

        Args:
            batch_data: List of dicts, each containing 'original_texts' and optional 'text_regions'.
            ctx: Context object.
            prev_context: Previous context string.
            retry_attempt: Retry attempt count.
            retry_reason: Reason for retry.
            is_image_mode: Whether to include image-specific descriptions.

        Returns:
            Constructed user prompt string.
        """
        import json
        
        # 检查是否开启AI断句
        enable_ai_break = False
        if ctx and hasattr(ctx, 'config') and ctx.config and hasattr(ctx.config, 'render'):
            enable_ai_break = getattr(ctx.config.render, 'disable_auto_wrap', False)

        prompt = ""

        # 添加重试提示到最前面（如果是重试）
        if retry_attempt > 0:
            prompt += self._get_retry_hint(retry_attempt, retry_reason) + "\n"

        # 添加多页上下文（如果有）
        if prev_context:
            prompt += f"{prev_context}\n\n---\n\n"
            self.logger.info(f"[Context] Length: {len(prev_context)} chars")
        else:
            self.logger.info(f"[Context] None")

        if is_image_mode:
            prompt += "Please translate the following manga text regions. I'm providing multiple images with their text regions in reading order:\n\n"
            # 添加图片信息
            for i, data in enumerate(batch_data):
                prompt += f"=== Image {i+1} ===\n"
                prompt += f"Text regions ({len(data['original_texts'])} regions):\n"
                for j, text in enumerate(data['original_texts']):
                    prompt += f"  {j+1}. {text}\n"
                prompt += "\n"
        else:
            prompt += "Please translate the following manga text regions:\n\n"

        prompt += "All texts to translate (JSON Array):\n"
        input_data = []
        text_index = 1
        for img_idx, data in enumerate(batch_data):
            # 获取 text_regions 用于 AI 断句
            text_regions = data.get('text_regions', [])
            
            for region_idx, text in enumerate(data['original_texts']):
                # 预处理文本：移除换行符
                text_clean = text.replace('\n', ' ').replace('\ufffd', '')
                
                item = {
                    "id": text_index,
                    "text": text_clean
                }
                
                # AI 断句逻辑：获取 original_region_count
                if enable_ai_break:
                    region_count = 1
                    # 尝试从 text_regions 获取
                    if text_regions and region_idx < len(text_regions):
                        region = text_regions[region_idx]
                        if hasattr(region, 'lines') and region.lines is not None:
                            region_count = len(region.lines)
                        elif isinstance(region, dict) and 'lines' in region:
                            region_count = len(region['lines'])
                    
                    # 如果获取失败（比如纯文本模式下 text_regions 为空），回退到数换行符
                    if region_count == 1 and text:
                        newline_count = text.count('\n')
                        if newline_count > 0:
                            region_count = newline_count + 1
                    
                    item["original_region_count"] = region_count
                
                input_data.append(item)
                text_index += 1

        prompt += json.dumps(input_data, ensure_ascii=False, indent=2)
        prompt += "\n\nCRITICAL: Provide translations in the exact same order as the input array. Follow the OUTPUT FORMAT specified in the System Prompt."

        return prompt

    def _build_user_prompt_for_hq(self, batch_data: List, ctx=None, prev_context: str = "", retry_attempt: int = 0, retry_reason: str = "") -> str:
        """Alias for backward compatibility (HQ mode)"""
        return self._build_unified_user_prompt(batch_data, ctx, prev_context, retry_attempt, retry_reason, is_image_mode=True)

    def _build_user_prompt_for_texts(self, texts: List[str], ctx=None, prev_context: str = "", retry_attempt: int = 0, retry_reason: str = "") -> str:
        """Alias for text mode: wraps texts into batch_data"""
        # 构造伪 batch_data
        batch_data = [{
            'original_texts': texts,
            'text_regions': getattr(ctx, 'text_regions', []) if ctx else []
        }]
        return self._build_unified_user_prompt(batch_data, ctx, prev_context, retry_attempt, retry_reason, is_image_mode=False)

    def _validate_br_markers(self, translations: List[str], queries: List[str] = None, ctx=None, batch_indices: List[int] = None, batch_data: List = None, split_level: int = 0) -> bool:
        """
        检查翻译结果是否包含必要的[BR]标记
        Check if translations contain necessary [BR] markers
        
        Args:
            translations: 翻译结果列表
            queries: 原始查询列表（可选）
            ctx: 上下文（用于获取配置和区域信息）
            batch_indices: 批次索引列表（可选，用于定位text_regions）
            batch_data: 批次数据列表（可选，HQ翻译器使用）
            split_level: 分割级别（可选，用于跳过深度分割时的检查）
            
        Returns:
            True if validation passes, False if BR markers are missing
        """
        import re
        
        # 如果分割级别过深（>=3），跳过BR检查以避免无限重试
        if split_level >= 3:
            self.logger.info(f"[AI断句检查] 分割级别过深 (split_level={split_level})，跳过BR标记检查")
            return True
        
        # 检查是否启用了BR检查
        check_enabled = False
        if ctx and hasattr(ctx, 'config') and hasattr(ctx.config, 'render'):
            check_enabled = getattr(ctx.config.render, 'check_br_and_retry', False)
        
        if not check_enabled:
            return True  # 检查未启用，直接通过
        
        # 检查是否启用了AI断句
        ai_break_enabled = False
        if ctx and hasattr(ctx, 'config') and hasattr(ctx.config, 'render'):
            ai_break_enabled = getattr(ctx.config.render, 'disable_auto_wrap', False)
        
        if not ai_break_enabled:
            return True  # AI断句未启用，不需要检查BR
        
        # 提取每个翻译对应的区域数
        region_counts = []
        if ctx and hasattr(ctx, 'text_regions') and ctx.text_regions:
            for idx in range(len(translations)):
                # 确定实际的region索引
                if batch_indices and idx < len(batch_indices):
                    region_idx = batch_indices[idx]
                else:
                    region_idx = idx
                
                if region_idx < len(ctx.text_regions):
                    region = ctx.text_regions[region_idx]
                    region_count = len(region.lines) if hasattr(region, 'lines') else 1
                    region_counts.append(region_count)
                else:
                    region_counts.append(1)  # 默认为1
        elif batch_data:
            # HQ翻译器使用batch_data
            for idx in range(len(translations)):
                region_idx = idx
                for data in batch_data:
                    if 'text_regions' in data and data['text_regions'] and region_idx < len(data['text_regions']):
                        region = data['text_regions'][region_idx]
                        region_count = len(region.lines) if hasattr(region, 'lines') else 1
                        region_counts.append(region_count)
                        break
                else:
                    region_counts.append(1)
        else:
            region_counts = [1] * len(translations)  # 默认都为1
        
        # 检查每个翻译，统计缺失BR的数量
        needs_check_count = 0
        missing_br_count = 0
        missing_indices = []
        
        for idx, (translation, region_count) in enumerate(zip(translations, region_counts)):
            # 只检查区域数≥2的翻译
            if region_count >= 2:
                needs_check_count += 1
                # 检查是否包含BR标记
                has_br = bool(re.search(r'(\[BR\]|【BR】|<br>)', translation, flags=re.IGNORECASE))
                if not has_br:
                    missing_br_count += 1
                    missing_indices.append(idx + 1)
                    self.logger.warning(
                        f"Translation {idx+1} missing [BR] markers (expected for {region_count} regions): {translation[:50]}..."
                    )
        
        # 计算容忍的错误数量：十分之一，最少1个
        if needs_check_count > 0:
            tolerance = max(1, needs_check_count // 10)
            
            if missing_br_count > tolerance:
                # 超过容忍度，验证失败
                self.logger.warning(
                    f"[AI断句检查] 缺失BR标记的翻译数 ({missing_br_count}/{needs_check_count}) 超过容忍度 ({tolerance})，需要重试"
                )
                return False
            elif missing_br_count > 0:
                # 在容忍度内，警告但通过
                self.logger.warning(
                    f"[AI断句检查] ⚠ {missing_br_count}/{needs_check_count} 条翻译缺失BR标记，但在容忍度内 ({tolerance})，继续执行"
                )
                return True
            else:
                # 全部通过
                self.logger.info(f"[AI断句检查] ✓ 所有多行区域的翻译都包含[BR]标记 (检查了 {needs_check_count}/{len(translations)} 条)")
                return True

        return True  # 没有需要检查的翻译，直接通过

    def _validate_translation_quality(self, queries: List[str], translations: List[str]) -> Tuple[bool, str]:
        """
        验证翻译质量，检测常见问题

        Args:
            queries: 原文列表
            translations: 译文列表

        Returns:
            (is_valid, error_message)
        """
        # 1. 检查数量匹配 (这是必须的，不能跳过)
        if len(translations) != len(queries):
            return False, f"Translation count mismatch: expected {len(queries)}, got {len(translations)}"

        import string

        # 2. 检查空翻译（原文不为空但译文为空）- 已禁用
        # empty_translation_errors = []
        # for i, (source, translation) in enumerate(zip(queries, translations)):
        #     if source.strip() and not translation.strip():
        #         empty_translation_errors.append(i + 1)
        # 
        # if empty_translation_errors:
        #     return False, f"Empty translation detected at positions: {empty_translation_errors}"

        # 3. 检查合并翻译（原文是正常文本但译文只有标点）
        for i, (source, translation) in enumerate(zip(queries, translations)):
            is_source_simple = all(char in string.punctuation or char.isspace() for char in source)
            is_translation_simple = all(char in string.punctuation or char.isspace() for char in translation)

            if is_translation_simple and not is_source_simple:
                return False, f"Detected potential merged translation at position {i+1}"

        # 4. 检查可疑符号（模型幻觉）- 已禁用
        # SUSPICIOUS_SYMBOLS = ["ହ", "ି", "ഹ"]
        # for symbol in SUSPICIOUS_SYMBOLS:
        #     for translation in translations:
        #         if symbol in translation:
        #             return False, f"Suspicious symbol '{symbol}' detected in translation"

        return True, ""

        return True, ""

    def _reset_global_attempt_count(self):
        """重置全局尝试计数器（每次新的翻译任务开始时调用）"""
        self._global_attempt_count = 0
        self._max_total_attempts = self.attempts

    def _increment_global_attempt(self) -> bool:
        """
        增加全局尝试计数，返回是否还可以继续尝试

        Returns:
            True: 还可以继续尝试
            False: 已达到总次数上限
        """
        self._global_attempt_count += 1

        # 无限重试模式
        if self._max_total_attempts == -1:
            return True

        # 检查是否超过上限
        if self._global_attempt_count >= self._max_total_attempts:
            self.logger.warning(f"Reached max total attempts: {self._global_attempt_count}/{self._max_total_attempts}")
            return False

        return True

    class SplitException(Exception):
        """用于触发分割的特殊异常"""
        def __init__(self, attempt_count, texts):
            self.attempt_count = attempt_count
            self.texts = texts
            super().__init__(f"Split triggered after {attempt_count} attempts")

    async def _translate_with_split(self, translator_func, texts: List[str], split_level: int = 0, **kwargs) -> List[str]:
        """
        带分割重试的翻译包装器（新逻辑）

        Args:
            translator_func: 实际的翻译函数（async callable）
            texts: 要翻译的文本列表
            split_level: 当前分割层级
            **kwargs: 传递给translator_func的其他参数

        Returns:
            翻译结果列表
        """
        # 检查是否超过全局尝试次数
        if self._max_total_attempts != -1 and self._global_attempt_count >= self._max_total_attempts:
            self.logger.error(f"Global attempt limit reached before translation: {self._global_attempt_count}/{self._max_total_attempts}")
            raise Exception(f"Translation failed: reached max total attempts ({self._max_total_attempts})")

        try:
            # 尝试翻译（内部会检查是否需要分割）
            translations = await translator_func(texts, split_level=split_level, **kwargs)
            return translations

        except self.SplitException as split_ex:
            # 触发分割
            if split_level < self._MAX_SPLIT_ATTEMPTS and len(texts) > 1:
                self.logger.warning(
                    f"Splitting after {split_ex.attempt_count} attempts at split_level={split_level}, "
                    f"batch size {len(texts)} → splitting into two halves"
                )

                # 分成两半（只分割texts，不分割batch_data等其他参数）
                mid = len(texts) // 2
                left_texts = texts[:mid]
                right_texts = texts[mid:]

                self.logger.info(f"Split: left={len(left_texts)}, right={len(right_texts)}, global_attempts={self._global_attempt_count}/{self._max_total_attempts}")

                # 并发翻译左右两部分（kwargs保持完整传递）
                try:
                    left_translations, right_translations = await asyncio.gather(
                        self._translate_with_split(translator_func, left_texts, split_level + 1, **kwargs),
                        self._translate_with_split(translator_func, right_texts, split_level + 1, **kwargs),
                        return_exceptions=False
                    )
                except Exception as split_error:
                    # 如果并发失败，回退到串行处理
                    self.logger.warning(f"Concurrent split failed, falling back to sequential: {split_error}")
                    left_translations = await self._translate_with_split(translator_func, left_texts, split_level + 1, **kwargs)
                    right_translations = await self._translate_with_split(translator_func, right_texts, split_level + 1, **kwargs)

                # 合并结果
                return left_translations + right_translations

            else:
                # 不能再分割了，终止翻译进程
                if len(texts) == 1:
                    self.logger.error(f"Single text translation failed at split_level={split_level}: {texts[0][:50]}...")
                    raise Exception(f"Translation failed for single text after {split_ex.attempt_count} attempts")
                else:
                    self.logger.error(f"Max split level ({self._MAX_SPLIT_ATTEMPTS}) reached, batch size={len(texts)}")
                    raise Exception(f"Translation failed: max split level reached with batch size {len(texts)}")

        except Exception as e:
            # 其他异常（非分割触发的），直接终止
            self.logger.error(f"Translation failed with exception at split_level={split_level}: {e}")
            raise e

    def parse_args(self, config):
        self.enable_post_translation_check = getattr(config, 'enable_post_translation_check', self.enable_post_translation_check)
        self.post_check_repetition_threshold = getattr(config, 'post_check_repetition_threshold', self.post_check_repetition_threshold)
        self.post_check_max_retry_attempts = getattr(config, 'post_check_max_retry_attempts', self.post_check_max_retry_attempts)
        self.attempts = getattr(config, 'attempts', self.attempts)

    def supports_languages(self, from_lang: str, to_lang: str, fatal: bool = False) -> bool:
        supported_src_languages = ['auto'] + list(self._LANGUAGE_CODE_MAP)
        supported_tgt_languages = list(self._LANGUAGE_CODE_MAP)

        if from_lang not in supported_src_languages:
            if fatal:
                raise LanguageUnsupportedException(from_lang, self.__class__.__name__, supported_src_languages)
            return False
        if to_lang not in supported_tgt_languages:
            if fatal:
                raise LanguageUnsupportedException(to_lang, self.__class__.__name__, supported_tgt_languages)
            return False
        return True

    def parse_language_codes(self, from_lang: str, to_lang: str, fatal: bool = False) -> Tuple[str, str]:
        if not self.supports_languages(from_lang, to_lang, fatal):
            return None, None
        if type(self._LANGUAGE_CODE_MAP) is list:
            return from_lang, to_lang

        _from_lang = self._LANGUAGE_CODE_MAP.get(from_lang) if from_lang != 'auto' else 'auto'
        _to_lang = self._LANGUAGE_CODE_MAP.get(to_lang)
        return _from_lang, _to_lang

    async def translate(self, from_lang: str, to_lang: str, queries: List[str], use_mtpe: bool = False, ctx=None) -> List[str]:
        """
        Translates list of queries of one language into another.
        """
        if to_lang not in VALID_LANGUAGES:
            raise ValueError('Invalid language code: "%s". Choose from the following: %s' % (to_lang, ', '.join(VALID_LANGUAGES)))
        if from_lang not in VALID_LANGUAGES and from_lang != 'auto':
            raise ValueError('Invalid language code: "%s". Choose from the following: auto, %s' % (from_lang, ', '.join(VALID_LANGUAGES)))
        self.logger.info(f'Translating into {VALID_LANGUAGES[to_lang]}')

        if from_lang == to_lang:
            # 即使源语言和目标语言相同，也应用文本清理（如全角句点替换）
            return [self._clean_translation_output(q, q, to_lang) for q in queries]

        # Dont translate queries without text
        query_indices = []
        final_translations = []
        for i, query in enumerate(queries):
            if not is_valuable_text(query):
                final_translations.append(queries[i])
            else:
                final_translations.append(None)
                query_indices.append(i)

        queries = [queries[i] for i in query_indices]

        translations = [''] * len(queries)
        untranslated_indices = list(range(len(queries)))
        for i in range(1 + self._INVALID_REPEAT_COUNT): # Repeat until all translations are considered valid
            if i > 0:
                self.logger.warn(f'Repeating because of invalid translation. Attempt: {i+1}')
                await asyncio.sleep(0.1)

            # Sleep if speed is over the ratelimit
            await self._ratelimit_sleep()

            # Translate
            _translations = await self._translate(*self.parse_language_codes(from_lang, to_lang, fatal=True), queries, ctx=ctx)

            # Strict validation: translation count must match query count
            if len(_translations) != len(queries):
                error_msg = f"Translation count mismatch: expected {len(queries)}, got {len(_translations)}"
                self.logger.error(error_msg)
                self.logger.error(f"Queries: {queries}")
                self.logger.error(f"Translations: {_translations}")
                raise InvalidServerResponse(error_msg)

            # Only overwrite yet untranslated indices
            for j in untranslated_indices:
                translations[j] = _translations[j]

            if self._INVALID_REPEAT_COUNT == 0:
                break

            new_untranslated_indices = []
            for j in untranslated_indices:
                q, t = queries[j], translations[j]
                # Repeat invalid translations with slightly modified queries
                if self._is_translation_invalid(q, t):
                    new_untranslated_indices.append(j)
                    queries[j] = self._modify_invalid_translation_query(q, t)
            untranslated_indices = new_untranslated_indices

            if not untranslated_indices:
                break

        translations = [self._clean_translation_output(q, r, to_lang) for q, r in zip(queries, translations)]

        if to_lang == 'ARA':
            import arabic_reshaper , bidi.algorithm
            translations = [bidi.algorithm.get_display(arabic_reshaper.reshape(t)) for t in translations]

        if use_mtpe:
            translations = await self.mtpe_adapter.dispatch(queries, translations)

        # Merge with the queries without text
        for i, trans in enumerate(translations):
            final_translations[query_indices[i]] = trans
            self.logger.info(f'{i}: {queries[i]} => {trans}')

        return final_translations

    @abstractmethod
    async def _translate(self, from_lang: str, to_lang: str, queries: List[str], ctx=None) -> List[str]:
        pass

    async def _ratelimit_sleep(self):
        if self._MAX_REQUESTS_PER_MINUTE > 0:
            now = time.time()
            ratelimit_timeout = self._last_request_ts + 60 / self._MAX_REQUESTS_PER_MINUTE
            if ratelimit_timeout > now:
                self.logger.info(f'Ratelimit sleep: {(ratelimit_timeout-now):.2f}s')
                await asyncio.sleep(ratelimit_timeout-now)
            self._last_request_ts = time.time()

    def _is_translation_invalid(self, query: str, trans: str) -> bool:
        if not trans and query:
            return True
        if not query or not trans:
            return False

        query_symbols_count = len(set(query))
        trans_symbols_count = len(set(trans))
        if query_symbols_count > 6 and trans_symbols_count < 6 and trans_symbols_count < 0.25 * len(trans):
            return True
        return False

    def _modify_invalid_translation_query(self, query: str, trans: str) -> str:
        """
        Can be overwritten if _INVALID_REPEAT_COUNT was set. It modifies the query
        for the next translation attempt.
        """
        return query

    def _clean_translation_output(self, query: str, trans: str, to_lang: str) -> str:
        """
        Tries to spot and skim down invalid translations.
        """
        if not query or not trans:
            return ''

        # 移除内部标记：【Original regions: X】或 [Original regions: X]
        # Remove internal markers: 【Original regions: X】 or [Original regions: X]
        trans = re.sub(r'【Original regions:\s*\d+】\s*', '', trans, flags=re.IGNORECASE)
        trans = re.sub(r'\[Original regions:\s*\d+\]\s*', '', trans, flags=re.IGNORECASE)
        
        # 替换全角句点连续出现（．．．或．．）为省略号
        trans = trans.replace('．．．', '…')
        trans = trans.replace('．．', '…')

        # '  ' -> ' '
        trans = re.sub(r'\s+', r' ', trans)
        # 'text.text' -> 'text. text'
        trans = re.sub(r'(?<![.,;!?])([.,;!?])(?=\w)', r'\1 ', trans)
        # ' ! ! . . ' -> ' !!.. '
        trans = re.sub(r'([.,;!?])\s+(?=[.,;!?]|$)', r'\1', trans)

        if to_lang != 'ARA':
            # 'text .' -> 'text.'
            trans = re.sub(r'(?<=[.,;!?\w])\s+([.,;!?])', r'\1', trans)
            # ' ... text' -> ' ...text'
            trans = re.sub(r'((?:\s|^)\.+)\s+(?=\w)', r'\1', trans)

        seq = repeating_sequence(trans.lower())

        # 'aaaaaaaaaaaaa' -> 'aaaaaa'
        if len(trans) < len(query) and len(seq) < 0.5 * len(trans):
            # Shrink sequence to length of original query
            trans = seq * max(len(query) // len(seq), 1)
            # Transfer capitalization of query to translation
            nTrans = ''
            for i in range(min(len(trans), len(query))):
                nTrans += trans[i].upper() if query[i].isupper() else trans[i]
            trans = nTrans

        # words = text.split()
        # elements = list(set(words))
        # if len(elements) / len(words) < 0.1:
        #     words = words[:int(len(words) / 1.75)]
        #     text = ' '.join(words)

        #     # For words that appear more then four times consecutively, remove the excess
        #     for el in elements:
        #         el = re.escape(el)
        #         text = re.sub(r'(?: ' + el + r'){4} (' + el + r' )+', ' ', text)

        return trans

class OfflineTranslator(CommonTranslator, ModelWrapper):
    _MODEL_SUB_DIR = 'translators'

    async def _translate(self, *args, **kwargs):
        return await self.infer(*args, **kwargs)

    @abstractmethod
    async def _infer(self, from_lang: str, to_lang: str, queries: List[str]) -> List[str]:
        pass

    async def load(self, from_lang: str, to_lang: str, device: str):
        return await super().load(device, *self.parse_language_codes(from_lang, to_lang))

    @abstractmethod
    async def _load(self, from_lang: str, to_lang: str, device: str):
        pass

    async def reload(self, from_lang: str, to_lang: str, device: str):
        return await super().reload(device, from_lang, to_lang)
    
    @abstractmethod
    async def _load(self, from_lang: str, to_lang: str, device: str):
        pass

    async def unload(self, device: str):
        return await super().unload()

def parse_hq_response(result_text: str) -> Tuple[List[str], List[Dict[str, str]]]:
    """
    专门解析HQ翻译器的响应，支持提取翻译和新术语
    Parse HQ translator response, supporting extraction of translations and new terms
    
    Returns:
        (translations, new_terms)
    """
    import json
    import logging
    import re
    
    logger = logging.getLogger('manga_translator')
    original_text = result_text # Keep for logging
    result_text = result_text.strip()
    if not result_text:
        return [], []

    # 1. 清理Markdown
    if "```" in result_text:
        code_block_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', result_text, re.DOTALL)
        if code_block_match:
            result_text = code_block_match.group(1).strip()
        else:
            lines = result_text.split('\n')
            if lines[0].strip().startswith("```"): lines = lines[1:]
            if lines and lines[-1].strip() == "```": lines = lines[:-1]
            result_text = "\n".join(lines).strip()

    # 2. 查找JSON起始 (清理前缀)
    first_bracket = result_text.find('[')
    first_brace = result_text.find('{')
    json_start = -1
    if first_bracket != -1 and first_brace != -1: json_start = min(first_bracket, first_brace)
    elif first_bracket != -1: json_start = first_bracket
    elif first_brace != -1: json_start = first_brace
    
    if json_start > 0:
        result_text = result_text[json_start:].strip()

    translations = []
    new_terms = []
    
    parsed_json = None
    
    # === 策略1: 标准 JSON 解析 ===
    try:
        parsed_json = json.loads(result_text)
    except json.JSONDecodeError:
        # === 策略2: 宽松 JSON5 解析 ===
        try:
            import json5
            parsed_json = json5.loads(result_text)
            logger.info("Using json5 for parsing")
        except (ImportError, Exception):
            parsed_json = None

    # 如果JSON解析成功，提取数据
    if parsed_json is not None:
        try:
            # 情况1: Object format {"translations": [...], "new_terms": [...]}
            if isinstance(parsed_json, dict):
                # 提取翻译
                trans_list = parsed_json.get("translations")
                if not trans_list and "t" in parsed_json: trans_list = parsed_json.get("t") # 兼容简写
                if not trans_list: trans_list = [] # 确保不为None

                if isinstance(trans_list, list):
                    if trans_list and isinstance(trans_list[0], dict):
                         # Sort by ID if possible
                        try: trans_list.sort(key=lambda x: int(x.get('id', 0)))
                        except: pass
                        for item in trans_list:
                            text = item.get('translation') or item.get('text') or list(item.values())[0]
                            translations.append(str(text) if text is not None else "")
                    else:
                        translations = [str(x) for x in trans_list]
                
                # 提取术语
                terms_list = parsed_json.get("new_terms") or parsed_json.get("glossary")
                if isinstance(terms_list, list):
                    new_terms = terms_list
            
            # 情况2: Array format [{"id":..., "translation":...}]
            elif isinstance(parsed_json, list):
                if parsed_json:
                    if isinstance(parsed_json[0], dict):
                        try: parsed_json.sort(key=lambda x: int(x.get('id', 0)))
                        except: pass
                        for item in parsed_json:
                            text = item.get('translation') or item.get('text') or list(item.values())[0]
                            translations.append(str(text) if text is not None else "")
                    else:
                        translations = [str(x) for x in parsed_json]
            
            return translations, new_terms

        except Exception as e:
             logger.warning(f"JSON structure parsing failed, falling back to regex: {e}")

    # === 策略3: 正则表达式暴力提取 ===
    logger.warning("JSON parsing failed, falling back to Regex extraction")
    
    # 3.1 尝试提取带ID的对象: {"id": 1, "translation": "..."}
    object_pattern = r'\{\s*"id"\s*:\s*(\d+)\s*,\s*"translation"\s*:\s*"([^"]*(?:\\.[^"]*)*)"\s*\}'
    matches = re.findall(object_pattern, result_text)
    
    if matches:
        logger.info(f"Regex extracted {len(matches)} translations with IDs")
        sorted_matches = sorted(matches, key=lambda x: int(x[0]))
        translations = [match[1].replace('\\"', '"').replace('\\n', '\n') for match in sorted_matches]
        
        # 尝试提取术语 (简单正则)
        # 假设 new_terms 在后面，格式类似 {"original": "...", ...}
        # 这里的正则很难完美匹配嵌套结构，只能尽力而为
        term_pattern = r'\{\s*"original"\s*:\s*"([^"]+)"\s*,\s*"translation"\s*:\s*"([^"]+)"\s*,\s*"category"\s*:\s*"([^"]+)"\s*\}'
        term_matches = re.findall(term_pattern, result_text)
        for tm in term_matches:
            new_terms.append({"original": tm[0], "translation": tm[1], "category": tm[2]})
            
        return translations, new_terms

    # 3.2 尝试只提取 translation 字段
    translation_pattern = r'"translation"\s*:\s*"([^"]*(?:\\.[^"]*)*)"'
    matches = re.findall(translation_pattern, result_text)
    if matches:
         logger.warning(f"Regex extracted {len(matches)} translations (no IDs)")
         translations = [match.replace('\\"', '"').replace('\\n', '\n') for match in matches]
         return translations, []

    # 3.3 最后的兜底：按行分割 (仅当不像JSON时)
    if not result_text.startswith('{') and not result_text.startswith('['):
         for line in result_text.split('\n'):
            line = line.strip()
            if line:
                line = re.sub(r'^\d+\.\s*', '', line)
                line = line.replace('\\n', '\n').replace('↵', '\n')
                translations.append(line)

    return translations, new_terms

def parse_json_or_text_response(result_text: str) -> List[str]:
    """
    解析LLM返回的文本，支持JSON列表格式或按行分割格式
    Wrapper around parse_hq_response for backward compatibility
    """
    translations, _ = parse_hq_response(result_text)
    return translations


def get_custom_prompt_content(file_path: str) -> str:
    """
    读取自定义提示词文件内容
    Read custom prompt file content
    """
    import os
    try:
        if not os.path.exists(file_path):
            return ""
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        print(f"Error reading prompt file {file_path}: {e}")
        return ""

def save_custom_prompt_content(file_path: str, content: str) -> bool:
    """
    保存自定义提示词文件内容
    Save custom prompt file content
    """
    import os
    try:
        # 确保存储目录存在
        os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"Error saving prompt file {file_path}: {e}")
        return False

def merge_glossary_to_file(file_path: str, new_terms: List[Dict[str, str]]) -> bool:
    """
    将新提取的术语合并到提示词文件中
    Merge newly extracted terms into the prompt file
    
    Args:
        file_path: 提示词文件路径
        new_terms: 新术语列表 [{"original": "...", "translation": "...", "category": "..."}]
    """
    import json
    import os
    
    if not new_terms:
        return False

    try:
        # 读取现有文件
        data = {}
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    pass # 如果文件损坏或为空，从头开始
        
        # 确保结构完整
        if "glossary" not in data or not isinstance(data["glossary"], dict):
            # 如果旧格式是列表，或者没有 glossary，初始化为新的分类结构
            data["glossary"] = {
                "Person": [], "Location": [], "Org": [], "Item": [], "Skill": [], "Creature": []
            }
        
        glossary = data["glossary"]
        # 确保所有标准分类键都存在
        valid_keys_map = {
            "person": "Person", 
            "location": "Location", 
            "org": "Org", 
            "organization": "Org",
            "item": "Item", 
            "skill": "Skill", 
            "creature": "Creature"
        }
        
        # 确保标准键存在于 glossary 中
        for key in set(valid_keys_map.values()):
            if key not in glossary:
                glossary[key] = []

        modified = False
        
        for term in new_terms:
            raw_category = term.get("category", "Item")
            original = term.get("original")
            translation = term.get("translation")
            
            if not original or not translation:
                continue

            # 映射 Category 到标准 Key
            target_key = "Item" # Default fallback
            if raw_category:
                normalized_cat = raw_category.lower()
                if normalized_cat in valid_keys_map:
                    target_key = valid_keys_map[normalized_cat]
                else:
                    # 尝试模糊匹配或直接使用 Title Case
                    for k in valid_keys_map.values():
                        if k.lower() == normalized_cat:
                            target_key = k
                            break
            
            # 检查是否已存在 (根据 original 去重)
            exists = False
            if target_key in glossary:
                for existing_term in glossary[target_key]:
                    if existing_term.get("original") == original:
                        exists = True
                        break
            else:
                glossary[target_key] = []
            
            if not exists:
                glossary[target_key].append({
                    "original": original,
                    "translation": translation
                })
                modified = True
                print(f"[Glossary] Added new term: {original} -> {translation} ({target_key})")
        
        if modified:
            # 确保存储目录存在
            os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
            
    except Exception as e:
        print(f"Error merging glossary: {e}")
        return False
    
    return False

def get_glossary_extraction_prompt(target_lang: str) -> str:
    """
    获取术语提取的追加提示词
    Get the additional prompt for glossary extraction
    """
    from ..utils import BASE_PATH
    import os
    import json
    
    try:
        prompt_path = os.path.join(BASE_PATH, 'dict', 'glossary_extraction_prompt.json')
        if not os.path.exists(prompt_path):
            return ""
            
        with open(prompt_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        prompt = data.get('glossary_extraction_prompt', '')
        if prompt:
            # Replace placeholder with target language
            # We assume the caller passes the full language name if possible, or we map it here if needed
            # For simplicity, we just use what's passed
            prompt = prompt.replace("{{{target_lang}}}", target_lang)
            return prompt
    except Exception as e:
        print(f"Error loading glossary extraction prompt: {e}")
        return ""
