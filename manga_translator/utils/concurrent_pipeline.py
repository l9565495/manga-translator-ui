"""
并发流水线处理模块 - 真正的并行架构
实现流水线并发：检测+OCR、翻译、修复、渲染 四个步骤在独立线程中运行
每个线程拥有独立的事件循环，互不阻塞
"""
import asyncio
import logging
import traceback
import os
import queue
import threading
from typing import List
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, wait

from . import Context, load_image

# 使用 manga_translator 的主 logger，确保日志能被UI捕获
logger = logging.getLogger('manga_translator')


class ConcurrentPipeline:
    """
    流水线并发处理器 - 真正的并行架构
    
    4个独立线程，每个拥有自己的事件循环，互不阻塞：
    1. 检测+OCR线程 → 完成后放入翻译队列和修复队列
    2. 翻译线程 → 批量处理翻译队列（HTTP 请求不会被 GPU 操作阻塞）
    3. 修复线程 → 处理修复队列（GPU 推理不会阻塞翻译）
    4. 渲染线程 → 翻译+修复完成后渲染出图
    
    batch_size 控制翻译批量大小（一次翻译多少个文本块）
    
    使用 queue.Queue 和 threading.Lock 进行线程间通信和同步。
    """
    
    def __init__(self, translator_instance, batch_size: int = 3, max_workers: int = 4):
        """
        初始化并发流水线
        
        Args:
            translator_instance: MangaTranslator实例
            batch_size: 批量大小（一次翻译多少个文本块）
            max_workers: 每个步骤的线程池大小
        """
        self.translator = translator_instance
        self.batch_size = batch_size
        
        # ✅ 为每个步骤创建独立的线程池，实现真正的并行处理
        # 每个线程拥有独立的事件循环，互不阻塞
        self._detection_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='DetectionThread')
        self._translation_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='TranslationThread')
        self._inpaint_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='InpaintThread')
        self._render_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='RenderThread')
        
        # 线程安全的队列
        self.translation_queue = queue.Queue()  # 翻译队列
        self.inpaint_queue = queue.Queue()      # 修复队列
        self.render_queue = queue.Queue()       # 渲染队列
        
        # 结果存储 {image_name: ctx}
        # 使用线程锁保护共享数据
        self._lock = threading.Lock()
        self.translation_done = {}  # 翻译完成的ctx（包含翻译后的text_regions）
        self.inpaint_done = {}      # 修复完成的ctx（包含img_inpainted）
        
        # 存储基础ctx（检测+OCR的结果），供翻译和修复使用
        self.base_contexts = {}     # {image_name: ctx}
        
        # 控制标志
        self.stop_workers = False
        self.detection_ocr_done = False  # 检测+OCR是否全部完成
        self.has_critical_error = False  # 是否发生严重错误
        self.critical_error_msg = None   # 严重错误信息
        self.critical_error_exception = None  # 原始异常对象
        
        # 统计信息
        self.start_time = None
        self.total_images = 0
        self.stats = {
            'detection_ocr': 0,
            'translation': 0,
            'inpaint': 0,
            'rendering': 0
        }
        
        # 结果列表（线程安全）
        self._results = []
        self._results_lock = threading.Lock()
        
        # ✅ 线程安全的状态消息队列（用于向主线程报告关键日志）
        self._status_queue = queue.Queue()
    
    def _emit_status(self, message: str):
        """向主线程发送状态消息（线程安全）"""
        self._status_queue.put(message)
    
    def _flush_status_to_logger(self):
        """将队列中的状态消息输出到 logger（在主线程调用）"""
        while not self._status_queue.empty():
            try:
                msg = self._status_queue.get_nowait()
                logger.info(msg)
            except queue.Empty:
                break
    
    def _run_async_in_thread(self, coro):
        """在当前线程中创建事件循环并运行协程"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
    
    def _detection_ocr_thread(self, file_paths: List[str], configs: List):
        """
        检测+OCR工作线程（在独立线程中运行）
        完成后将上下文放入翻译队列和修复队列
        """
        self._emit_status("[检测+OCR] 线程启动")
        try:
            self._run_async_in_thread(self._detection_ocr_async(file_paths, configs))
        finally:
            self._emit_status(f"[检测+OCR] 线程完成 ({self.stats['detection_ocr']}/{self.total_images})")
    
    async def _detection_ocr_async(self, file_paths: List[str], configs: List):
        """检测+OCR的异步实现"""
        try:
            self.translator._check_cancelled()
        except:
            pass
        
        logger.info(f"[检测+OCR线程] 开始处理 {len(file_paths)} 张图片（分批加载）")
        
        from PIL import Image
        
        for idx, (file_path, config) in enumerate(zip(file_paths, configs)):
            try:
                self.translator._check_cancelled()
            except:
                pass
            
            # 检查是否需要停止（其他线程出错）
            if self.stop_workers:
                logger.warning(f"[检测+OCR] 收到停止信号，已处理 {idx}/{len(file_paths)} 张图片")
                break
            
            try:
                # 分批加载：只在需要时加载图片
                logger.debug(f"[检测+OCR] 加载图片: {file_path}")
                with open(file_path, 'rb') as f:
                    image = Image.open(f)
                    image.load()  # 立即加载图片数据
                image.name = file_path
                
                # 创建上下文
                ctx = Context()
                ctx.input = image
                ctx.image_name = file_path
                ctx.verbose = self.translator.verbose
                ctx.save_quality = self.translator.save_quality
                ctx.config = config
                
                logger.info(f"[检测+OCR] 处理 {idx+1}/{self.total_images}: {ctx.image_name}")
                
                # 检查取消
                try:
                    self.translator._check_cancelled()
                except:
                    self.stop_workers = True
                    logger.warning(f"[检测+OCR] 用户取消，已处理 {idx}/{len(file_paths)} 张图片")
                    break
                
                # 预处理：上色、超分
                if config.colorizer.colorizer.value != 'none':
                    ctx.img_colorized = await self.translator._run_colorizer(config, ctx)
                else:
                    ctx.img_colorized = ctx.input

                # 检查取消
                try:
                    self.translator._check_cancelled()
                except:
                    self.stop_workers = True
                    logger.warning(f"[检测+OCR] 用户取消，已处理 {idx}/{len(file_paths)} 张图片")
                    break

                if config.upscale.upscale_ratio:
                    ctx.upscaled = await self.translator._run_upscaling(config, ctx)
                else:
                    ctx.upscaled = ctx.img_colorized

                # 统一转换为 numpy
                ctx.img_rgb, ctx.img_alpha = load_image(ctx.upscaled)
                
                # 检查取消
                try:
                    self.translator._check_cancelled()
                except:
                    self.stop_workers = True
                    logger.warning(f"[检测+OCR] 用户取消，已处理 {idx}/{len(file_paths)} 张图片")
                    break
                
                # 检测
                ctx.textlines, ctx.mask_raw, ctx.mask = await self.translator._run_detection(config, ctx)
                
                # 检查取消
                try:
                    self.translator._check_cancelled()
                except:
                    self.stop_workers = True
                    logger.warning(f"[检测+OCR] 用户取消，已处理 {idx}/{len(file_paths)} 张图片")
                    break
                
                # OCR
                ctx.textlines = await self.translator._run_ocr(config, ctx)
                
                # 检查取消
                try:
                    self.translator._check_cancelled()
                except:
                    self.stop_workers = True
                    logger.warning(f"[检测+OCR] 用户取消，已处理 {idx}/{len(file_paths)} 张图片")
                    break
                
                # 文本行合并
                if ctx.textlines:
                    ctx.text_regions = await self.translator._run_textline_merge(config, ctx)
                
                self.stats['detection_ocr'] += 1
                # ✅ 发送状态日志（每完成一张图）
                text_count = len(ctx.text_regions) if ctx.text_regions else 0
                self._emit_status(f"[检测+OCR] 完成 {idx+1}/{self.total_images}: {os.path.basename(file_path)} ({text_count} 个文本块)")
                
                # 保存图片尺寸
                if hasattr(image, 'size'):
                    ctx.original_size = image.size
                
                ctx.input = image
                
                # 保存基础ctx
                with self._lock:
                    self.base_contexts[ctx.image_name] = ctx
                
                # 放入翻译队列和修复队列
                if ctx.text_regions:
                    self.translation_queue.put((ctx.image_name, config))
                    self.inpaint_queue.put((ctx.image_name, config))
                    logger.info(f"[检测+OCR] {ctx.image_name} 已加入翻译队列和修复队列 (翻译队列大小: {self.translation_queue.qsize()})")
                else:
                    # 无文本，直接标记完成并放入渲染队列
                    with self._lock:
                        self.translation_done[ctx.image_name] = []
                        self.inpaint_done[ctx.image_name] = True
                    ctx.text_regions = []
                    self.render_queue.put((ctx, config))
                    logger.debug(f"[检测+OCR] {ctx.image_name} 无文本，直接进入渲染队列")
                
            except Exception as e:
                try:
                    error_msg = str(e)
                except Exception:
                    error_msg = f"无法获取异常信息 (异常类型: {type(e).__name__})"
                
                logger.error(f"[检测+OCR] 失败: {error_msg}")
                logger.error(traceback.format_exc())
                self.has_critical_error = True
                self.critical_error_msg = f"检测+OCR失败: {error_msg}"
                self.critical_error_exception = e
                self.stop_workers = True
                break
        
        # 标记检测+OCR全部完成
        self.detection_ocr_done = True
        logger.info("[检测+OCR线程] 处理完成")
    
    def _translation_thread(self):
        """翻译工作线程（在独立线程中运行）"""
        self._emit_status("[翻译] 线程启动")
        try:
            self._run_async_in_thread(self._translation_async())
        finally:
            self._emit_status(f"[翻译] 线程完成 ({self.stats['translation']}/{self.total_images})")
    
    async def _translation_async(self):
        """翻译的异步实现"""
        try:
            self.translator._check_cancelled()
        except:
            pass
        
        logger.info(f"[翻译线程] 启动，批量大小: {self.batch_size}")
        
        batch = []
        
        while not self.stop_workers:
            try:
                if self.has_critical_error:
                    logger.warning(f"[翻译] 检测到严重错误，停止翻译 (已完成 {self.stats['translation']}/{self.total_images})")
                    break
                
                # 从队列获取任务（非阻塞）
                try:
                    image_name, config = self.translation_queue.get(timeout=0.1)
                    with self._lock:
                        ctx = self.base_contexts.get(image_name)
                    if ctx:
                        batch.append((ctx, config))
                    else:
                        logger.error(f"[翻译] 找不到 {image_name} 的基础上下文")
                except queue.Empty:
                    if not batch:
                        if self.detection_ocr_done and self.translation_queue.empty():
                            break
                        if self.has_critical_error:
                            logger.warning("[翻译] 检测到严重错误，停止等待")
                            break
                        continue
                
                # 收集更多图片直到达到batch_size
                while len(batch) < self.batch_size:
                    try:
                        image_name, config = self.translation_queue.get(timeout=0.05)
                        with self._lock:
                            ctx = self.base_contexts.get(image_name)
                        if ctx:
                            batch.append((ctx, config))
                        else:
                            logger.error(f"[翻译] 找不到 {image_name} 的基础上下文")
                    except queue.Empty:
                        break
                
                # 判断是否应该翻译当前批次
                should_translate = False
                reason = ""
                
                if len(batch) >= self.batch_size:
                    should_translate = True
                    reason = f"批次已满 ({len(batch)}/{self.batch_size})"
                elif batch and self.detection_ocr_done:
                    should_translate = True
                    reason = f"OCR完成，翻译剩余 {len(batch)} 张图片"
                
                if should_translate:
                    logger.info(f"[翻译] {reason}，开始翻译")
                    await self._process_translation_batch(batch)
                    batch = []
                
            except Exception as e:
                try:
                    error_msg = str(e)
                except Exception:
                    error_msg = f"无法获取异常信息 (异常类型: {type(e).__name__})"
                
                logger.error(f"[翻译线程] 错误: {error_msg}")
                logger.error(traceback.format_exc())
                self.has_critical_error = True
                self.critical_error_msg = f"翻译线程错误: {error_msg}"
                self.critical_error_exception = e
                self.stop_workers = True
                break
        
        # 处理剩余批次
        if batch and not self.stop_workers:
            logger.info(f"[翻译] 翻译剩余 {len(batch)} 张图片")
            await self._process_translation_batch(batch)
        
        if self.stats['translation'] >= self.total_images:
            logger.info(f"[翻译线程] 所有图片已翻译 ({self.stats['translation']}/{self.total_images})")
        
        logger.info("[翻译线程] 停止")
    
    async def _process_translation_batch(self, batch: List[tuple]):
        """处理一个翻译批次"""
        if not batch:
            return
        
        logger.info(f"[翻译] 批量翻译 {len(batch)} 张图片")
        
        try:
            # 直接调用翻译（已经在独立线程的事件循环中）
            translated_batch = await self.translator._batch_translate_contexts(batch, len(batch))
            
            self.stats['translation'] += len(batch)
            # ✅ 发送状态日志
            self._emit_status(f"[翻译] 批次完成 ({self.stats['translation']}/{self.total_images})")
            
            ready_to_render = 0
            for ctx, config in translated_batch:
                with self._lock:
                    self.translation_done[ctx.image_name] = ctx.text_regions
                    if ctx.image_name in self.base_contexts:
                        self.base_contexts[ctx.image_name].text_regions = ctx.text_regions
                    
                    # 检查修复是否也完成
                    if ctx.image_name in self.inpaint_done:
                        self.render_queue.put((ctx, config))
                        ready_to_render += 1
                        logger.info(f"[翻译] {ctx.image_name} 翻译+修复都完成，立即加入渲染队列")
            
            if ready_to_render > 0:
                logger.info(f"[翻译] 批次中 {ready_to_render}/{len(batch)} 张图片立即加入渲染队列")
            else:
                logger.debug(f"[翻译] 批次中 0/{len(batch)} 张图片完成修复，等待修复完成后加入渲染队列")
            
        except Exception as e:
            try:
                error_msg = str(e)
            except Exception as str_error:
                error_msg = f"无法获取异常信息 (转换错误: {type(str_error).__name__})"
                logger.error(f"[翻译] 异常转换失败: {str_error}")
            
            logger.error(f"[翻译] 批次失败: {error_msg}")
            logger.error(f"[翻译] 异常类型: {type(e).__name__}")
            logger.error(traceback.format_exc())
            
            self.has_critical_error = True
            self.critical_error_msg = f"翻译批次失败: {error_msg}"
            self.critical_error_exception = e
            self.stop_workers = True
            
            for ctx, config in batch:
                ctx.translation_error = error_msg
                with self._lock:
                    self.translation_done[ctx.image_name] = []
                ctx.text_regions = []
    
    def _inpaint_thread(self):
        """修复工作线程（在独立线程中运行）"""
        self._emit_status("[修复] 线程启动")
        try:
            self._run_async_in_thread(self._inpaint_async())
        finally:
            self._emit_status(f"[修复] 线程完成 ({self.stats['inpaint']}/{self.total_images})")
    
    async def _inpaint_async(self):
        """修复的异步实现"""
        try:
            self.translator._check_cancelled()
        except:
            pass
        
        logger.info("[修复线程] 启动")
        
        inpaint_count = 0
        
        while not self.stop_workers:
            try:
                if self.has_critical_error:
                    logger.warning(f"[修复] 检测到严重错误，停止修复 (已完成 {inpaint_count}/{self.total_images})")
                    break
                
                # 检查是否完成所有任务
                if self.detection_ocr_done and self.inpaint_queue.empty():
                    import time
                    time.sleep(0.5)
                    if self.inpaint_queue.empty():
                        logger.info(f"[修复线程] 所有任务已完成 ({inpaint_count}/{self.total_images})")
                        break
                
                # 尝试获取任务
                try:
                    image_name, config = self.inpaint_queue.get(timeout=1.0)
                except queue.Empty:
                    if self.has_critical_error:
                        logger.warning("[修复] 检测到严重错误，停止等待")
                        break
                    continue
                
                with self._lock:
                    ctx = self.base_contexts.get(image_name)
                if not ctx:
                    logger.error(f"[修复] 找不到 {image_name} 的基础上下文")
                    continue
                
                logger.info(f"[修复] 处理: {ctx.image_name}")
                
                # Mask refinement
                if ctx.mask is None and ctx.text_regions:
                    ctx.mask = await self.translator._run_mask_refinement(config, ctx)
                
                # Inpainting
                if ctx.text_regions:
                    ctx.img_inpainted = await self.translator._run_inpainting(config, ctx)
                
                self.stats['inpaint'] += 1
                inpaint_count += 1
                # ✅ 发送状态日志
                self._emit_status(f"[修复] 完成 {inpaint_count}/{self.total_images}: {os.path.basename(ctx.image_name)}")
                
                # 标记修复完成
                with self._lock:
                    self.inpaint_done[ctx.image_name] = True
                    
                    # 如果翻译也完成了，放入渲染队列
                    if ctx.image_name in self.translation_done:
                        render_ctx = self.base_contexts.get(ctx.image_name)
                        if render_ctx:
                            translated_regions = self.translation_done.get(ctx.image_name)
                            if isinstance(translated_regions, (list, tuple)):
                                render_ctx.text_regions = translated_regions
                            elif translated_regions:
                                logger.warning(f"[修复] {ctx.image_name} 的翻译结果类型异常: {type(translated_regions)}, 使用空列表")
                                render_ctx.text_regions = []
                            else:
                                render_ctx.text_regions = []
                            self.render_queue.put((render_ctx, config))
                            logger.info(f"[修复] {ctx.image_name} 翻译+修复都完成，加入渲染队列")
                        else:
                            logger.error(f"[修复] 找不到 {ctx.image_name} 的基础上下文")
                
            except Exception as e:
                try:
                    error_msg = str(e)
                except Exception:
                    error_msg = f"无法获取异常信息 (异常类型: {type(e).__name__})"
                
                logger.error(f"[修复线程] 错误: {error_msg}")
                logger.error(traceback.format_exc())
                self.has_critical_error = True
                self.critical_error_msg = f"修复线程错误: {error_msg}"
                self.critical_error_exception = e
                self.stop_workers = True
                break
        
        logger.info("[修复线程] 停止")
    
    def _render_thread(self):
        """渲染工作线程（在独立线程中运行）"""
        self._emit_status("[渲染] 线程启动")
        try:
            self._run_async_in_thread(self._render_async())
        finally:
            self._emit_status(f"[渲染] 线程完成 ({self.stats['rendering']}/{self.total_images})")
    
    async def _render_async(self):
        """渲染的异步实现"""
        try:
            self.translator._check_cancelled()
        except:
            pass
        
        logger.info("[渲染线程] 启动")
        
        rendered_count = 0
        
        while not self.stop_workers or rendered_count < self.total_images:
            try:
                if self.has_critical_error:
                    logger.warning(f"[渲染] 检测到严重错误，停止渲染 (已完成 {rendered_count}/{self.total_images})")
                    break
                
                # 尝试获取任务
                try:
                    ctx, config = self.render_queue.get(timeout=1.0)
                except queue.Empty:
                    # 检查是否应该退出
                    if self.stop_workers:
                        logger.info(f"[渲染] 收到停止信号，已渲染 {rendered_count}/{self.total_images} 张图片")
                        break
                    if rendered_count >= self.total_images:
                        break
                    if self.has_critical_error:
                        logger.warning("[渲染] 检测到严重错误，停止等待")
                        break
                    continue
                
                logger.info(f"[渲染] 从队列获取任务: {ctx.image_name} (队列剩余: {self.render_queue.qsize()})")
                
                # 验证ctx
                with self._lock:
                    verified_ctx = self.base_contexts.get(ctx.image_name)
                if not verified_ctx:
                    logger.error(f"[渲染] 找不到 {ctx.image_name} 的基础上下文，跳过")
                    continue
                
                ctx = verified_ctx
                logger.info(f"[渲染] 开始处理: {ctx.image_name}")
                
                # 检查渲染所需的数据是否完整
                if not hasattr(ctx, 'img_rgb') or ctx.img_rgb is None:
                    logger.error("[渲染] ctx.img_rgb 为 None，无法渲染！跳过此图片")
                    ctx.translation_error = "渲染失败：缺少原始图片数据"
                    continue
                
                # 备份修复后图片
                img_inpainted_copy = None
                if (self.translator.save_text or self.translator.text_output_file) and hasattr(ctx, 'img_inpainted') and ctx.img_inpainted is not None:
                    import numpy as np
                    img_inpainted_copy = np.copy(ctx.img_inpainted)
                    logger.debug("[渲染] 已备份修复后图片用于保存")
                
                if not ctx.text_regions:
                    from .generic import dump_image
                    ctx.result = dump_image(ctx.input, ctx.img_rgb, ctx.img_alpha)
                else:
                    ctx.img_rendered = await self.translator._run_text_rendering(config, ctx)
                    from .generic import dump_image
                    ctx.result = dump_image(ctx.input, ctx.img_rendered, ctx.img_alpha)
                
                self.stats['rendering'] += 1
                rendered_count += 1
                
                # ✅ 发送状态日志（每完成一张图）
                self._emit_status(f"[渲染] 完成 {rendered_count}/{self.total_images}: {os.path.basename(ctx.image_name)}")
                
                # 保存
                if ctx.result is not None:
                    logger.info(f"[渲染] ctx.result 已设置，类型: {type(ctx.result)}")
                    
                    try:
                        if hasattr(self.translator, '_current_save_info') and self.translator._current_save_info:
                            save_info = self.translator._current_save_info
                            
                            # ✅ 先保存修复图（在PSD导出之前），这样PSD导出时可以找到修复图文件
                            if img_inpainted_copy is not None:
                                try:
                                    from .path_manager import get_inpainted_path
                                    from .generic import imwrite_unicode
                                    import cv2
                                    
                                    inpainted_path = get_inpainted_path(ctx.image_name, create_dir=True)
                                    imwrite_unicode(inpainted_path, cv2.cvtColor(img_inpainted_copy, cv2.COLOR_RGB2BGR), logger)
                                    logger.info(f"[渲染] 修复后图片已保存: {inpainted_path}")
                                except Exception as e:
                                    logger.error(f"[渲染] 保存修复后图片失败: {e}")
                                finally:
                                    del img_inpainted_copy
                                    img_inpainted_copy = None
                            
                            # 保存翻译结果和导出PSD
                            self.translator._save_and_cleanup_context(ctx, save_info, config, "CONCURRENT")
                            
                            if (self.translator.save_text or self.translator.text_output_file) and ctx.text_regions is not None:
                                self.translator._save_text_to_file(ctx.image_name, ctx, config)
                        else:
                            logger.warning("[渲染] 无save_info，跳过保存")
                        
                        ctx.success = True
                                
                    except Exception as save_err:
                        logger.error(f"[渲染] 保存失败 {os.path.basename(ctx.image_name)}: {save_err}")
                        logger.error(traceback.format_exc())
                        ctx.translation_error = str(save_err)
                else:
                    logger.error("[渲染] ctx.result 为 None！")
                
                # 添加到结果列表
                with self._results_lock:
                    self._results.append(ctx)
                
                # 清理内存
                logger.debug(f"[渲染] 清理内存: {ctx.image_name}")
                if hasattr(ctx, 'input') and ctx.input is not None:
                    if hasattr(ctx.input, 'close'):
                        try:
                            ctx.input.close()
                        except:
                            pass
                    ctx.input = None
                if hasattr(ctx, 'img_rgb') and ctx.img_rgb is not None:
                    del ctx.img_rgb
                    ctx.img_rgb = None
                if hasattr(ctx, 'img_colorized') and ctx.img_colorized is not None:
                    if hasattr(ctx.img_colorized, 'close'):
                        try:
                            ctx.img_colorized.close()
                        except:
                            pass
                    ctx.img_colorized = None
                if hasattr(ctx, 'upscaled') and ctx.upscaled is not None:
                    if hasattr(ctx.upscaled, 'close'):
                        try:
                            ctx.upscaled.close()
                        except:
                            pass
                    ctx.upscaled = None
                if hasattr(ctx, 'mask') and ctx.mask is not None:
                    del ctx.mask
                    ctx.mask = None
                if hasattr(ctx, 'img_inpainted') and ctx.img_inpainted is not None:
                    del ctx.img_inpainted
                    ctx.img_inpainted = None
                if hasattr(ctx, 'img_rendered') and ctx.img_rendered is not None:
                    del ctx.img_rendered
                    ctx.img_rendered = None
                
                # 垃圾回收
                import gc
                gc.collect()
                
                # 清理base_contexts
                with self._lock:
                    if ctx.image_name in self.base_contexts:
                        del self.base_contexts[ctx.image_name]
                        logger.debug(f"[渲染] 已清理 {ctx.image_name} 的基础上下文")
                
            except Exception as e:
                try:
                    error_msg = str(e)
                except Exception:
                    error_msg = f"无法获取异常信息 (异常类型: {type(e).__name__})"
                
                logger.error(f"[渲染线程] 错误: {error_msg}")
                logger.error(traceback.format_exc())
                self.has_critical_error = True
                self.critical_error_msg = f"渲染线程错误: {error_msg}"
                self.critical_error_exception = e
                self.stop_workers = True
                break
        
        logger.info("[渲染线程] 停止")
    
    async def process_batch(self, file_paths: List[str], configs: List) -> List[Context]:
        """
        并发处理一批图片（流水线模式，分批加载）
        
        Args:
            file_paths: 图片文件路径列表
            configs: 配置列表
            
        Returns:
            处理完成的Context列表
        """
        self.total_images = len(file_paths)
        self.start_time = datetime.now(timezone.utc)
        
        logger.info(f"[并发流水线] 开始处理 {self.total_images} 张图片")
        logger.info(f"[并发流水线] 真正并行模式: 4个独立线程（检测+OCR / 翻译 / 修复 / 渲染）")
        
        # 重置统计
        for key in self.stats:
            self.stats[key] = 0
        self.translation_done.clear()
        self.inpaint_done.clear()
        self.base_contexts.clear()
        self.detection_ocr_done = False
        self.stop_workers = False
        self.has_critical_error = False
        self.critical_error_msg = None
        self.critical_error_exception = None
        self._results = []
        
        # 提交4个独立线程任务
        futures = [
            self._detection_executor.submit(self._detection_ocr_thread, file_paths, configs),
            self._translation_executor.submit(self._translation_thread),
            self._inpaint_executor.submit(self._inpaint_thread),
            self._render_executor.submit(self._render_thread),
        ]
        
        try:
            # 等待所有线程完成（在外部循环中检查以便响应取消）
            last_rendered = 0
            while True:
                done, not_done = wait(futures, timeout=0.5)
                
                # ✅ 刷新子线程的状态日志到主线程
                self._flush_status_to_logger()
                
                # ✅ 报告进度（如果渲染数有变化）
                current_rendered = self.stats['rendering']
                if current_rendered > last_rendered:
                    try:
                        await self.translator._report_progress(f"batch:1:{current_rendered}:{self.total_images}")
                    except Exception:
                        pass
                    last_rendered = current_rendered
                
                if len(not_done) == 0:
                    break
                # 检查是否有异常
                for f in done:
                    if f.exception():
                        raise f.exception()
                # 让出控制权，检查取消
                await asyncio.sleep(0)
                
        except asyncio.CancelledError:
            # 用户取消了任务
            logger.warning(f"[并发流水线] 用户取消任务")
            self.stop_workers = True
            # 等待所有线程停止（最多等待10秒）
            logger.info("[并发流水线] 等待所有线程停止...")
            done, not_done = wait(futures, timeout=10.0)
            if not_done:
                # 显示哪些线程没有停止
                thread_names = []
                for i, future in enumerate(futures):
                    if future in not_done:
                        names = ["检测+OCR", "翻译", "修复", "渲染"]
                        thread_names.append(names[i])
                logger.warning(f"[并发流水线] {len(not_done)} 个线程未能在10秒内停止: {', '.join(thread_names)}")
            else:
                logger.info("[并发流水线] 所有线程已停止")
            raise
        except Exception as e:
            logger.error(f"[并发流水线] 错误: {e}")
            logger.error(traceback.format_exc())
            self.stop_workers = True
            raise
        finally:
            self.stop_workers = True
            # 关闭所有线程池
            for executor in [self._detection_executor, self._translation_executor, 
                           self._inpaint_executor, self._render_executor]:
                if executor:
                    executor.shutdown(wait=False)
        
        # 检查是否有严重错误
        if self.has_critical_error:
            error_msg = self.critical_error_msg or "未知错误"
            logger.error(f"[并发流水线] 处理失败: {error_msg}")
            if self.critical_error_exception:
                raise self.critical_error_exception
            else:
                raise RuntimeError(f"并发流水线处理失败: {error_msg}")
        
        # 统计
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        logger.info("[并发流水线] 完成！")
        logger.info(f"  总耗时: {elapsed:.2f}秒")
        logger.info(f"  平均速度: {elapsed/self.total_images:.2f}秒/张")
        logger.info(f"  处理统计: 检测+OCR={self.stats['detection_ocr']}, "
                   f"翻译={self.stats['translation']}, 修复={self.stats['inpaint']}, "
                   f"渲染={self.stats['rendering']}")
        
        return self._results
