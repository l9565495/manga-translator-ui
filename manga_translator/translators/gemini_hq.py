import os
import re
import asyncio
import base64
import json
from io import BytesIO
from typing import List, Dict, Any
from PIL import Image
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from .common import CommonTranslator, VALID_LANGUAGES
from .keys import GEMINI_API_KEY
from ..utils import Context


def encode_image_for_gemini(image, max_size=1024):
    """将图片处理为适合Gemini API的格式"""
    # 转换图片格式
    if image.mode == "P":
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    elif image.mode == "RGBA":
        # Gemini更喜欢RGB格式
        background = Image.new('RGB', image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    
    # 调整图片大小
    w, h = image.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        image = image.resize((new_w, new_h), Image.LANCZOS)
    
    return image


def _flatten_prompt_data(data: Any, indent: int = 0) -> str:
    """Recursively flattens a dictionary or list into a formatted string."""
    prompt_parts = []
    prefix = "  " * indent

    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                prompt_parts.append(f"{prefix}- {key}:")
                prompt_parts.append(_flatten_prompt_data(value, indent + 1))
            else:
                prompt_parts.append(f"{prefix}- {key}: {value}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                prompt_parts.append(_flatten_prompt_data(item, indent + 1))
            else:
                prompt_parts.append(f"{prefix}- {item}")
    
    return "\n".join(prompt_parts)

class GeminiHighQualityTranslator(CommonTranslator):
    """
    Gemini高质量翻译器
    支持多图片批量处理，提供文本框顺序、原文和原图给AI进行更精准的翻译
    """
    _LANGUAGE_CODE_MAP = VALID_LANGUAGES
    
    def __init__(self):
        super().__init__()
        self.client = None
        # Initial setup from environment variables
        self.api_key = os.getenv('GEMINI_API_KEY', GEMINI_API_KEY)
        self.base_url = os.getenv('GEMINI_API_BASE', 'https://generativelanguage.googleapis.com')
        self.model_name = os.getenv('GEMINI_MODEL', "gemini-1.5-flash")
        self.max_tokens = 4000
        self.temperature = 0.1
        self.safety_settings = [
            {
                "category": HarmCategory.HARM_CATEGORY_HARASSMENT,
                "threshold": HarmBlockThreshold.BLOCK_NONE,
            },
            {
                "category": HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                "threshold": HarmBlockThreshold.BLOCK_NONE,
            },
            {
                "category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                "threshold": HarmBlockThreshold.BLOCK_NONE,
            },
            {
                "category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                "threshold": HarmBlockThreshold.BLOCK_NONE,
            },
        ]
        self._setup_client()
        
    def _setup_client(self):
        """设置Gemini客户端"""
        if not self.client and self.api_key:
            client_options = {"api_endpoint": self.base_url} if self.base_url else None

            genai.configure(
                api_key=self.api_key,
                transport='rest',  # 支持自定义base_url
                client_options=client_options
            )
            
            # Apply different configs for different API types
            is_third_party_api = self.base_url and self.base_url != 'https://generativelanguage.googleapis.com'

            if not is_third_party_api:
                # Official Google API - full config
                generation_config = {
                    "temperature": self.temperature,
                    "top_p": 0.95,
                    "top_k": 64,
                    "max_output_tokens": self.max_tokens,
                    "response_mime_type": "text/plain",
                }
                model_args = {
                    "model_name": self.model_name,
                    "generation_config": generation_config,
                    "safety_settings": self.safety_settings
                }
                self.logger.info("使用官方Google API，应用完整配置。")
            else:
                # Third-party API - minimal config to avoid format issues
                generation_config = {
                    "temperature": self.temperature,
                    "max_output_tokens": self.max_tokens,
                }
                model_args = {
                    "model_name": self.model_name,
                    "generation_config": generation_config,
                }
                self.logger.info("检测到第三方API，使用简化配置避免格式冲突。")

            self.client = genai.GenerativeModel(**model_args)
    

    
    def _build_system_prompt(self, source_lang: str, target_lang: str, custom_prompt_json: Dict[str, Any] = None, line_break_prompt_json: Dict[str, Any] = None) -> str:
        """构建系统提示词"""
        # Map language codes to full names for clarity in the prompt
        lang_map = {
            "CHS": "Simplified Chinese",
            "CHT": "Traditional Chinese",
            "JPN": "Japanese",
            "ENG": "English",
            "KOR": "Korean",
            "VIN": "Vietnamese",
            "FRA": "French",
            "DEU": "German",
            "ITA": "Italian",
        }
        target_lang_full = lang_map.get(target_lang, target_lang) # Fallback to the code itself

        custom_prompt_str = ""
        if custom_prompt_json:
            custom_prompt_str = _flatten_prompt_data(custom_prompt_json)
            # self.logger.info(f"--- Custom Prompt Content ---\n{custom_prompt_str}\n---------------------------")

        line_break_prompt_str = ""
        if line_break_prompt_json and line_break_prompt_json.get('line_break_prompt'):
            line_break_prompt_str = line_break_prompt_json['line_break_prompt']

        try:
            from ..utils import BASE_PATH
            import os
            import json
            prompt_path = os.path.join(BASE_PATH, 'dict', 'system_prompt_hq.json')
            with open(prompt_path, 'r', encoding='utf-8') as f:
                base_prompt_data = json.load(f)
            base_prompt = base_prompt_data['system_prompt']
        except Exception as e:
            self.logger.warning(f"Failed to load system prompt from file, falling back to hardcoded prompt. Error: {e}")
            base_prompt = f"""You are an expert manga translator. Your task is to accurately translate manga text from the source language into **{{{target_lang}}}**. You will be given the full manga page for context.\n\n**CRITICAL INSTRUCTIONS (FOLLOW STRICTLY):**\n\n1.  **DIRECT TRANSLATION ONLY**: Your output MUST contain ONLY the raw, translated text. Nothing else.\n    -   DO NOT include the original text.\n    -   DO NOT include any explanations, greetings, apologies, or any conversational text.\n    -   DO NOT use Markdown formatting (like ```json or ```).\n    -   The output is fed directly to an automated script. Any extra text will cause it to fail.\n\n2.  **MATCH LINE COUNT**: The number of lines in your output MUST EXACTLY match the number of text regions you are asked to translate. Each line in your output corresponds to one numbered text region in the input.\n\n3.  **TRANSLATE EVERYTHING**: Translate all text provided, including sound effects and single characters. Do not leave any line untranslated.\n\n4.  **ACCURACY AND TONE**:\n    -   Preserve the original tone, emotion, and character's voice.\n    -   Ensure consistent translation of names, places, and special terms.\n    -   For onomatopoeia (sound effects), provide the equivalent sound in {{{target_lang}}} or a brief description (e.g., '(rumble)', '(thud)').\n\n---\n\n**EXAMPLE OF CORRECT AND INCORRECT OUTPUT:**\n\n**[ CORRECT OUTPUT EXAMPLE ]**\nThis is a correct response. Notice it only contains the translated text, with each translation on a new line.\n\n(Imagine the user input was: "1. うるさい！", "2. 黙れ！")\n```\n吵死了！\n闭嘴！\n```\n\n**[ ❌ INCORRECT OUTPUT EXAMPLE ]**\nThis is an incorrect response because it includes extra text and explanations.\n\n(Imagine the user input was: "1. うるさい！", "2. 黙れ！")\n```\n好的，这是您的翻译：\n1. 吵死了！\n2. 闭嘴！\n```\n**REASONING:** The above example is WRONG because it includes "好的，这是您的翻译：" and numbering. Your response must be ONLY the translated text, line by line.\n\n---\n\n**FINAL INSTRUCTION:** Now, perform the translation task. Remember, your response must be clean, containing only the translated text.\n"""

        # Replace placeholder with the full language name
        base_prompt = base_prompt.replace("{{{target_lang}}}", target_lang_full)

        # Combine prompts
        final_prompt = ""
        if line_break_prompt_str:
            final_prompt += f"{line_break_prompt_str}\n\n---\n\n"
        if custom_prompt_str:
            final_prompt += f"{custom_prompt_str}\n\n---\n\n"
        
        final_prompt += base_prompt
        return final_prompt

    def _build_user_prompt(self, batch_data: List[Dict], ctx: Any) -> str:
        """构建用户提示词"""
        prompt = "Please translate the following manga text regions. I'm providing multiple images with their text regions in reading order:\n\n"
        
        # 添加图片信息
        for i, data in enumerate(batch_data):
            prompt += f"=== Image {i+1} ===\n"
            prompt += f"Text regions ({len(data['original_texts'])} regions):\n"
            for j, text in enumerate(data['original_texts']):
                prompt += f"  {j+1}. {text}\n"
            prompt += "\n"
        
        prompt += "All texts to translate (in order):\n"
        text_index = 1
        for img_idx, data in enumerate(batch_data):
            for region_idx, text in enumerate(data['original_texts']):
                text_to_translate = text.replace('\n', ' ').replace('\ufffd', '')
                # 获取对应的text_region来获取区域数
                if data['text_regions'] and region_idx < len(data['text_regions']):
                    region = data['text_regions'][region_idx]
                    region_count = len(region.lines) if hasattr(region, 'lines') else 1
                else:
                    region_count = 1
                prompt += f"{text_index}. [Original regions: {region_count}] {text_to_translate}\n"
                text_index += 1
        
        prompt += "\nCRITICAL: Provide translations in the exact same order as the numbered input text regions. Your first line of output must be the translation for text region #1, your second line for #2, and so on. DO NOT CHANGE THE ORDER."
        
        return prompt

    async def _translate_batch_high_quality(self, texts: List[str], batch_data: List[Dict], source_lang: str, target_lang: str, custom_prompt_json: Dict[str, Any] = None, line_break_prompt_json: Dict[str, Any] = None, ctx: Any = None) -> List[str]:
        """高质量批量翻译方法"""
        if not texts:
            return []
        
        if not self.client:
            self._setup_client()
        
        if not self.client:
            self.logger.error("Gemini客户端初始化失败")
            return texts
        
        # 准备图片和内容
        content_parts = []
        
        # 打印输入的原文
        self.logger.info("--- Original Texts for Translation ---")
        for i, text in enumerate(texts):
            self.logger.info(f"{i+1}: {text}")
        self.logger.info("------------------------------------")

        # 打印图片信息
        self.logger.info("--- Image Info ---")
        for i, data in enumerate(batch_data):
            image = data['image']
            self.logger.info(f"Image {i+1}: size={image.size}, mode={image.mode}")
        self.logger.info("--------------------")

        # 添加系统提示词和用户提示词
        system_prompt = self._build_system_prompt(source_lang, target_lang, custom_prompt_json=custom_prompt_json, line_break_prompt_json=line_break_prompt_json)
        user_prompt = self._build_user_prompt(batch_data, ctx)
        
        content_parts.append(system_prompt + "\n\n" + user_prompt)
        
        # 添加图片
        for data in batch_data:
            image = data['image']
            processed_image = encode_image_for_gemini(image)
            content_parts.append(processed_image)
        
        # 发送请求
        max_retries = self.attempts
        attempt = 0
        is_infinite = max_retries == -1

        # Dynamically construct arguments for generate_content
        request_args = {
            "contents": content_parts
        }
        is_third_party_api = self.base_url and self.base_url != 'https://generativelanguage.googleapis.com'
        if is_third_party_api:
            self.logger.warning("Omitting safety settings for third-party API request.")
        else:
            request_args["safety_settings"] = self.safety_settings

        def generate_content_with_logging(**kwargs):
            # Create a serializable copy of the arguments for logging
            log_kwargs = kwargs.copy()
            if 'contents' in log_kwargs and isinstance(log_kwargs['contents'], list):
                serializable_contents = []
                for item in log_kwargs['contents']:
                    if isinstance(item, Image.Image):
                        serializable_contents.append(f"<PIL.Image.Image size={item.size} mode={item.mode}>")
                    else:
                        serializable_contents.append(item)
                log_kwargs['contents'] = serializable_contents

            self.logger.info(f"--- Gemini Request Body ---\n{json.dumps(log_kwargs, indent=2, ensure_ascii=False)}\n---------------------------")
            return self.client.generate_content(**kwargs)

        while is_infinite or attempt < max_retries:
            try:
                response = await asyncio.to_thread(
                    generate_content_with_logging,
                    **request_args
                )

                # 检查finish_reason，只有成功(1)才继续，其他都重试
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'finish_reason'):
                        finish_reason = candidate.finish_reason

                        if finish_reason != 1:  # 不是STOP(成功)
                            attempt += 1
                            log_attempt = f"{attempt}/{max_retries}" if not is_infinite else f"Attempt {attempt}"

                            # 显示具体的finish_reason信息
                            finish_reason_map = {
                                1: "STOP(成功)",
                                2: "SAFETY(安全策略拦截)",
                                3: "MAX_TOKENS(达到最大token限制)",
                                4: "RECITATION(内容重复检测)",
                                5: "OTHER(其他未知错误)"
                            }
                            reason_desc = finish_reason_map.get(finish_reason, f"未知错误码({finish_reason})")

                            self.logger.warning(f"Gemini API失败 ({log_attempt}): finish_reason={finish_reason} - {reason_desc}")

                            if not is_infinite and attempt >= max_retries:
                                self.logger.error(f"Gemini翻译在多次重试后仍失败: {reason_desc}")
                                break
                            await asyncio.sleep(1)
                            continue

                # 尝试访问 .text 属性，如果API因安全原因等返回空内容，这里会触发异常
                result_text = response.text.strip()

                # 调试日志：打印Gemini的原始返回内容
                self.logger.info(f"--- Gemini Raw Response ---\n{result_text}\n---------------------------")

                # 增加清理步骤，移除可能的Markdown代码块
                if result_text.startswith("```") and result_text.endswith("```"):
                    result_text = result_text[3:-3].strip()
                
                # 如果成功获取文本，则处理并返回
                translations = []
                for line in result_text.split('\n'):
                    line = line.strip()
                    if line:
                        # 移除编号（如"1. "）
                        line = re.sub(r'^\d+\.\s*', '', line)
                        # Replace other possible newline representations, but keep [BR]
                        line = line.replace('\\n', '\n').replace('↵', '\n')
                        translations.append(line)
                
                # 确保翻译数量匹配 - 用空字符串填充而不是原文
                while len(translations) < len(texts):
                    translations.append("")
                
                # 打印原文和译文的对应关系
                self.logger.info("--- Translation Results ---")
                for original, translated in zip(texts, translations):
                    self.logger.info(f'{original} -> {translated}')
                self.logger.info("---------------------------")

                return translations[:len(texts)]

            except Exception as e:
                attempt += 1
                log_attempt = f"{attempt}/{max_retries}" if not is_infinite else f"Attempt {attempt}"
                self.logger.warning(f"Gemini高质量翻译出错 ({log_attempt}): {e}")

                if "finish_reason: 2" in str(e) or "finish_reason is 2" in str(e):
                    self.logger.warning("检测到Gemini安全设置拦截。正在重试...")
                
                if not is_infinite and attempt >= max_retries:
                    self.logger.error("Gemini翻译在多次重试后仍然失败。即将终止程序。")
                    raise e
                
                await asyncio.sleep(1) # Wait before retrying
        
        return texts # Fallback in case loop finishes unexpectedly

    async def _translate(self, from_lang: str, to_lang: str, queries: List[str], ctx=None) -> List[str]:
        """主翻译方法"""
        if not self.client:
            from .. import manga_translator
            if hasattr(manga_translator, 'config') and hasattr(manga_translator.config, 'translator'):
                self.parse_args(manga_translator.config.translator)
        
        if not queries:
            return []
        
        # 检查是否为高质量批量翻译模式
        if ctx and hasattr(ctx, 'high_quality_batch_data'):
            batch_data = ctx.high_quality_batch_data
            if batch_data and len(batch_data) > 0:
                self.logger.info(f"高质量翻译模式：正在打包 {len(batch_data)} 张图片并发送...")
                custom_prompt_json = getattr(ctx, 'custom_prompt_json', None)
                line_break_prompt_json = getattr(ctx, 'line_break_prompt_json', None)
                return await self._translate_batch_high_quality(queries, batch_data, from_lang, to_lang, custom_prompt_json=custom_prompt_json, line_break_prompt_json=line_break_prompt_json, ctx=ctx)
        
        # 普通单文本翻译（后备方案）
        if not self.client:
            self._setup_client()
        
        if not self.client:
            self.logger.error("Gemini客户端初始化失败，请检查 GEMINI_API_KEY 是否已在UI或.env文件中正确设置。")
            return queries
        
        try:
            simple_prompt = f"Translate the following {from_lang} text to {to_lang}. Provide only the translation:\n\n" + "\n".join(queries)
            
            # Dynamically construct arguments to handle safety settings for the fallback path
            request_args = {
                "contents": simple_prompt
            }
            is_third_party_api = self.base_url and self.base_url != 'https://generativelanguage.googleapis.com'
            if is_third_party_api:
                # For third-party APIs, omit the safety_settings parameter entirely
                pass
            else:
                request_args["safety_settings"] = self.safety_settings

            def generate_content_with_logging(**kwargs):
                log_kwargs = kwargs.copy()
                if 'contents' in log_kwargs and isinstance(log_kwargs['contents'], list):
                    serializable_contents = []
                    for item in log_kwargs['contents']:
                        if isinstance(item, Image.Image):
                            serializable_contents.append(f"<PIL.Image.Image size={item.size} mode={item.mode}>")
                        else:
                            serializable_contents.append(item)
                    log_kwargs['contents'] = serializable_contents
                self.logger.info(f"--- Gemini Fallback Request Body ---\n{json.dumps(log_kwargs, indent=2, ensure_ascii=False)}\n------------------------------------")
                return self.client.generate_content(**kwargs)

            response = await asyncio.to_thread(
                generate_content_with_logging,
                **request_args
            )
            
            if response and response.text:
                result = response.text.strip()
                translations = result.split('\n')
                translations = [t.strip() for t in translations if t.strip()]
                
                # 确保数量匹配
                while len(translations) < len(queries):
                    translations.append(queries[len(translations)] if len(translations) < len(queries) else "")
                
                return translations[:len(queries)]
                
        except Exception as e:
            self.logger.error(f"Gemini翻译出错: {e}")
        
        return queries
