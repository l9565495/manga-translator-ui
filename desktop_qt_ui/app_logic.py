
"""
应用业务逻辑层
处理应用的核心业务逻辑，与UI层分离
"""
import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from manga_translator.config import (
    Alignment,
    Colorizer,
    Detector,
    Direction,
    Inpainter,
    InpaintPrecision,
    Ocr,
    Renderer,
    Translator,
    Upscaler,
)
from manga_translator.save import OUTPUT_FORMATS
from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QFileDialog

from services import (
    get_config_service,
    get_file_service,
    get_logger,
    get_state_manager,
    get_translation_service,
)
from services.state_manager import AppStateKey


@dataclass
class AppConfig:
    """应用配置信息"""
    window_size: tuple = (1200, 800)
    theme: str = "dark"
    language: str = "zh_CN"
    auto_save: bool = True
    max_recent_files: int = 10

class MainAppLogic(QObject):
    """主页面业务逻辑控制器"""
    files_added = pyqtSignal(list)
    files_cleared = pyqtSignal()
    file_removed = pyqtSignal(str)
    config_loaded = pyqtSignal(dict)
    output_path_updated = pyqtSignal(str)
    task_completed = pyqtSignal(list)
    task_file_completed = pyqtSignal(dict)
    log_message = pyqtSignal(str)
    render_setting_changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.logger = get_logger(__name__)
        self.config_service = get_config_service()
        self.translation_service = get_translation_service()
        self.file_service = get_file_service()
        self.state_manager = get_state_manager()

        self.thread = None
        self.worker = None
        self.saved_files_count = 0

        self.source_files: List[str] = [] # Holds both files and folders
        self.file_to_folder_map: Dict[str, Optional[str]] = {} # 记录文件来自哪个文件夹
        self.display_name_maps = None

        self.app_config = AppConfig()
        self.logger.info("主页面应用业务逻辑初始化完成")


    @pyqtSlot(dict)
    def on_file_completed(self, result):
        """处理单个文件处理完成的信号并保存"""
        if not result.get('success') or not result.get('image_data'):
            self.logger.error(f"Skipping save for failed item: {result.get('original_path')}")
            return

        try:
            config = self.config_service.get_config()
            output_format = config.cli.format
            save_quality = config.cli.save_quality
            output_folder = config.app.last_output_path

            if not output_folder:
                self.logger.error("输出目录未设置，无法保存文件。")
                self.state_manager.set_status_message("错误：输出目录未设置！")
                return

            original_path = result['original_path']
            base_filename = os.path.basename(original_path)

            # 检查文件是否来自文件夹
            source_folder = self.file_to_folder_map.get(original_path)

            if source_folder:
                # 文件来自文件夹，在输出目录创建同名文件夹
                folder_name = os.path.basename(source_folder)
                final_output_folder = os.path.join(output_folder, folder_name)
            else:
                # 文件是单独添加的，直接保存到输出目录
                final_output_folder = output_folder

            # 确定文件扩展名
            if output_format and output_format != "不指定":
                file_extension = f".{output_format}"
                output_filename = os.path.splitext(base_filename)[0] + file_extension
            else:
                # 保持原扩展名
                output_filename = base_filename

            final_output_path = os.path.join(final_output_folder, output_filename)

            os.makedirs(final_output_folder, exist_ok=True)

            save_kwargs = {}
            image_to_save = result['image_data']

            # Convert RGBA to RGB for JPEG format
            if final_output_path.lower().endswith(('.jpg', '.jpeg')):
                if image_to_save.mode == 'RGBA':
                    image_to_save = image_to_save.convert('RGB')
                save_kwargs['quality'] = save_quality
            elif final_output_path.lower().endswith('.webp'):
                save_kwargs['quality'] = save_quality

            image_to_save.save(final_output_path, **save_kwargs)

            # 更新translation_map.json
            self._update_translation_map(original_path, final_output_path)

            self.saved_files_count += 1
            self.logger.info(f"成功保存文件: {final_output_path}")
            self.task_file_completed.emit({'path': final_output_path})

        except Exception as e:
            self.logger.error(f"保存文件 {result['original_path']} 时出错: {e}")

    def _update_translation_map(self, source_path: str, translated_path: str):
        """在输出目录创建或更新 translation_map.json"""
        try:
            import json
            output_dir = os.path.dirname(translated_path)
            map_path = os.path.join(output_dir, 'translation_map.json')

            # 规范化路径以确保一致性
            source_path_norm = os.path.normpath(source_path)
            translated_path_norm = os.path.normpath(translated_path)

            translation_map = {}
            if os.path.exists(map_path):
                with open(map_path, 'r', encoding='utf-8') as f:
                    try:
                        translation_map = json.load(f)
                    except json.JSONDecodeError:
                        self.logger.warning(f"Could not decode {map_path}, creating a new one.")

            # 使用翻译后的路径作为键，确保唯一性
            translation_map[translated_path_norm] = source_path_norm

            with open(map_path, 'w', encoding='utf-8') as f:
                json.dump(translation_map, f, ensure_ascii=False, indent=4)

            self.logger.info(f"Updated translation_map.json: {translated_path_norm} -> {source_path_norm}")
        except Exception as e:
            self.logger.error(f"Failed to update translation_map.json: {e}")

    @pyqtSlot(str)
    def on_worker_log(self, message):
        self.log_message.emit(message)

    @pyqtSlot()
    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(None, "选择输出目录")
        if folder:
            self.update_single_config('app.last_output_path', folder)
            self.output_path_updated.emit(folder)

    @pyqtSlot()
    def open_output_folder(self):
        import subprocess
        import sys
        output_dir = self.config_service.get_config().app.last_output_path
        if not output_dir or not os.path.isdir(output_dir):
            self.logger.warning(f"Output path is not a valid directory: {output_dir}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(os.path.realpath(output_dir))
            elif sys.platform == "darwin":
                subprocess.run(["open", output_dir])
            else:
                subprocess.run(["xdg-open", output_dir])
        except Exception as e:
            self.logger.error(f"Failed to open output folder: {e}")

    def open_font_directory(self):
        import subprocess
        import sys
        # fonts目录在_internal里（打包后）或项目根目录（开发时）
        fonts_dir = os.path.join(self.config_service.root_dir, 'fonts')
        try:
            if not os.path.exists(fonts_dir):
                os.makedirs(fonts_dir)
            if sys.platform == "win32":
                os.startfile(fonts_dir)
            elif sys.platform == "darwin":
                subprocess.run(["open", fonts_dir])
            else:
                subprocess.run(["xdg-open", fonts_dir])
        except Exception as e:
            self.logger.error(f"Error opening font directory: {e}")

    def open_dict_directory(self):
        import subprocess
        import sys
        # dict目录在_internal里（打包后）或项目根目录（开发时）
        dict_dir = os.path.join(self.config_service.root_dir, 'dict')
        try:
            if not os.path.exists(dict_dir):
                os.makedirs(dict_dir)
            if sys.platform == "win32":
                os.startfile(dict_dir)
            elif sys.platform == "darwin":
                subprocess.run(["open", dict_dir])
            else:
                subprocess.run(["xdg-open", dict_dir])
        except Exception as e:
            self.logger.error(f"Error opening dict directory: {e}")

    def get_hq_prompt_options(self) -> List[str]:
        try:
            # dict目录在_internal里（打包后）或项目根目录（开发时）
            dict_dir = os.path.join(self.config_service.root_dir, 'dict')
            if not os.path.isdir(dict_dir):
                return []
            prompt_files = sorted([
                f for f in os.listdir(dict_dir)
                if f.lower().endswith('.json') and f not in [
                    'system_prompt_hq.json',
                    'system_prompt_line_break.json'
                ]
            ])
            return prompt_files
        except Exception as e:
            self.logger.error(f"Error scanning prompt directory: {e}")
            return []

    @pyqtSlot(str, str)
    def save_env_var(self, key: str, value: str):
        self.config_service.save_env_var(key, value)
        self.logger.info(f"Saved {key} to .env file.")

    # region 配置管理
    def load_config_file(self, config_path: str) -> bool:
        try:
            success = self.config_service.load_config_file(config_path)
            if success:
                config = self.config_service.get_config()
                self.state_manager.set_current_config(config)
                self.state_manager.set_state(AppStateKey.CONFIG_PATH, config_path)
                self.logger.info(f"配置文件加载成功: {config_path}")
                self.config_loaded.emit(config.dict())
                if config.app.last_output_path:
                    self.output_path_updated.emit(config.app.last_output_path)
                return True
            else:
                self.logger.error(f"配置文件加载失败: {config_path}")
                return False
        except Exception as e:
            self.logger.error(f"加载配置文件异常: {e}")
            return False
    
    def save_config_file(self, config_path: str = None) -> bool:
        try:
            success = self.config_service.save_config_file(config_path)
            if success:
                self.logger.info("配置文件保存成功")
                return True
            return False
        except Exception as e:
            self.logger.error(f"保存配置文件异常: {e}")
            return False
    
    def update_config(self, config_updates: Dict[str, Any]) -> bool:
        try:
            self.config_service.update_config(config_updates)
            updated_config = self.config_service.get_config()
            self.state_manager.set_current_config(updated_config)
            self.logger.info("配置更新成功")
            return True
        except Exception as e:
            self.logger.error(f"更新配置异常: {e}")
            return False

    def update_single_config(self, full_key: str, value: Any):
        self.logger.info(f"--- DIAGNOSTIC_KEY: update_single_config called with key: '{full_key}', value: '{value}'")
        try:
            config_obj = self.config_service.get_config()
            keys = full_key.split('.')
            parent_obj = config_obj
            for key in keys[:-1]:
                parent_obj = getattr(parent_obj, key)
            setattr(parent_obj, keys[-1], value)
            self.config_service.set_config(config_obj)
            self.config_service.save_config_file()
            self.logger.info(f"Saved '{full_key}' = '{value}' to config.")

            # 当翻译器设置被更改时，直接更新翻译服务的内部状态
            if full_key == 'translator.translator':
                self.logger.info(f"Translator has been changed to '{value}'. Updating translation service state.")
                self.translation_service.set_translator(value)

            # 当渲染设置被更改时，通知编辑器刷新
            if full_key.startswith('render.'):
                self.logger.info(f"Render setting '{full_key}' changed. Emitting signal.")
                self.render_setting_changed.emit()

        except Exception as e:
            self.logger.error(f"Error saving single config change for {full_key}: {e}")
    # endregion

    # region UI数据提供
    def get_display_mapping(self, key: str) -> Optional[Dict[str, str]]:
        if not hasattr(self, 'display_name_maps') or self.display_name_maps is None:
            self.display_name_maps = {
                "alignment": {"auto": "自动", "left": "左对齐", "center": "居中", "right": "右对齐"},
                "direction": {"auto": "自动", "h": "横排", "v": "竖排"},
                "layout_mode": {
                    'default': "默认模式 (有Bug)",
                    'smart_scaling': "智能缩放 (推荐)",
                    'strict': "严格边界 (缩小字体)",
                    'fixed_font': "固定字体 (扩大文本框)",
                    'disable_all': "完全禁用 (裁剪文本)"
                },
                "translator": {
                    "youdao": "有道翻译", "baidu": "百度翻译", "deepl": "DeepL", "papago": "Papago",
                    "caiyun": "彩云小译", "openai": "OpenAI",
                    "none": "无", "original": "原文", "sakura": "Sakura",
                    "groq": "Groq", "gemini": "Google Gemini",
                    "openai_hq": "高质量翻译 OpenAI", "gemini_hq": "高质量翻译 Gemini",
                    "offline": "离线翻译", "nllb": "NLLB", "nllb_big": "NLLB (Big)", "sugoi": "Sugoi",
                    "jparacrawl": "JParaCrawl", "jparacrawl_big": "JParaCrawl (Big)", "m2m100": "M2M100",
                    "m2m100_big": "M2M100 (Big)", "mbart50": "mBART50", "qwen2": "Qwen2", "qwen2_big": "Qwen2 (Big)",
                },
                "target_lang": self.translation_service.get_target_languages(),
                "labels": {
                    "filter_text": "过滤文本 (Regex)", "kernel_size": "卷积核大小", "mask_dilation_offset": "遮罩扩张偏移",
                    "translator": "翻译器", "target_lang": "目标语言", "no_text_lang_skip": "不跳过目标语言文本",
                    "gpt_config": "GPT配置文件路径", "high_quality_prompt_path": "高质量翻译提示词", "use_mocr_merge": "使用MOCR合并",
                    "ocr": "OCR模型", "use_hybrid_ocr": "启用混合OCR", "secondary_ocr": "备用OCR",
                    "min_text_length": "最小文本长度", "ignore_bubble": "忽略非气泡文本", "prob": "文本区域最低概率 (prob)",
                    "merge_gamma": "合并-距离容忍度", "merge_sigma": "合并-离群容忍度", "detector": "文本检测器",
                    "detection_size": "检测大小", "text_threshold": "文本阈值", "det_rotate": "旋转图像进行检测",
                    "det_auto_rotate": "旋转图像以优先检测垂直文本行", "det_invert": "反转图像颜色进行检测",
                    "det_gamma_correct": "应用伽马校正进行检测", "box_threshold": "边界框生成阈值", "unclip_ratio": "Unclip比例",
                    "inpainter": "修复模型", "inpainting_size": "修复大小", "inpainting_precision": "修复精度",
                    "renderer": "渲染器", "alignment": "对齐方式", "disable_font_border": "禁用字体边框",
                    "disable_auto_wrap": "AI断句", "font_size_offset": "字体大小偏移量", "font_size_minimum": "最小字体大小",
                    "max_font_size": "最大字体大小", "font_scale_ratio": "字体缩放比例",
                    "center_text_in_bubble": "AI断句时文本居中",
                    "direction": "文本方向", "uppercase": "大写", "lowercase": "小写", "gimp_font": "GIMP字体",
                    "font_path": "字体路径", "no_hyphenation": "禁用连字符", "font_color": "字体颜色",
                    "auto_rotate_symbols": "竖排内横排", "rtl": "从右到左", "layout_mode": "排版模式",
                    "upscaler": "超分模型", "revert_upscaling": "还原超分", "colorization_size": "上色大小",
                    "denoise_sigma": "降噪强度", "colorizer": "上色模型", "verbose": "详细日志",
                    "attempts": "重试次数", "ignore_errors": "忽略错误", "use_gpu": "使用 GPU",
                    "use_gpu_limited": "使用 GPU（受限）", "context_size": "上下文页数", "format": "输出格式",
                    "overwrite": "覆盖已存在文件", "skip_no_text": "跳过无文本图像", "use_mtpe": "启用后期编辑(MTPE)",
                    "save_text": "图片可编辑", "load_text": "导入翻译", "template": "导出原文",
                    "prep_manual": "为手动排版做准备", "save_quality": "图像保存质量", "batch_size": "批量大小",
                    "batch_concurrent": "并发批量处理", "generate_and_export": "导出翻译", "high_quality_batch_size": "高质量批次大小",
                    "last_output_path": "最后输出路径", "line_spacing": "行间距", "font_size": "字体大小",
                    "YOUDAO_APP_KEY": "有道翻译应用ID", "YOUDAO_SECRET_KEY": "有道翻译应用秘钥",
                    "BAIDU_APP_ID": "百度翻译 AppID", "BAIDU_SECRET_KEY": "百度翻译密钥",
                    "DEEPL_AUTH_KEY": "DeepL 授权密钥", "CAIYUN_TOKEN": "彩云小译 API 令牌",
                    "OPENAI_API_KEY": "OpenAI API 密钥", "OPENAI_MODEL": "OpenAI 模型",
                    "OPENAI_API_BASE": "OpenAI API 地址", "OPENAI_HTTP_PROXY": "HTTP 代理", "OPENAI_GLOSSARY_PATH": "术语表路径",
                    "DEEPSEEK_API_KEY": "DeepSeek API 密钥", "DEEPSEEK_API_BASE": "DeepSeek API 地址", "DEEPSEEK_MODEL": "DeepSeek 模型",
                    "GROQ_API_KEY": "Groq API 密钥", "GROQ_MODEL": "Groq 模型",
                    "GEMINI_API_KEY": "Gemini API 密钥", "GEMINI_MODEL": "Gemini 模型", "GEMINI_API_BASE": "Gemini API 地址",
                    "SAKURA_API_BASE": "SAKURA API 地址", "SAKURA_DICT_PATH": "SAKURA 词典路径", "SAKURA_VERSION": "SAKURA API 版本",
                    "CUSTOM_OPENAI_API_BASE": "自定义 OpenAI API 地址", "CUSTOM_OPENAI_MODEL": "自定义 OpenAI 模型",
                    "CUSTOM_OPENAI_API_KEY": "自定义 OpenAI API 密钥", "CUSTOM_OPENAI_MODEL_CONF": "自定义 OpenAI 模型配置"
                }
            }
        return self.display_name_maps.get(key)

    def get_options_for_key(self, key: str) -> Optional[List[str]]:
        options_map = {
            "format": ["不指定"] + list(OUTPUT_FORMATS.keys()),
            "renderer": [member.value for member in Renderer],
            "alignment": [member.value for member in Alignment],
            "direction": [member.value for member in Direction],
            "upscaler": [member.value for member in Upscaler],
            "translator": [member.value for member in Translator],
            "detector": [member.value for member in Detector],
            "colorizer": [member.value for member in Colorizer],
            "inpainter": [member.value for member in Inpainter],
            "inpainting_precision": [member.value for member in InpaintPrecision],
            "ocr": [member.value for member in Ocr],
            "secondary_ocr": [member.value for member in Ocr]
        }
        return options_map.get(key)
    # endregion

    # region 文件管理
    def add_files(self, file_paths: List[str]):
        """
        Adds files/folders to the list for processing.
        """
        new_paths = []
        for path in file_paths:
            norm_path = os.path.normpath(path)
            if norm_path not in self.source_files:
                new_paths.append(norm_path)

        if new_paths:
            self.source_files.extend(new_paths)
            self.logger.info(f"Added {len(new_paths)} files/folders to the list.")
            self.files_added.emit(new_paths)

    def get_last_open_dir(self) -> str:
        path = self.config_service.get_config().app.last_open_dir
        self.logger.info(f"Retrieved last open directory: {path}")
        return path

    def set_last_open_dir(self, path: str):
        self.logger.info(f"Saving last open directory: {path}")
        self.update_single_config('app.last_open_dir', path)

    def add_folder(self):
        """Opens a dialog to select a folder and adds its path to the list."""
        last_dir = self.get_last_open_dir()
        folder = QFileDialog.getExistingDirectory(None, "选择文件夹", last_dir)
        if folder:
            self.set_last_open_dir(folder)
            self.add_files([folder])

    def remove_file(self, file_path: str):
        try:
            norm_file_path = os.path.normpath(file_path)
            if norm_file_path in self.source_files:
                self.source_files.remove(norm_file_path)
                self.file_removed.emit(file_path)
                self.logger.info(f"Removed path {os.path.basename(file_path)} from list.")
            else:
                self.logger.warning(f"Path not found in list for removal: {file_path}")
        except Exception as e:
            self.logger.error(f"移除路径时发生异常: {e}")

    def clear_file_list(self):
        if not self.source_files:
            return
        # TODO: Add confirmation dialog
        self.source_files.clear()
        self.file_to_folder_map.clear()  # 清空文件夹映射
        self.files_cleared.emit()
        self.logger.info("File list cleared by user.")
    # endregion

    # region 核心任务逻辑
    def _resolve_input_files(self) -> List[str]:
        """
        Expands folders in self.source_files into a list of image files.
        同时记录文件和文件夹的映射关系。
        """
        resolved_files = []
        self.file_to_folder_map.clear()  # 清空旧的映射

        for path in self.source_files:
            if os.path.isdir(path):
                # 获取文件夹中的所有图片
                folder_files = self.file_service.get_image_files_from_folder(path, recursive=True)
                resolved_files.extend(folder_files)
                # 记录这些文件来自这个文件夹
                for file_path in folder_files:
                    self.file_to_folder_map[file_path] = path
            elif os.path.isfile(path):
                if self.file_service.validate_image_file(path):
                    resolved_files.append(path)
                    # 单独添加的文件，不属于任何文件夹
                    self.file_to_folder_map[path] = None

        return list(dict.fromkeys(resolved_files)) # Return unique files

    def start_backend_task(self):
        """
        Resolves input paths and uses a 'Worker-to-Thread' model to start the translation task.
        """
        if self.thread is not None and self.thread.isRunning():
            self.logger.warning("一个任务已经在运行中。")
            return

        files_to_process = self._resolve_input_files()
        if not files_to_process:
            self.logger.warning("没有找到有效的图片文件，任务中止")
            return

        self.saved_files_count = 0
        self.thread = QThread()
        self.worker = TranslationWorker(
            files=files_to_process,
            config_dict=self.config_service.get_config().dict(),
            output_folder=self.config_service.get_config().app.last_output_path,
            root_dir=self.config_service.root_dir,
            file_to_folder_map=self.file_to_folder_map.copy()  # 传递文件到文件夹的映射
        )
        
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.process)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.finished.connect(self.on_task_finished)
        self.worker.error.connect(self.on_task_error)
        self.worker.progress.connect(self.on_task_progress)
        self.worker.log_received.connect(self.on_worker_log)
        self.worker.file_processed.connect(self.on_file_completed)

        self.thread.start()
        self.logger.info("翻译工作线程已启动。")
        self.state_manager.set_translating(True)
        self.state_manager.set_status_message("正在翻译...")

    def on_task_finished(self, results):
        """处理任务完成信号，并根据需要保存批量任务的结果"""
        print("--- MainAppLogic: Slot on_task_finished triggered.")
        saved_files = []
        # The `results` list will only contain items from a batch job now.
        # Sequential jobs handle saving in `on_file_completed`.
        if results:
            self.logger.info(f"批量翻译任务完成，收到 {len(results)} 个结果。正在保存...")
            try:
                config = self.config_service.get_config()
                output_format = config.cli.format
                save_quality = config.cli.save_quality
                output_folder = config.app.last_output_path

                if not output_folder:
                    self.logger.error("输出目录未设置，无法保存文件。")
                    self.state_manager.set_status_message("错误：输出目录未设置！")
                else:
                    for result in results:
                        if result.get('success'):
                            # In batch mode, image_data is None because the backend already saved the file.
                            # We just need to acknowledge it.
                            if result.get('image_data') is None:
                                # 构造翻译后的图片路径
                                original_path = result.get('original_path')
                                source_folder = self.file_to_folder_map.get(original_path)

                                if source_folder:
                                    # 文件来自文件夹
                                    folder_name = os.path.basename(source_folder)
                                    final_output_folder = os.path.join(output_folder, folder_name)
                                    translated_file = os.path.join(final_output_folder, os.path.basename(original_path))
                                else:
                                    # 单独添加的文件
                                    translated_file = os.path.join(output_folder, os.path.basename(original_path))

                                # 规范化路径，避免混合斜杠
                                translated_file = os.path.normpath(translated_file)
                                saved_files.append(translated_file)
                                self.logger.info(f"确认由后端批量保存的文件: {original_path}")
                            else:
                                # This handles cases where a result with image_data is present in a batch
                                try:
                                    base_filename = os.path.splitext(os.path.basename(result['original_path']))[0]
                                    file_extension = f".{output_format}" if output_format and output_format != "不指定" else ".png"
                                    output_filename = f"{base_filename}_translated{file_extension}"
                                    final_output_path = os.path.join(output_folder, output_filename)
                                    os.makedirs(output_folder, exist_ok=True)
                                    
                                    save_kwargs = {}
                                    image_to_save = result['image_data']

                                    # Convert RGBA to RGB for JPEG format
                                    if file_extension in ['.jpg', '.jpeg']:
                                        if image_to_save.mode == 'RGBA':
                                            image_to_save = image_to_save.convert('RGB')
                                        save_kwargs['quality'] = save_quality
                                    elif file_extension == '.webp':
                                        save_kwargs['quality'] = save_quality

                                    image_to_save.save(final_output_path, **save_kwargs)
                                    saved_files.append(final_output_path)
                                    self.logger.info(f"成功保存文件: {final_output_path}")
                                except Exception as e:
                                    self.logger.error(f"保存文件 {result['original_path']} 时出错: {e}")
                
                # In batch mode, the saved_files_count is the length of this list
                self.saved_files_count = len(saved_files)

            except Exception as e:
                self.logger.error(f"处理批量任务结果时发生严重错误: {e}")

        # This part runs for both sequential and batch modes
        self.logger.info(f"翻译任务完成。总共成功处理 {self.saved_files_count} 个文件。")
        try:
            print("--- DEBUG: on_task_finished step 1: Setting translating state to False.")
            self.state_manager.set_translating(False)
            print("--- DEBUG: on_task_finished step 2: Setting status message.")
            self.state_manager.set_status_message(f"任务完成，成功处理 {self.saved_files_count} 个文件。")
            print("--- DEBUG: on_task_finished step 3: Emitting task_completed signal.")
            self.task_completed.emit(saved_files)
            print("--- DEBUG: on_task_finished step 4: Signal emitted successfully.")
        except Exception as e:
            self.logger.error(f"完成任务状态更新或信号发射时发生致命错误: {e}", exc_info=True)
        finally:
            print("--- DEBUG: on_task_finished step 5: Entering finally block.")
            self.thread = None
            self.worker = None
            print("--- MainAppLogic: Slot on_task_finished finished.")

    def on_task_error(self, error_message):
        print("--- MainAppLogic: Slot on_task_error triggered.")
        self.logger.error(f"翻译任务发生错误: {error_message}")
        self.state_manager.set_translating(False)
        self.state_manager.set_status_message(f"任务失败: {error_message}")
        self.thread = None
        self.worker = None
        print("--- MainAppLogic: Slot on_task_error finished.")

    def on_task_progress(self, current, total, message):
        self.logger.info(f"[进度] {current}/{total}: {message}")
        percentage = (current / total) * 100 if total > 0 else 0
        self.state_manager.set_translation_progress(percentage)
        self.state_manager.set_status_message(f"[{current}/{total}] {message}")

    def stop_task(self) -> bool:
        if self.thread and self.thread.isRunning():
            self.logger.info("正在请求停止翻译线程...")

            # 立即更新UI状态：设置为非翻译状态，显示"停止中"
            self.state_manager.set_translating(False)
            self.state_manager.set_status_message("正在停止翻译...")

            if self.worker:
                self.worker.stop()
            self.thread.quit()

            # 保存线程引用，避免在等待过程中被清空
            thread_ref = self.thread

            # 在后台等待线程停止，不阻塞UI
            from PyQt6.QtCore import QTimer
            def wait_for_thread():
                try:
                    if thread_ref and not thread_ref.wait(100):  # 等待100ms
                        # 如果还没停止，继续等待
                        QTimer.singleShot(100, wait_for_thread)
                    else:
                        # 线程已停止
                        self.logger.info("翻译线程已成功停止。")
                        self.state_manager.set_status_message("任务已停止")
                except RuntimeError:
                    # 线程对象已被删除，认为已停止
                    self.logger.info("翻译线程已停止（对象已删除）。")
                    self.state_manager.set_status_message("任务已停止")

            # 启动非阻塞等待
            QTimer.singleShot(0, wait_for_thread)

            # 立即返回，不等待线程停止
            return True
        self.logger.warning("请求停止任务，但没有正在运行的线程。")
        return False
    # endregion

    # region 应用生命周期
    def initialize(self) -> bool:
        try:
            # The config is already loaded at startup. We just need to ensure the UI
            # reflects the loaded state without triggering a full, blocking rebuild.
            
            # Get the already loaded config
            config = self.config_service.get_config()

            # Manually emit the signal to populate UI options
            self.config_loaded.emit(config.dict())

            # Manually emit the signal to update the output path display in the UI
            if config.app.last_output_path:
                self.output_path_updated.emit(config.app.last_output_path)
            
            # Ensure the config path is stored in the state manager
            default_config_path = self.config_service.get_default_config_path()
            if os.path.exists(default_config_path):
                self.state_manager.set_state(AppStateKey.CONFIG_PATH, default_config_path)

            self.state_manager.set_app_ready(True)
            self.state_manager.set_status_message("就绪")
            self.logger.info("应用初始化完成")
            return True
        except Exception as e:
            self.logger.error(f"应用初始化异常: {e}")
            return False
    
    def shutdown(self):
        try:
            if self.state_manager.is_translating():
                self.stop_task()
            if self.translation_service:
                pass
            self.logger.info("应用正常关闭")
        except Exception as e:
            self.logger.error(f"应用关闭异常: {e}")
    # endregion

