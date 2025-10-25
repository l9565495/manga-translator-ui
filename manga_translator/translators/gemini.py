import re
import google.generativeai as genai
from google.generativeai import types

import asyncio
from typing import List
from .common import MissingAPIKeyException, InvalidServerResponse
from .keys import GEMINI_API_KEY, GEMINI_MODEL
from .common_gpt import CommonGPTTranslator, _CommonGPTTranslator_JSON


# Text Formatting:
# For Windows: enable ANSI escape code support
from colorama import init as initColorama

BOLD='\033[1m' # Bold text
NRML='\033[0m' # Revert to Normal formatting

class GeminiTranslator(CommonGPTTranslator):
    _INVALID_REPEAT_COUNT = 0  # 现在这个参数没意义了
    _MAX_REQUESTS_PER_MINUTE = 9999  # 无RPM限制
    _TIMEOUT = 40  # 在重试之前等待服务器响应的时间（秒）
    _RETRY_ATTEMPTS = 3  # 在放弃之前重试错误请求的次数
    _TIMEOUT_RETRY_ATTEMPTS = 3  # 在放弃之前重试超时请求的次数
    _RATELIMIT_RETRY_ATTEMPTS = 3  # 在放弃之前重试速率限制请求的次数

    _MAX_TOKENS = 8192
    _MAX_TOKENS_IN = _MAX_TOKENS // 2

    def __init__(self):
        _CONFIG_KEY = 'gemini.' + GEMINI_MODEL
        CommonGPTTranslator.__init__(self, config_key=_CONFIG_KEY)
        initColorama()

        self.cached_content = None
        self.templateCache = None
        self.cachedVals={None}

        # 重新加载 .env 文件以获取最新配置
        from dotenv import load_dotenv
        load_dotenv(override=True)

        # 重新读取环境变量
        import os
        api_key = os.getenv('GEMINI_API_KEY', GEMINI_API_KEY)
        api_base = os.getenv('GEMINI_API_BASE')

        if not api_key:
            raise MissingAPIKeyException(
                        'Please set the GEMINI_API_KEY environment variable '
                        'before using the Gemini translator.'
                    )

        client_options = {"api_endpoint": api_base} if api_base else None

        genai.configure(
            api_key=api_key,
            transport='rest',
            client_options=client_options
        )

        # 只有在使用官方API时才尝试获取模型信息，避免第三方API的404错误
        is_third_party_api = api_base and api_base != 'https://generativelanguage.googleapis.com'
        if not is_third_party_api:
            try:
                model_info = genai.get_model(f'models/{GEMINI_MODEL}')
                self._MAX_TOKENS = model_info.output_token_limit
                self._MAX_TOKENS_IN = self._MAX_TOKENS // 2
            except Exception as e:
                self.logger.warning(f"Could not get model info for {GEMINI_MODEL}. Using default token limits. Error: {e}")

        # 只有在使用官方API时才设置safety_settings，第三方API可能不支持
        self.safety_settings = None
        if not is_third_party_api:
            self.safety_settings = [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE",
                }
            ]
        else:
            self.logger.info("检测到第三方API，已禁用安全设置和模型信息获取")
        
        generation_config = {
            "temperature": self.temperature,
            "top_p": self.top_p,
        }

        self.client = genai.GenerativeModel(GEMINI_MODEL, generation_config=generation_config, safety_settings=self.safety_settings)
        
        self.token_count = 0
        self.token_count_last = 0 
        self.config = None

    @property
    def useCache(self) -> bool:
        return False

    def withinTokenLimit(self, text: str) -> bool:
        return True

    def parse_args(self, args: CommonGPTTranslator):
        super().parse_args(args)
        if self.json_mode:
            self._init_json_mode()
        else:
            self._init_standard_mode()

    def _init_json_mode(self):
        self._json_funcs = _GeminiTranslator_json(self)
        self._createContext = self._json_funcs._createContext
        self._request_translation = self._json_funcs._request_translation
        self._assemble_prompts = self._json_funcs._assemble_prompts
        self._parse_response = self._json_funcs._parse_response

    def _init_standard_mode(self):
        self._assemble_prompts = super()._assemble_prompts

    def count_tokens(self, text: str) -> int:
        # Bypassed by withinTokenLimit, but providing a safe fallback.
        return len(text)
    
    def _createContext(self, to_lang: str):
        pass
        
    def _needRecache(self) -> bool:
        return False

    async def _translate(self, from_lang: str, to_lang: str, queries: List[str], ctx=None) -> List[str]:
        # 保存ctx到实例变量，供_request_translation使用
        self.ctx = ctx

        self.to_lang=to_lang
        translations = [''] * len(queries)
        self.logger.debug(f'Temperature: {self.temperature}, TopP: {self.top_p}')
        MAX_SPLIT_ATTEMPTS = 5
        # 优先使用配置中的attempts，如果没有则使用默认的_RETRY_ATTEMPTS
        RETRY_ATTEMPTS = self.attempts if hasattr(self, 'attempts') and self.attempts is not None else self._RETRY_ATTEMPTS

        async def translate_batch(prompt_queries, prompt_query_indices, split_level=0):
            nonlocal MAX_SPLIT_ATTEMPTS
            prompt, query_size = self._assemble_prompts(from_lang, to_lang, prompt_queries, ctx).__next__()

            server_error_attempt = 0
            attempt = 0
            while True:  # 使用while True来支持无限重试
                if RETRY_ATTEMPTS != -1 and attempt >= RETRY_ATTEMPTS:
                    break
                try:
                    response_text = await self._request_translation(to_lang, prompt)
                    new_translations = self._parse_response(response_text, prompt_queries)

                    if len(new_translations) < query_size:
                        new_translations = re.split(r'\n', response_text)

                    if len(new_translations) < query_size:
                        self.logger.warning(f'Incomplete response, retrying...')
                        attempt += 1
                        continue

                    new_translations = new_translations[:query_size] + [''] * (query_size - len(new_translations))
                    new_translations = [t.split('\n')[0].strip() for t in new_translations]
                    new_translations = [re.sub(r'^\s*<\|\d+\|>\s*', '', t) for t in new_translations]

                    for idx, translation in zip(prompt_query_indices, new_translations):
                        translations[idx] = translation

                    self.logger.info(f'Batch translated: {len([t for t in translations if t])}/{len(queries)} completed.')
                    return True
                except Warning as e:
                    if 'Single query response does not contain prefix' in str(e):
                        # 对于没有前缀的单个查询响应，直接使用响应文本
                        response_text = await self._request_translation(to_lang, prompt)
                        new_translations = [response_text.strip()]

                        for idx, translation in zip(prompt_query_indices, new_translations):
                            translations[idx] = translation

                        self.logger.info(f'Batch translated: {len([t for t in translations if t])}/{len(queries)} completed.')
                        return True
                    else:
                        raise
                except Exception as e:
                    if isinstance(e, (types.BlockedPromptException, types.StopCandidateException)):
                        self.logger.error(f"Translation blocked by API safety settings: {e}")
                        raise

                    server_error_attempt += 1
                    # 检查是否超过重试次数（-1表示无限重试）
                    if RETRY_ATTEMPTS != -1 and server_error_attempt >= RETRY_ATTEMPTS:
                        self.logger.error(f'Gemini encountered a server error: {e}. Use a different translator or try again later.')
                        raise
                    self.logger.warning(f'Restarting request due to a server error. Attempt: {server_error_attempt}')
                    await asyncio.sleep(1)

                # 增加尝试计数器
                attempt += 1

            if split_level < MAX_SPLIT_ATTEMPTS:  
                mid_index = len(prompt_queries) // 2  
                futures = [translate_batch(prompt_queries[:mid_index], prompt_query_indices[:mid_index], split_level + 1),
                           translate_batch(prompt_queries[mid_index:], prompt_query_indices[mid_index:], split_level + 1)]
                await asyncio.gather(*futures)
                return True
            else:  
                self.logger.error('Maximum split attempts reached.')  
                return False

        success = await translate_batch(queries, list(range(len(queries))))
        if not success:
            self.logger.error("Gemini translation failed after all retries and split attempts")
            raise RuntimeError("Gemini translation failed after all retries and split attempts")
        return translations

    def formatLog(self, vals: dict) -> str:
        return '\n---\n'.join(f"\n{BOLD}{aKey}{NRML}:\n{aVal}" for aKey, aVal in vals.items())

    async def _request_translation(self, to_lang: str, prompt: str) -> str:
        # 从ctx获取line_break_prompt（如果有）
        line_break_prompt_str = ""
        if hasattr(self, 'ctx') and self.ctx and hasattr(self.ctx, 'line_break_prompt_json'):
            line_break_prompt_json = self.ctx.line_break_prompt_json
            if line_break_prompt_json and line_break_prompt_json.get('line_break_prompt'):
                line_break_prompt_str = line_break_prompt_json['line_break_prompt']

        system_instruction = self.chat_system_template.format(to_lang=to_lang)

        # 如果有line_break_prompt，添加到system instruction前面
        if line_break_prompt_str:
            system_instruction = f"{line_break_prompt_str}\n\n---\n\n{system_instruction}"

        lang_chat_samples = self.get_chat_sample(to_lang)

        messages = []

        # Add chat samples if available
        if lang_chat_samples:
            messages.extend([
                {"role": "user", "parts": [{"text": lang_chat_samples[0]}]},
                {"role": "model", "parts": [{"text": lang_chat_samples[1]}]}
            ])

        # Add the actual prompt
        if hasattr(prompt, 'parts'):
            prompt_text = "".join(p.text for p in prompt.parts)
        else:
            prompt_text = str(prompt)

        messages.append({"role": "user", "parts": [{"text": prompt_text}]})

        # Configure the model with system instruction
        generation_config = {
            "temperature": self.temperature,
            "top_p": self.top_p,
        }

        if system_instruction:
            model = genai.GenerativeModel(
                GEMINI_MODEL,
                generation_config=generation_config,
                safety_settings=self.safety_settings,
                system_instruction=system_instruction
            )
        else:
            model = self.client

        response = await asyncio.to_thread(
            model.generate_content,
            messages
        )

        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            self.token_count += response.usage_metadata.prompt_token_count
            self.token_count_last = response.usage_metadata.total_token_count

        # 安全的响应处理
        if not response.candidates or len(response.candidates) == 0:
            raise ValueError("API返回了空的候选回应，可能是内容被安全过滤器阻止")

        return response.text

