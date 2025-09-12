#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import json
import asyncio
import logging
from pathlib import Path

# 强制设置UTF-8编码
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)

# 强制刷新输出
def flush_print(text):
    try:
        print(text, flush=True)
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception as e:
        # 如果输出出错，尝试用ASCII输出
        try:
            print(str(text).encode('ascii', 'ignore').decode('ascii'), flush=True)
        except:
            pass

# 配置日志输出到stdout
def setup_logging():
    try:
        # 清除现有handlers
        logging.getLogger().handlers.clear()
        
        # 创建stdout handler
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        
        # 设置根logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.addHandler(handler)
        
        # 确保manga_translator的日志也输出
        manga_logger = logging.getLogger('manga_translator')
        manga_logger.setLevel(logging.INFO)
        manga_logger.addHandler(handler)
    except Exception as e:
        flush_print(f"设置日志时出错: {e}")

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    return os.path.join(base_path, relative_path)

def main():
    try:
        if len(sys.argv) != 2:
            flush_print("Usage: translation_worker.py <config_file>")
            sys.exit(1)
        
        config_file = sys.argv[1]
        flush_print(f"翻译工作进程启动，PID: {os.getpid()}")
        flush_print(f"配置文件: {config_file}")
        
        # 设置日志
        setup_logging()
        
        # 加载配置
        with open(config_file, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        
        config_dict = config_data['config_dict']
        input_files = config_data['input_files']
        output_folder = config_data['output_folder']
        
        flush_print(f"输入文件数: {len(input_files)}")
        flush_print(f"输出文件夹: {output_folder}")
        
        # 导入翻译相关模块
        flush_print("正在导入翻译模块...")
        try:
            from manga_translator.config import (
                Config, RenderConfig, UpscaleConfig, TranslatorConfig, DetectorConfig,
                ColorizerConfig, InpainterConfig, OcrConfig
            )
            from manga_translator.manga_translator import MangaTranslator
            from PIL import Image
            flush_print("翻译模块导入成功")
        except Exception as e:
            flush_print(f"导入翻译模块失败: {e}")
            import traceback
            flush_print(traceback.format_exc())
            return
        
        # 初始化翻译器
        translator_params = {}
        if 'cli' in config_dict:
            translator_params.update(config_dict.pop('cli'))
        
        # 提取字体路径并设置为翻译器参数
        render_config = config_dict.get('render', {})
        font_filename = render_config.get('font_path')
        if font_filename:
            # 构建完整的字体路径
            font_full_path = resource_path(os.path.join('fonts', font_filename))
            if os.path.exists(font_full_path):
                translator_params['font_path'] = font_full_path
                flush_print(f"设置翻译器字体路径: {font_full_path}")
            else:
                flush_print(f"警告: 字体文件不存在: {font_full_path}")
        
        translator_params.update(config_dict)
        translator_params['is_ui_mode'] = True
        
        flush_print("正在初始化翻译引擎...")
        try:
            translator = MangaTranslator(params=translator_params)
            flush_print("翻译引擎初始化完成")
        except Exception as e:
            flush_print(f"翻译引擎初始化失败: {e}")
            import traceback
            flush_print(traceback.format_exc())
            return
        
        # 解析输入文件
        flush_print("正在解析输入文件...")
        image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'}
        resolved_files = []
        
        for path in input_files:
            if os.path.isfile(path):
                _, ext = os.path.splitext(path.lower())
                if ext in image_extensions:
                    resolved_files.append(path)
            elif os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file in files:
                        _, ext = os.path.splitext(file.lower())
                        if ext in image_extensions:
                            resolved_files.append(os.path.join(root, file))
        
        if not resolved_files:
            flush_print("没有找到有效的图片文件")
            return
            
        flush_print(f"找到 {len(resolved_files)} 个图片文件")
        
        # 创建配置对象
        try:
            config = Config(
                render=RenderConfig(**config_dict.get('render', {})),
                upscale=UpscaleConfig(**config_dict.get('upscale', {})),
                translator=TranslatorConfig(**config_dict.get('translator', {})),
                detector=DetectorConfig(**config_dict.get('detector', {})),
                colorizer=ColorizerConfig(**config_dict.get('colorizer', {})),
                inpainter=InpainterConfig(**config_dict.get('inpainter', {})),
                ocr=OcrConfig(**config_dict.get('ocr', {}))
            )
            flush_print("配置对象创建成功")
        except Exception as e:
            flush_print(f"创建配置对象失败: {e}")
            import traceback
            flush_print(traceback.format_exc())
            return
        
        # Create the event loop ONCE
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Get the list of input folders to create subdirectories
        input_folders = {os.path.normpath(path) for path in input_files if os.path.isdir(path)}

        try:
            # 检查是否应该强制使用批量模式
            translator_type = config_dict.get('translator', {}).get('translator')
            is_hq = translator_type in ['openai_hq', 'gemini_hq']
            
            if len(resolved_files) > 1 or is_hq:
                flush_print(f"开始批量翻译 {len(resolved_files)} 个文件...")
                if is_hq and len(resolved_files) == 1:
                    flush_print("检测到高质量翻译器，强制使用批量模式处理单个文件...")
                
                images_with_configs = []
                for file_path in resolved_files:
                    image = Image.open(file_path)
                    image.name = file_path
                    images_with_configs.append((image, config))
                
                # 对于高质量/批量模式，传递保存信息以便在内部逐批保存
                save_info = {
                    "output_folder": output_folder,
                    "input_folders": input_folders,
                }
                
                # 此函数现在将在内部处理保存，并返回最终的上下文列表
                results = loop.run_until_complete(translator.translate_batch(images_with_configs, save_info=save_info))
                flush_print(f"所有批次处理和保存完成。")
            else:
                flush_print(f"开始单文件模式翻译 {len(resolved_files)} 个文件...")
                for i, file_path in enumerate(resolved_files):
                    flush_print(f"\n=== [{i+1}/{len(resolved_files)}] 处理文件: {os.path.basename(file_path)} ===")

                    try:
                        # 加载图片
                        flush_print(f"  -> 加载图片: {os.path.basename(file_path)}")
                        image = Image.open(file_path)
                        image.name = file_path
                        flush_print(f"  -> 图片尺寸: {image.size}")
                        
                        flush_print(f"  -> 开始翻译处理...")
                        
                        # 异步翻译
                        ctx = loop.run_until_complete(translator.translate(image, config, image_name=image.name))
                        
                        cli_params = config_dict.get('cli', {})
                        save_text_mode = cli_params.get('save_text', False)
                        task_successful = (ctx and ctx.result) or (ctx and save_text_mode and ctx.result is None)

                        if task_successful:
                            if ctx.result:
                                final_output_dir = output_folder
                                parent_dir = os.path.normpath(os.path.dirname(file_path))
                                for folder in input_folders:
                                    if parent_dir.startswith(folder):
                                        final_output_dir = os.path.join(output_folder, os.path.basename(folder))
                                        break
                                
                                os.makedirs(final_output_dir, exist_ok=True)
                                output_filename = os.path.basename(file_path)
                                final_output_path = os.path.join(final_output_dir, output_filename)
                                
                                image_to_save = ctx.result
                                if final_output_path.lower().endswith(('.jpg', '.jpeg')) and image_to_save.mode in ('RGBA', 'LA'):
                                    image_to_save = image_to_save.convert('RGB')
                                
                                image_to_save.save(final_output_path)
                                flush_print(f"  -> ✅ 翻译完成: {os.path.basename(final_output_path)}")
                            else:
                                flush_print(f"  -> ✅ 文本导出成功: {os.path.basename(file_path)}")
                            
                            if hasattr(ctx, 'text_regions') and ctx.text_regions:
                                flush_print(f"  -> 识别到 {len(ctx.text_regions)} 个文本区域")
                                for j, region in enumerate(ctx.text_regions[:3]):
                                    text = getattr(region, 'text', '') or getattr(region, 'translation', '')
                                    if text:
                                        flush_print(f"     区域{j+1}: {text[:50]}{'...' if len(text) > 50 else ''}")
                        else:
                            flush_print(f"  -> ❌ 翻译失败: {os.path.basename(file_path)}")
                            
                    except Exception as e:
                        flush_print(f"  -> ❌ 处理文件时出错 {os.path.basename(file_path)}: {e}")
                        import traceback
                        flush_print(traceback.format_exc())
        finally:
            loop.close()
        
        flush_print("\n=== 翻译进程完成 ===")
        
    except Exception as e:
        flush_print(f"翻译工作进程出错: {e}")
        import traceback
        flush_print(traceback.format_exc())
        sys.exit(1)
    finally:
        # 清理临时文件
        try:
            if 'config_file' in locals() and os.path.exists(config_file):
                os.remove(config_file)
                flush_print(f"已清理临时配置文件: {config_file}")
        except Exception as e:
            flush_print(f"清理临时文件出错: {e}")


if __name__ == '__main__':
    main()