class QtLogHandler(logging.Handler):
    def __init__(self, signal):
        super().__init__()
        self.signal = signal

    def emit(self, record):
        msg = self.format(record)
        self.signal.emit(msg)

class TranslationWorker(QObject):
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int, str)
    log_received = pyqtSignal(str)
    file_processed = pyqtSignal(dict)

    def __init__(self, files, config_dict, output_folder, root_dir, file_to_folder_map=None):
        super().__init__()
        self.files = files
        self.config_dict = config_dict
        self.output_folder = output_folder
        self.root_dir = root_dir
        self.file_to_folder_map = file_to_folder_map or {}  # 文件到文件夹的映射
        self._is_running = True
        self._current_task = None  # 保存当前运行的异步任务

    def stop(self):
        self.log_received.emit("--- Stop request received.")
        self._is_running = False
        # 取消当前运行的异步任务
        if self._current_task and not self._current_task.done():
            self._current_task.cancel()

    async def _do_processing(self):
        log_handler = QtLogHandler(self.log_received)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        log_handler.setFormatter(formatter)
        manga_logger = logging.getLogger('manga_translator')
        manga_logger.addHandler(log_handler)
        manga_logger.setLevel(logging.INFO)

        results = []
        try:
            from manga_translator.config import (
                ColorizerConfig,
                Config,
                DetectorConfig,
                InpainterConfig,
                OcrConfig,
                RenderConfig,
                Translator,
                TranslatorConfig,
                UpscaleConfig,
            )
            from manga_translator.manga_translator import MangaTranslator
            from PIL import Image

            self.log_received.emit("--- [9] THREAD: Initializing translator...")
            translator_params = self.config_dict.get('cli', {})
            translator_params.update(self.config_dict)
            translator_params['is_ui_mode'] = True
            
            font_filename = self.config_dict.get('render', {}).get('font_path')
            if font_filename:
                font_full_path = os.path.join(self.root_dir, 'fonts', font_filename)
                if os.path.exists(font_full_path):
                    translator_params['font_path'] = font_full_path

            translator = MangaTranslator(params=translator_params)
            self.log_received.emit("--- [10] THREAD: Translator initialized.")

            explicit_keys = {'render', 'upscale', 'translator', 'detector', 'colorizer', 'inpainter', 'ocr'}
            remaining_config = {
                k: v for k, v in self.config_dict.items() 
                if k in Config.__fields__ and k not in explicit_keys
            }

            render_config_data = self.config_dict.get('render', {})

            translator_config_data = self.config_dict.get('translator', {}).copy()
            hq_prompt_path = translator_config_data.get('high_quality_prompt_path')
            if hq_prompt_path and not os.path.isabs(hq_prompt_path):
                full_prompt_path = os.path.join(self.root_dir, hq_prompt_path)
                if os.path.exists(full_prompt_path):
                    translator_config_data['high_quality_prompt_path'] = full_prompt_path
                else:
                    self.log_received.emit(f"--- WARNING: High quality prompt file not found at {full_prompt_path}")

            config = Config(
                render=RenderConfig(**render_config_data),
                upscale=UpscaleConfig(**self.config_dict.get('upscale', {})),
                translator=TranslatorConfig(**translator_config_data),
                detector=DetectorConfig(**self.config_dict.get('detector', {})),
                colorizer=ColorizerConfig(**self.config_dict.get('colorizer', {})),
                inpainter=InpainterConfig(**self.config_dict.get('inpainter', {})),
                ocr=OcrConfig(**self.config_dict.get('ocr', {})),
                **remaining_config
            )
            self.log_received.emit("--- [11] THREAD: Config object created correctly.")

            translator_type = config.translator.translator
            is_hq = translator_type in [Translator.openai_hq, Translator.gemini_hq]
            batch_size = self.config_dict.get('cli', {}).get('batch_size', 1)

            # 准备save_info（所有模式都需要）
            output_format = self.config_dict.get('cli', {}).get('format')
            if not output_format or output_format == "不指定":
                output_format = None # Set to None to preserve original extension

            # 收集输入文件夹列表（从file_to_folder_map中获取）
            input_folders = set()
            for file_path in self.files:
                folder = self.file_to_folder_map.get(file_path)
                if folder:
                    input_folders.add(os.path.normpath(folder))

            save_info = {
                'output_folder': self.output_folder,
                'format': output_format,
                'overwrite': self.config_dict.get('cli', {}).get('overwrite', True),
                'input_folders': input_folders
            }

            if is_hq or (len(self.files) > 1 and batch_size > 1):
                self.log_received.emit(f"--- [12] THREAD: Starting batch processing ({'HQ mode' if is_hq else 'Batch mode'})...")

                images_with_configs = []
                for file_path in self.files:
                    if not self._is_running: raise asyncio.CancelledError("Task stopped by user.")
                    self.progress.emit(len(images_with_configs), len(self.files), f"Loading for batch: {os.path.basename(file_path)}")
                    image = Image.open(file_path)
                    image.name = file_path
                    images_with_configs.append((image, config))

                contexts = await translator.translate_batch(images_with_configs, save_info=save_info)

                # The backend now handles saving for batch jobs. We just need to collect the paths/status.
                for ctx in contexts:
                    if not self._is_running: raise asyncio.CancelledError("Task stopped by user.")
                    if ctx:
                        results.append({'success': True, 'original_path': ctx.image_name, 'image_data': None})
                    else:
                        results.append({'success': False, 'original_path': 'Unknown', 'error': 'Batch translation returned no context'})

            else: 
                self.log_received.emit("--- [12] THREAD: Starting sequential processing...")
                total_files = len(self.files)
                for i, file_path in enumerate(self.files):
                    if not self._is_running:
                        raise asyncio.CancelledError("Task stopped by user.")

                    self.progress.emit(i, total_files, f"Processing: {os.path.basename(file_path)}")
                    
                    try:
                        image = Image.open(file_path)
                        image.name = file_path
                        
                        ctx = await translator.translate(image, config, image_name=image.name)
                        
                        if ctx and ctx.result:
                            self.file_processed.emit({'success': True, 'original_path': file_path, 'image_data': ctx.result})
                        else:
                            self.file_processed.emit({'success': False, 'original_path': file_path, 'error': 'Translation returned no result or image'})

                    except Exception as e:
                        self.log_received.emit(f"Error processing file {os.path.basename(file_path)}: {e}")
                        self.file_processed.emit({'success': False, 'original_path': file_path, 'error': str(e)})
            
            self.finished.emit(results)

        except asyncio.CancelledError as e:
            self.log_received.emit(f"Task cancelled: {e}")
            self.error.emit(str(e))
        except Exception as e:
            import traceback
            self.error.emit(f"{str(e)}\n{traceback.format_exc()}")
        finally:
            manga_logger.removeHandler(log_handler)

    @pyqtSlot()
    def process(self):
        try:
            import asyncio
            self.log_received.emit("--- [1] THREAD: process() method entered, starting asyncio task.")

            # 创建事件循环并保存任务引用
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self._current_task = loop.create_task(self._do_processing())
                loop.run_until_complete(self._current_task)
                self.log_received.emit("--- [END] THREAD: asyncio task finished.")
            except asyncio.CancelledError:
                self.log_received.emit("--- [CANCELLED] THREAD: asyncio task was cancelled.")
            finally:
                loop.close()
        except Exception as e:
            import traceback
            self.error.emit(f"An error occurred in the asyncio runner: {str(e)}\n{traceback.format_exc()}")