class _GeminiTranslator_json (_CommonGPTTranslator_JSON):
    from .config_gpt import TranslationList
    import json

    def __init__(self, translator: GeminiTranslator):
        super().__init__(translator)
        self.translator = translator
        self.logger = self.translator.logger 

    def _createContext(self, to_lang: str):
        pass

    async def _request_translation(self, to_lang: str, prompt: str) -> str:
        # 从ctx获取line_break_prompt（如果有）
        line_break_prompt_str = ""
        if hasattr(self.translator, 'ctx') and self.translator.ctx and hasattr(self.translator.ctx, 'line_break_prompt_json'):
            line_break_prompt_json = self.translator.ctx.line_break_prompt_json
            if line_break_prompt_json and line_break_prompt_json.get('line_break_prompt'):
                line_break_prompt_str = line_break_prompt_json['line_break_prompt']

        system_instruction = self.translator.chat_system_template.format(to_lang=to_lang)

        # 如果有line_break_prompt，添加到system instruction前面
        if line_break_prompt_str:
            system_instruction = f"{line_break_prompt_str}\n\n---\n\n{system_instruction}"

        lang_JSON_samples = self.translator.get_json_sample(to_lang)

        messages = []

        # Add JSON samples if available
        if lang_JSON_samples:
            messages.extend([
                {"role": "user", "parts": [{"text": lang_JSON_samples[0].model_dump_json()}]},
                {"role": "model", "parts": [{"text": lang_JSON_samples[1].model_dump_json()}]}
            ])

        # Add the actual prompt
        prompt_text = str(prompt)
        messages.append({"role": "user", "parts": [{"text": prompt_text}]})

        json_config = {
            "temperature": self.translator.temperature,
            "top_p": self.translator.top_p,
            "response_mime_type": "application/json",
            "response_schema": self.TranslationList
        }

        # Configure the model with system instruction and JSON config
        if system_instruction:
            model = genai.GenerativeModel(
                GEMINI_MODEL,
                generation_config=json_config,
                safety_settings=self.translator.safety_settings,
                system_instruction=system_instruction
            )
        else:
            model = genai.GenerativeModel(
                GEMINI_MODEL,
                generation_config=json_config,
                safety_settings=self.translator.safety_settings
            )

        response = await asyncio.to_thread(
            model.generate_content,
            messages
        )

        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            self.translator.token_count += response.usage_metadata.prompt_token_count
            self.translator.token_count_last = response.usage_metadata.total_token_count

        # 安全的响应处理
        if not response.candidates or len(response.candidates) == 0:
            raise ValueError("API返回了空的候选回应，可能是内容被安全过滤器阻止")

        return response.text