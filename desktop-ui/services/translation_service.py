"""
翻译服务
支持多种翻译器的选择和配置管理，根据配置文件参数调用相应的翻译器
"""
import asyncio
import logging
import numpy as np
import sys
import os
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from PIL import Image

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), '..'))

try:
    from manga_translator.translators import dispatch as dispatch_translator
    from manga_translator.config import Translator, TranslatorConfig, TranslatorChain
    from manga_translator.utils import Context, TextBlock
    TRANSLATOR_AVAILABLE = True
except ImportError as e:
    logging.warning(f"翻译器后端模块导入失败: {e}")
    TRANSLATOR_AVAILABLE = False
    # 定义fallback类型
    class Translator:
        sugoi = "sugoi"
    
    class TranslatorConfig:
        pass
    
    class Context:
        pass

@dataclass
class TranslationResult:
    original_text: str
    translated_text: str
    translator_used: str

class TranslationService:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.current_translator_enum = Translator.sugoi
        self.current_target_lang = 'CHS'

    def get_available_translators(self) -> List[str]:
        if not TRANSLATOR_AVAILABLE:
            return []
        return [t.value for t in Translator]

    def get_target_languages(self) -> Dict[str, str]:
        """获取支持的目标语言列表（中文）"""
        return {
            'CHS': '简体中文',
            'CHT': '繁体中文',
            'CSY': '捷克语',
            'NLD': '荷兰语',
            'ENG': '英语',
            'FRA': '法语',
            'DEU': '德语',
            'HUN': '匈牙利语',
            'ITA': '意大利语',
            'JPN': '日语',
            'KOR': '韩语',
            'POL': '波兰语',
            'PTB': '葡萄牙语（巴西）',
            'ROM': '罗马尼亚语',
            'RUS': '俄语',
            'ESP': '西班牙语',
            'TRK': '土耳其语',
            'UKR': '乌克兰语',
            'VIN': '越南语',
            'ARA': '阿拉伯语',
            'SRP': '塞尔维亚语',
            'HRV': '克罗地亚语',
            'THA': '泰语',
            'IND': '印度尼西亚语',
            'FIL': '菲律宾语（他加禄语）'
        }

    async def translate_text(self, text: str, 
                           translator: Optional[Translator] = None,
                           target_lang: Optional[str] = None,
                           config: Optional[TranslatorConfig] = None) -> Optional[TranslationResult]:
        if not TRANSLATOR_AVAILABLE or not text or not text.strip():
            return None

        translator_to_use = translator or self.current_translator_enum
        target_lang_to_use = target_lang or self.current_target_lang

        try:
            chain_string = f"{translator_to_use.value}:{target_lang_to_use}"
            chain = TranslatorChain(chain_string)
            ctx = Context()
            ctx.text = text
            queries = [text]

            translated_texts = await dispatch_translator(
                chain,
                queries,
                translator_config=config,
                args=ctx
            )

            if translated_texts:
                return TranslationResult(
                    original_text=text,
                    translated_text=translated_texts[0],
                    translator_used=translator_to_use.value
                )
            return None
        except Exception as e:
            self.logger.error(f"翻译失败: {e}")
            raise

    async def translate_text_batch(self, texts: List[str],
                                 translator: Optional[Translator] = None,
                                 target_lang: Optional[str] = None,
                                 config: Optional[TranslatorConfig] = None,
                                 image: Optional[Image.Image] = None,
                                 regions: Optional[List[Dict[str, Any]]] = None) -> List[Optional[TranslationResult]]:
        if not TRANSLATOR_AVAILABLE or not texts:
            return [None] * len(texts)

        translator_to_use = translator or self.current_translator_enum
        target_lang_to_use = target_lang or self.current_target_lang

        try:
            chain_string = f"{translator_to_use.value}:{target_lang_to_use}"
            chain = TranslatorChain(chain_string)
            ctx = Context()
            if image and regions:
                ctx.img_rgb = np.array(image.convert("RGB"))
                ctx.text_regions = [TextBlock(**r) for r in regions]
                
                # For HQ translators, create the expected data structure
                batch_item = {
                    'image': image,
                    'original_texts': [r.get('text', '') for r in regions]
                }
                ctx.high_quality_batch_data = [batch_item]

            # Although the backend translator takes a list, the context `text` is not used in the same way.
            # We can leave it empty or set it to the first text.
            if texts:
                ctx.text = texts[0]

            translated_texts = await dispatch_translator(
                chain,
                texts,  # Pass the whole list of texts
                translator_config=config,
                args=ctx
            )

            if translated_texts and len(translated_texts) == len(texts):
                return [
                    TranslationResult(
                        original_text=original,
                        translated_text=translated,
                        translator_used=translator_to_use.value
                    ) for original, translated in zip(texts, translated_texts)
                ]
            
            # Handle cases where translation returns an unexpected number of results
            self.logger.warning(f"Batch translation returned {len(translated_texts) if translated_texts else 0} results for {len(texts)} inputs.")
            return [None] * len(texts)

        except Exception as e:
            self.logger.error(f"批量翻译失败: {e}")
            # In case of an exception, return a list of Nones
            return [None] * len(texts)

    def set_translator(self, translator_name: str):
        if TRANSLATOR_AVAILABLE and hasattr(Translator, translator_name):
            self.current_translator_enum = Translator[translator_name]

    def set_target_language(self, lang_code: str):
        self.current_target_lang = lang_code