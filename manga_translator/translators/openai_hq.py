import os
import re
import asyncio
import base64
import json
import logging
from io import BytesIO
from typing import List, Dict, Any
from PIL import Image
import httpx
import openai
from openai import AsyncOpenAI

from .common import CommonTranslator, VALID_LANGUAGES, draw_text_boxes_on_image
from .keys import OPENAI_API_KEY, OPENAI_MODEL
from ..utils import Context

# 禁用openai库的DEBUG日志,避免打印base64图片数据
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

# 浏览器风格的请求头，避免被 CF 拦截
# 注意：移除 Accept-Encoding 让 httpx 自动处理，避免压缩响应导致的 UTF-8 解码错误
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}


def encode_image_for_openai(image, max_size=1024):
    """将图片编码为base64格式，适合OpenAI API"""
    # 转换图片格式为RGB（处理所有可能的图片模式）
    if image.mode == "P":
        # 调色板模式：转换为RGBA（如果有透明度）或RGB
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")

    if image.mode == "RGBA":
        # RGBA模式：创建白色背景并合并透明通道
        background = Image.new('RGB', image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    elif image.mode in ("LA", "L", "1", "CMYK"):
        # LA（灰度+透明）、L（灰度）、1（二值）、CMYK：统一转换为RGB
        if image.mode == "LA":
            # 灰度+透明：先转RGBA再合并到白色背景
            image = image.convert("RGBA")
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[-1])
            image = background
        else:
            # 其他模式：直接转RGB
            image = image.convert("RGB")
    elif image.mode != "RGB":
        # 其他未知模式：强制转换为RGB
        image = image.convert("RGB")

    # 调整图片大小
    w, h = image.size
    if max(w, h) > max_size:
        scale = max_size / max(w, h)
        new_w, new_h = int(w * scale), int(h * scale)
        image = image.resize((new_w, new_h), Image.LANCZOS)

    # 编码为base64（使用PNG格式确保质量和兼容性）
    buf = BytesIO()
    image.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode('utf-8')


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

