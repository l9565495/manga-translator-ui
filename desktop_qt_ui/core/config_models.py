from typing import Optional
import os

from pydantic import BaseModel, Field


class TranslatorSettings(BaseModel):
    translator: str = "openai_hq"
    target_lang: str = "CHS"
    no_text_lang_skip: bool = False
    # 相对路径，后端会用BASE_PATH拼接（打包后=_internal，开发时=项目根目录）
    gpt_config: Optional[str] = "examples/gpt_config-example.yaml"
    high_quality_prompt_path: Optional[str] = "dict/prompt_example.json"
    
    @property
    def chatgpt_config(self):
        """加载GPT配置文件"""
        if self.gpt_config is not None:
            try:
                from omegaconf import OmegaConf
                from manga_translator.utils.generic import BASE_PATH
                
                config_path = self.gpt_config
                if not os.path.isabs(config_path):
                    config_path = os.path.join(BASE_PATH, config_path)
                
                if os.path.exists(config_path):
                    return OmegaConf.load(config_path)
            except Exception:
                pass
        return None

class OcrSettings(BaseModel):
    use_mocr_merge: bool = False
    ocr: str = "48px"
    use_hybrid_ocr: bool = True
    secondary_ocr: str = "mocr"
    min_text_length: int = 0
    ignore_bubble: int = 0
    prob: float = 0.1
    merge_gamma: float = 0.8
    merge_sigma: float = 2.5
    merge_edge_ratio_threshold: float = 0.0

class DetectorSettings(BaseModel):
    detector: str = "default"
    detection_size: int = 2048
    text_threshold: float = 0.5
    det_rotate: bool = False
    det_auto_rotate: bool = False
    det_invert: bool = False
    det_gamma_correct: bool = False
    box_threshold: float = 0.5
    unclip_ratio: float = 2.5

class InpainterSettings(BaseModel):
    inpainter: str = "lama_mpe"
    inpainting_size: int = 2048
    inpainting_precision: str = "fp32"

class RenderSettings(BaseModel):
    renderer: str = "default"
    alignment: str = "auto"
    disable_font_border: bool = False
    disable_auto_wrap: bool = True
    font_size_offset: int = 0
    font_size_minimum: int = 0
    direction: str = "auto"
    uppercase: bool = False
    lowercase: bool = False
    gimp_font: str = "Arial-Unicode-Regular.ttf"
    font_path: str = "Arial-Unicode-Regular.ttf"
    no_hyphenation: bool = False
    font_color: Optional[str] = None
    line_spacing: Optional[float] = None
    font_size: Optional[int] = None
    auto_rotate_symbols: bool = True
    rtl: bool = False
    layout_mode: str = "smart_scaling"
    max_font_size: int = 0
    font_scale_ratio: float = 1.0
    center_text_in_bubble: bool = False

class UpscaleSettings(BaseModel):
    upscaler: str = "esrgan"
    revert_upscaling: bool = False

class ColorizerSettings(BaseModel):
    colorization_size: int = 576
    denoise_sigma: int = 30
    colorizer: str = "none"

class CliSettings(BaseModel):
    verbose: bool = True
    attempts: int = -1
    ignore_errors: bool = False
    use_gpu: bool = True
    use_gpu_limited: bool = False
    context_size: int = 3
    format: str = "不指定"
    overwrite: bool = True
    skip_no_text: bool = False
    use_mtpe: bool = False
    save_text: bool = True
    load_text: bool = False
    template: bool = False
    prep_manual: bool = False
    save_quality: int = 100
    batch_size: int = 1
    batch_concurrent: bool = False
    generate_and_export: bool = False
    colorize_only: bool = False
    high_quality_batch_size: int = 3

class AppSection(BaseModel):
    last_open_dir: str = '.'
    last_output_path: str = ""

class AppSettings(BaseModel):
    app: AppSection = Field(default_factory=AppSection)
    filter_text: Optional[str] = None
    kernel_size: int = 3
    mask_dilation_offset: int = 70
    translator: TranslatorSettings = Field(default_factory=TranslatorSettings)
    ocr: OcrSettings = Field(default_factory=OcrSettings)
    detector: DetectorSettings = Field(default_factory=DetectorSettings)
    inpainter: InpainterSettings = Field(default_factory=InpainterSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)
    upscale: UpscaleSettings = Field(default_factory=UpscaleSettings)
    colorizer: ColorizerSettings = Field(default_factory=ColorizerSettings)
    cli: CliSettings = Field(default_factory=CliSettings)
