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
            genai.configure(
                api_key=self.api_key,
                transport='rest'  # 支持自定义base_url
            )
            
            # 如果有自定义base_url，需要特殊处理
            if self.base_url and self.base_url != "https://generativelanguage.googleapis.com":
                # 注意：Gemini的base_url配置可能需要特殊处理
                # 这里提供基本框架，具体实现可能需要根据实际API调整
                os.environ['GOOGLE_AI_API_BASE'] = self.base_url
            
            generation_config = {
                "temperature": self.temperature,
                "top_p": 0.95,
                "top_k": 64,
                "max_output_tokens": self.max_tokens,
                "response_mime_type": "text/plain",
            }
            
            self.client = genai.GenerativeModel(
                model_name=self.model_name,
                generation_config=generation_config,
                safety_settings=self.safety_settings,
            )
    
    def parse_args(self, config):
        """解析配置参数，使用和原有Gemini翻译器相同的环境变量"""
        # 从UI配置覆盖环境变量
        ui_api_key = getattr(config, 'GEMINI_API_KEY', None) or getattr(config, 'api_key', None)
        if ui_api_key:
            self.api_key = ui_api_key

        ui_base_url = getattr(config, 'api_base', None)
        if ui_base_url:
            self.base_url = ui_base_url
        
        self.model_name = getattr(config, 'model', self.model_name)
        
        # 设置翻译参数
        self.max_tokens = getattr(config, 'max_tokens', self.max_tokens)
        self.temperature = getattr(config, 'temperature', self.temperature)
        
        # 使用新配置重新设置客户端
        self.client = None  # 强制重新初始化
        self._setup_client()
        
        # 调用父类解析
        super().parse_args(config)
    
    def _build_system_prompt(self, source_lang: str, target_lang: str) -> str:
        """构建系统提示词"""
        return f"""You are an expert manga translator. Your primary goal is to provide a high-quality, natural-sounding translation that is faithful to the original's intent, emotion, and context.

**CONTEXT:**
You will be given a batch of manga pages. The user prompt will first list the original text grouped by page (e.g., under `=== Image 1 ===`, `=== Image 2 ===`). Then, it will provide a flat, numbered list of all texts that need translating. You will also receive the corresponding image files. Analyze all of this information together to ensure consistency in tone, style, and character voice.

**CRITICAL RULES (Do not break these):**
1.  You MUST translate every text region provided, even single characters or sound effects.
2.  Your output MUST have the exact same number of lines as the input text regions. Each line of your output corresponds to one text region. Do not merge or split regions.
3.  Your output MUST contain ONLY the translated text, with each translation on a new line. Do not add any extra explanations, apologies, or formatting.
4.  You MUST return text in {{{target_lang}}}. NEVER return the original text.

**TRANSLATION GUIDELINES:**
- **Natural Language:** The translation must be natural and conform to {{{target_lang}}} linguistic habits. Don't make it sound like a literal machine translation.
- **Character & Scene:** The translation must fit the character's personality, the scene's mood, and the overall context.
- **Terminology:** Ensure consistent translation of names, places, and special terms.
- **Cultural Nuances:** If you encounter humor, puns, or cultural references, find an appropriate equivalent in {{{target_lang}}}.
- **Sound Effects:** For onomatopoeia, provide the equivalent sound in {{{target_lang}}} or a brief description of the sound (e.g., '(rumble)', '(thud)')."""

    def _build_user_prompt(self, batch_data: List[Dict], texts: List[str]) -> str:
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
        for i, text in enumerate(texts):
            prompt += f"{i+1}. {text}\n"
        
        prompt += "\nPlease provide translations in the same order:"
        
        return prompt

    async def _translate_batch_high_quality(self, texts: List[str], batch_data: List[Dict], source_lang: str, target_lang: str) -> List[str]:
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
        system_prompt = self._build_system_prompt(source_lang, target_lang)
        user_prompt = self._build_user_prompt(batch_data, texts)
        
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

        while is_infinite or attempt < max_retries:
            try:
                response = await asyncio.to_thread(
                    self.client.generate_content,
                    content_parts
                )
                
                # 尝试访问 .text 属性，如果API因安全原因等返回空内容，这里会触发异常
                result_text = response.text.strip()
                
                # 如果成功获取文本，则处理并返回
                translations = []
                for line in result_text.split('\n'):
                    line = line.strip()
                    if line:
                        # 移除编号（如"1. "）
                        line = re.sub(r'^\d+\.\s*', '', line)
                        translations.append(line)
                
                # 确保翻译数量匹配
                while len(translations) < len(texts):
                    translations.append(texts[len(translations)] if len(translations) < len(texts) else "")
                
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
                return await self._translate_batch_high_quality(queries, batch_data, from_lang, to_lang)
        
        # 普通单文本翻译（后备方案）
        if not self.client:
            self._setup_client()
        
        if not self.client:
            self.logger.error("Gemini客户端初始化失败，请检查 GEMINI_API_KEY 是否已在UI或.env文件中正确设置。")
            return queries
        
        try:
            simple_prompt = f"Translate the following {from_lang} text to {to_lang}. Provide only the translation:\n\n" + "\n".join(queries)
            
            response = await asyncio.to_thread(
                self.client.generate_content,
                simple_prompt
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