class OpenAIHighQualityTranslator(CommonTranslator):
    """
    OpenAI高质量翻译器
    支持多图片批量处理，提供文本框顺序、原文和原图给AI进行更精准的翻译
    """
    _LANGUAGE_CODE_MAP = VALID_LANGUAGES
    
    # 类变量: 跨实例共享的RPM限制时间戳
    _GLOBAL_LAST_REQUEST_TS = {}  # {model_name: timestamp}
    
    def __init__(self):
        super().__init__()
        self.client = None
        self.prev_context = ""  # 用于存储多页上下文
        
        # 只在非Web环境下重新加载.env文件
        # Web环境下不重新加载，避免覆盖用户临时设置的环境变量
        is_web_server = os.getenv('MANGA_TRANSLATOR_WEB_SERVER', 'false').lower() == 'true'
        if not is_web_server:
            from dotenv import load_dotenv
            load_dotenv(override=True)
        
        self.api_key = os.getenv('OPENAI_API_KEY', OPENAI_API_KEY)
        self.base_url = os.getenv('OPENAI_API_BASE', 'https://api.openai.com/v1')
        self.model = os.getenv('OPENAI_MODEL', "gpt-4o")
        self.max_tokens = None  # 不限制，使用模型默认最大值
        self.temperature = 0.1
        self._MAX_REQUESTS_PER_MINUTE = 0  # 默认无限制
        # 使用全局时间戳,跨实例共享
        if self.model not in OpenAIHighQualityTranslator._GLOBAL_LAST_REQUEST_TS:
            OpenAIHighQualityTranslator._GLOBAL_LAST_REQUEST_TS[self.model] = 0
        self._last_request_ts_key = self.model
        self._setup_client()
    
    def set_prev_context(self, context: str):
        """设置多页上下文（用于context_size > 0时）"""
        self.prev_context = context if context else ""
    
    def parse_args(self, args):
        """解析配置参数"""
        # 调用父类的 parse_args 来设置通用参数（包括 attempts、post_check 等）
        super().parse_args(args)
        
        # 同步 attempts 到 _max_total_attempts
        self._max_total_attempts = self.attempts
        
        # 从配置中读取RPM限制
        max_rpm = getattr(args, 'max_requests_per_minute', 0)
        if max_rpm > 0:
            self._MAX_REQUESTS_PER_MINUTE = max_rpm
            self.logger.info(f"Setting OpenAI HQ max requests per minute to: {max_rpm}")
        
        # 从配置中读取用户级 API Key（优先于环境变量）
        # 这允许 Web 服务器为每个用户使用不同的 API Key
        need_rebuild_client = False
        
        user_api_key = getattr(args, 'user_api_key', None)
        if user_api_key:
            self.api_key = user_api_key
            need_rebuild_client = True
            self.logger.info("[UserAPIKey] Using user-provided API key")
        
        user_api_base = getattr(args, 'user_api_base', None)
        if user_api_base:
            self.base_url = user_api_base
            need_rebuild_client = True
            self.logger.info(f"[UserAPIKey] Using user-provided API base: {user_api_base}")
        
        user_api_model = getattr(args, 'user_api_model', None)
        if user_api_model:
            self.model = user_api_model
            self.logger.info(f"[UserAPIKey] Using user-provided model: {user_api_model}")
        
        # 如果 API Key 或 Base URL 变化，重建客户端
        if need_rebuild_client:
            self.client = None
            self._setup_client()
    
    def _setup_client(self):
        """设置OpenAI客户端"""
        if not self.client:
            # 使用浏览器式请求头，避免被 Cloudflare 阻止
            self.client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                default_headers=BROWSER_HEADERS,
                http_client=httpx.AsyncClient(
                    headers=BROWSER_HEADERS,
                    timeout=httpx.Timeout(300.0, connect=60.0)
                )
            )
    
    async def _cleanup(self):
        """清理资源"""
        if self.client:
            try:
                await self.client.close()
            except Exception:
                pass  # 忽略清理时的错误
    
    def __del__(self):
        """析构函数，确保资源被清理"""
        if self.client:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果事件循环还在运行，创建清理任务
                    asyncio.create_task(self._cleanup())
                elif not loop.is_closed():
                    # 如果事件循环未关闭，同步执行清理
                    loop.run_until_complete(self._cleanup())
            except Exception:
                pass  # 忽略所有清理错误

    
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
            base_prompt = f"""You are an expert manga translator. Your task is to accurately translate manga text from the source language into **{{{target_lang}}}**. You will be given the full manga page for context.

**CRITICAL INSTRUCTIONS (FOLLOW STRICTLY):**

1.  **DIRECT TRANSLATION ONLY**: Your output MUST contain ONLY the raw, translated text. Nothing else.
    -   DO NOT include the original text.
    -   DO NOT include any explanations, greetings, apologies, or any conversational text.
    -   DO NOT use Markdown formatting (like ```json or ```).
    -   The output is fed directly to an automated script. Any extra text will cause it to fail.

2.  **MATCH LINE COUNT**: The number of lines in your output MUST EXACTLY match the number of text regions you are asked to translate. Each line in your output corresponds to one numbered text region in the input.

3.  **TRANSLATE EVERYTHING**: Translate all text provided, including sound effects and single characters. Do not leave any line untranslated.

4.  **ACCURACY AND TONE**:
    -   Preserve the original tone, emotion, and character's voice.
    -   Ensure consistent translation of names, places, and special terms.
    -   For onomatopoeia (sound effects), provide the equivalent sound in {{{target_lang}}} or a brief description (e.g., '(rumble)', '(thud)').

---

**EXAMPLE OF CORRECT AND INCORRECT OUTPUT:**

**[ CORRECT OUTPUT EXAMPLE ]**
This is a correct response. Notice it only contains the translated text, with each translation on a new line.

(Imagine the user input was: "1. うるさい！", "2. 黙れ！")
```
吵死了！
闭嘴！
```

**[ ❌ INCORRECT OUTPUT EXAMPLE ]**
This is an incorrect response because it includes extra text and explanations.

(Imagine the user input was: "1. うるさい！", "2. 黙れ！")
```
好的，这是您的翻译：
1. 吵死了！
2. 闭嘴！
```
**REASONING:** The above example is WRONG because it includes "好的，这是您的翻译：" and numbering. Your response must be ONLY the translated text, line by line.

---

**FINAL INSTRUCTION:** Now, perform the translation task. Remember, your response must be clean, containing only the translated text.
"""

        # Replace placeholder with the full language name
        base_prompt = base_prompt.replace("{{{target_lang}}}", target_lang_full)
        
        # Also replace target_lang placeholder in custom prompt
        if custom_prompt_str:
            custom_prompt_str = custom_prompt_str.replace("{{{target_lang}}}", target_lang_full)

        # Combine prompts
        final_prompt = ""
        if line_break_prompt_str:
            final_prompt += f"{line_break_prompt_str}\n\n---\n\n"
        if custom_prompt_str:
            final_prompt += f"{custom_prompt_str}\n\n---\n\n"
        
        final_prompt += base_prompt
        # self.logger.info(f"--- OpenAI HQ Final System Prompt ---\n{final_prompt}")
        return final_prompt

    def _build_user_prompt(self, batch_data: List[Dict], ctx: Any, retry_attempt: int = 0, retry_reason: str = "") -> str:
        """构建用户提示词（高质量版）- 使用统一方法，只包含上下文和待翻译文本"""
        return self._build_user_prompt_for_hq(batch_data, ctx, self.prev_context, retry_attempt=retry_attempt, retry_reason=retry_reason)
    
    def _get_system_prompt(self, source_lang: str, target_lang: str, custom_prompt_json: Dict[str, Any] = None, line_break_prompt_json: Dict[str, Any] = None) -> str:
        """获取完整的系统提示词（包含断句提示词、自定义提示词和基础系统提示词）"""
        return self._build_system_prompt(source_lang, target_lang, custom_prompt_json=custom_prompt_json, line_break_prompt_json=line_break_prompt_json)

    async def _translate_batch_high_quality(self, texts: List[str], batch_data: List[Dict], source_lang: str, target_lang: str, custom_prompt_json: Dict[str, Any] = None, line_break_prompt_json: Dict[str, Any] = None, ctx: Any = None, split_level: int = 0) -> List[str]:
        """高质量批量翻译方法"""
        if not texts:
            return []
        
        if not self.client:
            self._setup_client()
        
        # 准备图片
        self.logger.info(f"高质量翻译模式：正在打包 {len(batch_data)} 张图片并发送...")

        image_contents = []
        for img_idx, data in enumerate(batch_data):
            image = data['image']
            
            # 在图片上绘制带编号的文本框
            text_regions = data.get('text_regions', [])
            text_order = data.get('text_order', [])
            upscaled_size = data.get('upscaled_size')
            if text_regions and text_order:
                image = draw_text_boxes_on_image(image, text_regions, text_order, upscaled_size)
                self.logger.debug(f"已在图片上绘制 {len(text_regions)} 个带编号的文本框")
            
            base64_img = encode_image_for_openai(image)
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{base64_img}"}
            })
        
        # 构建消息：系统提示词放在 system role，用户内容（文本+图片）放在 user role
        system_prompt = self._get_system_prompt(source_lang, target_lang, custom_prompt_json=custom_prompt_json, line_break_prompt_json=line_break_prompt_json)
        
        # 初始化重试信息
        retry_attempt = 0
        retry_reason = ""
        
        # 发送请求
        max_retries = self.attempts
        attempt = 0
        is_infinite = max_retries == -1
        last_exception = None
        local_attempt = 0  # 本次批次的尝试次数

        while is_infinite or attempt < max_retries:
            # 检查是否被取消
            self._check_cancelled()
            
            # 检查全局尝试次数
            if not self._increment_global_attempt():
                self.logger.error("Reached global attempt limit. Stopping translation.")
                # 包含最后一次错误的真正原因
                last_error_msg = str(last_exception) if last_exception else "Unknown error"
                raise Exception(f"达到最大尝试次数 ({self._max_total_attempts})，最后一次错误: {last_error_msg}")

            local_attempt += 1
            attempt += 1

            # 文本分割逻辑已禁用
            # if local_attempt > self._SPLIT_THRESHOLD and len(texts) > 1 and split_level < self._MAX_SPLIT_ATTEMPTS:
            #     self.logger.warning(f"Triggering split after {local_attempt} local attempts")
            #     raise self.SplitException(local_attempt, texts)
            
            # 构建用户提示词（包含重试信息以避免缓存）
            user_prompt = self._build_user_prompt(batch_data, ctx, retry_attempt=retry_attempt, retry_reason=retry_reason)
            user_content = [{"type": "text", "text": user_prompt}]
            user_content.extend(image_contents)
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ]

            try:
                # RPM限制
                if self._MAX_REQUESTS_PER_MINUTE > 0:
                    import time
                    now = time.time()
                    delay = 60.0 / self._MAX_REQUESTS_PER_MINUTE
                    elapsed = now - OpenAIHighQualityTranslator._GLOBAL_LAST_REQUEST_TS[self._last_request_ts_key]
                    if elapsed < delay:
                        sleep_time = delay - elapsed
                        self.logger.info(f'Ratelimit sleep: {sleep_time:.2f}s')
                        await asyncio.sleep(sleep_time)
                
                # 动态调整温度：质量检查或BR检查失败时提高温度帮助跳出错误模式
                current_temperature = self._get_retry_temperature(self.temperature, retry_attempt, retry_reason)
                if retry_attempt > 0 and current_temperature != self.temperature:
                    self.logger.info(f"[重试] 温度调整: {self.temperature} -> {current_temperature}")
                
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=self.max_tokens,
                    temperature=current_temperature
                )
                
                # 在API调用成功后立即更新时间戳，确保所有请求（包括重试）都被计入速率限制
                if self._MAX_REQUESTS_PER_MINUTE > 0:
                    OpenAIHighQualityTranslator._GLOBAL_LAST_REQUEST_TS[self._last_request_ts_key] = time.time()

                # 检查成功条件
                if response.choices and response.choices[0].message.content and response.choices[0].finish_reason != 'content_filter':
                    result_text = response.choices[0].message.content.strip()
                    
                    # ✅ 检测HTML错误响应（404等）- 抛出特定异常供统一错误处理
                    if result_text.startswith('<!DOCTYPE') or result_text.startswith('<html') or '<h1>404</h1>' in result_text:
                        raise Exception(f"API_404_ERROR: API返回HTML错误页面 - API地址({self.base_url})或模型({self.model})配置错误")
                    
                    # 去除 <think>...</think> 标签及内容（LM Studio 等本地模型的思考过程）
                    result_text = re.sub(r'(</think>)?<think>.*?</think>', '', result_text, flags=re.DOTALL)
                    # 提取 <answer>...</answer> 中的内容（如果存在）
                    answer_match = re.search(r'<answer>(.*?)</answer>', result_text, flags=re.DOTALL)
                    if answer_match:
                        result_text = answer_match.group(1).strip()
                    
                    # 增加清理步骤，移除可能的Markdown代码块
                    if result_text.startswith("```") and result_text.endswith("```"):
                        result_text = result_text[3:-3].strip()
                    
                    # 解析翻译结果
                    translations = []
                    for line in result_text.split('\n'):
                        line = line.strip()
                        if line:
                            line = re.sub(r'^\d+\.\s*', '', line)
                            # Replace other possible newline representations, but keep [BR]
                            line = line.replace('\\n', '\n').replace('↵', '\n')
                            translations.append(line)
                    
                    # Strict validation: must match input count
                    if len(translations) != len(texts):
                        retry_attempt += 1
                        retry_reason = f"Translation count mismatch: expected {len(texts)}, got {len(translations)}"
                        log_attempt = f"{attempt}/{max_retries}" if not is_infinite else f"Attempt {attempt}"
                        self.logger.warning(f"[{log_attempt}] {retry_reason}. Retrying...")
                        self.logger.warning(f"Expected texts: {texts}")
                        self.logger.warning(f"Got translations: {translations}")
                        
                        # 记录错误以便在达到最大尝试次数时显示
                        last_exception = Exception(f"翻译数量不匹配: 期望 {len(texts)} 条，实际得到 {len(translations)} 条")

                        if not is_infinite and attempt >= max_retries:
                            raise Exception(f"Translation count mismatch after {max_retries} attempts: expected {len(texts)}, got {len(translations)}")

                        await asyncio.sleep(2)
                        continue

                    # 质量验证：检查空翻译、合并翻译、可疑符号等
                    is_valid, error_msg = self._validate_translation_quality(texts, translations)
                    if not is_valid:
                        retry_attempt += 1
                        retry_reason = f"Quality check failed: {error_msg}"
                        log_attempt = f"{attempt}/{max_retries}" if not is_infinite else f"Attempt {attempt}"
                        self.logger.warning(f"[{log_attempt}] {retry_reason}. Retrying...")
                        
                        # 记录错误以便在达到最大尝试次数时显示
                        last_exception = Exception(f"翻译质量检查失败: {error_msg}")

                        if not is_infinite and attempt >= max_retries:
                            raise Exception(f"Quality check failed after {max_retries} attempts: {error_msg}")

                        await asyncio.sleep(2)
                        continue

                    self.logger.info("--- Translation Results ---")
                    for original, translated in zip(texts, translations):
                        self.logger.info(f'{original} -> {translated}')
                    self.logger.info("---------------------------")

                    # BR检查：检查翻译结果是否包含必要的[BR]标记
                    # BR check: Check if translations contain necessary [BR] markers
                    if not self._validate_br_markers(translations, batch_data=batch_data, ctx=ctx):
                        retry_attempt += 1
                        retry_reason = "BR markers missing in translations"
                        log_attempt = f"{attempt}/{max_retries}" if not is_infinite else f"Attempt {attempt}"
                        self.logger.warning(f"[{log_attempt}] {retry_reason}, retrying...")
                        
                        # 记录错误以便在达到最大尝试次数时显示
                        last_exception = Exception("AI断句检查失败: 翻译结果缺少必要的[BR]标记")
                        
                        # 如果达到最大重试次数，抛出友好的异常
                        if not is_infinite and attempt >= max_retries:
                            from .common import BRMarkersValidationException
                            self.logger.error("OpenAI高质量翻译在多次重试后仍然失败：AI断句检查失败。")
                            raise BRMarkersValidationException(
                                missing_count=0,  # 具体数字在_validate_br_markers中已记录
                                total_count=len(texts),
                                tolerance=max(1, len(texts) // 10)
                            )
                        
                        await asyncio.sleep(2)
                        continue

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

            except openai.BadRequestError as e:
                # 专门处理400错误，检查是否是多模态不支持问题
                error_message = str(e)
                is_multimodal_unsupported = any(keyword in error_message.lower() for keyword in [
                    'image_url', 'multimodal', 'vision', 'expected `text`', 'unknown variant'
                ])
                
                if is_multimodal_unsupported:
                    self.logger.error(f"❌ 模型 {self.model} 不支持多模态输入（图片+文本）")
                    self.logger.error(f"💡 解决方案：")
                    self.logger.error(f"   1. 使用支持多模态的模型（如 gpt-4o, gpt-4-vision-preview）")
                    self.logger.error(f"   2. 或者切换到普通翻译模式（不使用 _hq 高质量翻译器）")
                    self.logger.error(f"   3. DeepSeek模型不支持多模态，请勿使用 openai_hq 翻译器")
                    raise Exception(f"模型不支持多模态输入: {self.model}") from e
                else:
                    # 其他400错误，正常重试
                    attempt += 1
                    log_attempt = f"{attempt}/{max_retries}" if not is_infinite else f"Attempt {attempt}"
                    last_exception = e
                    self.logger.warning(f"OpenAI高质量翻译出错 ({log_attempt}): {e}")
                    
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

        # 重置全局尝试计数器
        self._reset_global_attempt_count()

        # 检查是否为高质量批量翻译模式
        if ctx and hasattr(ctx, 'high_quality_batch_data'):
            batch_data = ctx.high_quality_batch_data
            if batch_data and len(batch_data) > 0:
                self.logger.info(f"使用OpenAI高质量翻译模式处理{len(batch_data)}张图片，最大尝试次数: {self._max_total_attempts}")
                custom_prompt_json = getattr(ctx, 'custom_prompt_json', None)
                line_break_prompt_json = getattr(ctx, 'line_break_prompt_json', None)

                # 使用分割包装器进行翻译
                translations = await self._translate_with_split(
                    self._translate_batch_high_quality,
                    queries,
                    split_level=0,
                    batch_data=batch_data,
                    source_lang=from_lang,
                    target_lang=to_lang,
                    custom_prompt_json=custom_prompt_json,
                    line_break_prompt_json=line_break_prompt_json,
                    ctx=ctx
                )

                # 应用文本后处理（与普通翻译器保持一致）
                translations = [self._clean_translation_output(q, r, to_lang) for q, r in zip(queries, translations)]
                return translations
        
        # 普通单文本翻译（后备方案）
        if not self.client:
            self._setup_client()
        
        try:
            simple_prompt = f"Translate the following {from_lang} text to {to_lang}. Provide only the translation:\n\n" + "\n".join(queries)
            
            # RPM限制
            if self._MAX_REQUESTS_PER_MINUTE > 0:
                import time
                now = time.time()
                delay = 60.0 / self._MAX_REQUESTS_PER_MINUTE
                elapsed = now - OpenAIHighQualityTranslator._GLOBAL_LAST_REQUEST_TS[self._last_request_ts_key]
                if elapsed < delay:
                    sleep_time = delay - elapsed
                    self.logger.info(f'Ratelimit sleep: {sleep_time:.2f}s')
                    await asyncio.sleep(sleep_time)
            
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": simple_prompt}],
                max_tokens=self.max_tokens,
                temperature=self.temperature
            )
            
            # 在API调用成功后立即更新时间戳，确保所有请求（包括重试）都被计入速率限制
            if self._MAX_REQUESTS_PER_MINUTE > 0:
                OpenAIHighQualityTranslator._GLOBAL_LAST_REQUEST_TS[self._last_request_ts_key] = time.time()
            
            if response.choices and response.choices[0].message.content:
                result = response.choices[0].message.content.strip()
                
                # 去除 <think>...</think> 标签及内容（LM Studio 等本地模型的思考过程）
                result = re.sub(r'(</think>)?<think>.*?</think>', '', result, flags=re.DOTALL)
                # 提取 <answer>...</answer> 中的内容（如果存在）
                answer_match = re.search(r'<answer>(.*?)</answer>', result, flags=re.DOTALL)
                if answer_match:
                    result = answer_match.group(1).strip()
                
                translations = result.split('\n')
                translations = [t.strip() for t in translations if t.strip()]
                
                # Strict validation: must match input count
                if len(translations) != len(queries):
                    error_msg = f"Translation count mismatch: expected {len(queries)}, got {len(translations)}"
                    self.logger.error(error_msg)
                    self.logger.error(f"Queries: {queries}")
                    self.logger.error(f"Translations: {translations}")
                    raise Exception(error_msg)
                
                return translations
                
        except Exception as e:
            self.logger.error(f"OpenAI翻译出错: {e}")
        
        return queries