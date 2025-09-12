import os
import re
import asyncio
import base64
import json
from io import BytesIO
from typing import List, Dict, Any
from PIL import Image
import openai
from openai import AsyncOpenAI

from .common import CommonTranslator, VALID_LANGUAGES
from .keys import OPENAI_API_KEY, OPENAI_MODEL
from ..utils import Context


def encode_image_for_openai(image, max_size=1024):
    """将图片编码为base64格式，适合OpenAI API"""
    # 转换图片格式
    if image.mode == "P":
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    elif image.mode == "RGBA":
        # 创建一个白色背景
        background = Image.new('RGB', image.size, (255, 255, 255))
        # 将带有透明通道的图片粘贴到白色背景上
        background.paste(image, mask=image.split()[-1])
        image = background
    
    # 调整图片大小
    w, h = image.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        image = image.resize((new_w, new_h), Image.LANCZOS)
    
    # 编码为base64
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode('utf-8')


class OpenAIHighQualityTranslator(CommonTranslator):
    """
    OpenAI高质量翻译器
    支持多图片批量处理，提供文本框顺序、原文和原图给AI进行更精准的翻译
    """
    _LANGUAGE_CODE_MAP = VALID_LANGUAGES
    
    def __init__(self):
        super().__init__()
        self.client = None
        self.api_key = os.getenv('OPENAI_API_KEY', OPENAI_API_KEY)
        self.base_url = os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1')
        self.model = os.getenv('OPENAI_MODEL', "gpt-4o")
        self.max_tokens = 4000
        self.temperature = 0.1
        self._setup_client()
        
    def _setup_client(self):
        """设置OpenAI客户端"""
        if not self.client:
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url
            )
    
    def parse_args(self, config):
        """解析配置参数，使用和原有OpenAI翻译器相同的环境变量"""
        # 从UI配置覆盖环境变量
        ui_api_key = getattr(config, 'OPENAI_API_KEY', None) or getattr(config, 'api_key', None)
        if ui_api_key:
            self.api_key = ui_api_key

        ui_base_url = getattr(config, 'api_base', None)
        if ui_base_url:
            self.base_url = ui_base_url
        
        self.model = getattr(config, 'model', self.model)
        
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
        
        # 准备图片
        self.logger.info(f"高质量翻译模式：正在打包 {len(batch_data)} 张图片并发送...")
        
        # 打印图片信息
        self.logger.info("--- Image Info ---")
        for i, data in enumerate(batch_data):
            image = data['image']
            self.logger.info(f"Image {i+1}: size={image.size}, mode={image.mode}")
        self.logger.info("--------------------")

        image_contents = []
        for data in batch_data:
            image = data['image']
            base64_img = encode_image_for_openai(image)
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_img}"}
            })
        
        # 构建消息
        system_prompt = self._build_system_prompt(source_lang, target_lang)
        user_prompt = self._build_user_prompt(batch_data, texts)
        
        user_content = [{"type": "text", "text": user_prompt}]
        user_content.extend(image_contents)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ]
        
        # 发送请求
        max_retries = self.attempts
        attempt = 0
        is_infinite = max_retries == -1
        last_exception = None

        while is_infinite or attempt < max_retries:
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature
                )

                # 检查成功条件
                if response.choices and response.choices[0].message.content and response.choices[0].finish_reason != 'content_filter':
                    result_text = response.choices[0].message.content.strip()
                    
                    # 解析翻译结果
                    translations = []
                    for line in result_text.split('\n'):
                        line = line.strip()
                        if line:
                            line = re.sub(r'^\d+\.\s*', '', line)
                            translations.append(line)
                    
                    while len(translations) < len(texts):
                        translations.append(texts[len(translations)] if len(translations) < len(texts) else "")
                    
                    self.logger.info("--- Translation Results ---")
                    for original, translated in zip(texts, translations):
                        self.logger.info(f'{original} -> {translated}')
                    self.logger.info("---------------------------")

                    return translations[:len(texts)]
                
                # 如果不成功，则记录原因并准备重试
                attempt += 1
                log_attempt = f"{attempt}/{max_retries}" if not is_infinite else f"Attempt {attempt}"
                finish_reason = response.choices[0].finish_reason if response.choices else "N/A"

                if finish_reason == 'content_filter':
                    self.logger.warning(f"OpenAI内容被安全策略拦截 ({log_attempt})。正在重试...")
                    last_exception = Exception("OpenAI content filter triggered")
                else:
                    self.logger.warning(f"OpenAI返回空内容或意外的结束原因 '{finish_reason}' ({log_attempt})。正在重试...")
                    last_exception = Exception(f"OpenAI returned empty content or unexpected finish_reason: {finish_reason}")

                if not is_infinite and attempt >= max_retries:
                    self.logger.error("OpenAI翻译在多次重试后仍然失败。即将终止程序。")
                    raise last_exception
                
                await asyncio.sleep(1)

            except Exception as e:
                attempt += 1
                log_attempt = f"{attempt}/{max_retries}" if not is_infinite else f"Attempt {attempt}"
                last_exception = e
                self.logger.warning(f"OpenAI高质量翻译出错 ({log_attempt}): {e}")
                
                if not is_infinite and attempt >= max_retries:
                    self.logger.error("OpenAI翻译在多次重试后仍然失败。即将终止程序。")
                    raise last_exception
                
                await asyncio.sleep(1)

        # 只有在所有重试都失败后才会执行到这里
        raise last_exception if last_exception else Exception("OpenAI translation failed after all retries")

    async def _translate(self, from_lang: str, to_lang: str, queries: List[str], ctx=None) -> List[str]:
        """主翻译方法"""
        if not queries:
            return []
        
        # 检查是否为高质量批量翻译模式
        if ctx and hasattr(ctx, 'high_quality_batch_data'):
            batch_data = ctx.high_quality_batch_data
            if batch_data and len(batch_data) > 0:
                self.logger.info(f"使用OpenAI高质量翻译模式处理{len(batch_data)}张图片")
                return await self._translate_batch_high_quality(queries, batch_data, from_lang, to_lang)
        
        # 普通单文本翻译（后备方案）
        if not self.client:
            self._setup_client()
        
        try:
            simple_prompt = f"Translate the following {from_lang} text to {target_lang}. Provide only the translation:\n\n" + "\n".join(queries)
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": simple_prompt}],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            if response.choices and response.choices[0].message.content:
                result = response.choices[0].message.content.strip()
                translations = result.split('\n')
                translations = [t.strip() for t in translations if t.strip()]
                
                # 确保数量匹配
                while len(translations) < len(queries):
                    translations.append(queries[len(translations)] if len(translations) < len(queries) else "")
                
                return translations[:len(queries)]
                
        except Exception as e:
            self.logger.error(f"OpenAI翻译出错: {e}")
        
        return queries