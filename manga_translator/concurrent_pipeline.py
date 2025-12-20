"""
并发流水线处理模块
实现流水线并发：检测+OCR（顺序）→ 翻译线程（批量）+ 修复线程 + 渲染线程
使用线程池执行CPU/GPU密集型操作，避免阻塞事件循环
"""
import asyncio
import logging
import traceback
import os
from typing import List
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import functools

from .utils import Context, load_image

# 使用 manga_translator 的主 logger，确保日志能被UI捕获
logger = logging.getLogger('manga_translator')


class ConcurrentPipeline:
    """
    流水线并发处理器
    
    4个独立工作线程：
    1. 检测+OCR线程（顺序）→ 完成后放入翻译队列和修复队列
    2. 翻译线程（独立）→ 批量处理翻译队列
    3. 修复线程（独立）→ 处理修复队列
    4. 渲染线程（独立）→ 翻译+修复完成后渲染出图
    
    batch_size 控制翻译批量大小（一次翻译多少个文本块）
    """
    
    def __init__(self, translator_instance, batch_size: int = 3, max_workers: int = 4):
        """
        初始化并发流水线
        
        Args:
            translator_instance: MangaTranslator实例
            batch_size: 批量大小（一次翻译多少个文本块）
            max_workers: 线程池最大工作线程数（用于CPU/GPU密集型操作）
                        默认4个：检测+OCR、修复、渲染可以同时执行
        """
        self.translator = translator_instance
        self.batch_size = batch_size
        
        # 线程池：用于执行CPU/GPU密集型操作
        # 4个工作线程：允许检测、OCR、修复、渲染同时执行
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pipeline_worker")
        
        # 队列
        self.translation_queue = asyncio.Queue()  # 翻译队列
        self.inpaint_queue = asyncio.Queue()      # 修复队列
        self.render_queue = asyncio.Queue()       # 渲染队列
        
        # 结果存储 {image_name: ctx}
        # ✅ 存储完整的ctx对象，而不是True/False标记
        self.translation_done = {}  # 翻译完成的ctx（包含翻译后的text_regions）
        self.inpaint_done = {}      # 修复完成的ctx（包含img_inpainted）
        
        # ✅ 存储基础ctx（检测+OCR的结果），供翻译和修复使用
        self.base_contexts = {}     # {image_name: ctx}
        
        # 控制标志
        self.stop_workers = False
        self.detection_ocr_done = False  # 检测+OCR是否全部完成
        
        # 统计信息
        self.start_time = None
        self.total_images = 0
        self.stats = {
            'detection_ocr': 0,
            'translation': 0,
            'inpaint': 0,
            'rendering': 0
        }
    
    async def _detection_ocr_worker(self, file_paths: List[str], configs: List):
        """
        检测+OCR工作线程（顺序处理，分批加载图片）
        完成后将上下文放入翻译队列和修复队列
        """
        # 让出控制权，确保其他线程有机会启动
        await asyncio.sleep(0)
        
        logger.info(f"[检测+OCR线程] 开始处理 {len(file_paths)} 张图片（分批加载）")
        
        from PIL import Image
        
        for idx, (file_path, config) in enumerate(zip(file_paths, configs)):
            if self.stop_workers:
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
                
                # 预处理：加载图片、上色、超分
                ctx.img_rgb, ctx.img_alpha = load_image(image)
                
                if config.colorizer.colorizer.value != 'none':
                    colorized_result = await self.translator._run_colorizer(config, ctx)
                    # colorizer 返回 PIL Image，需要转换为 numpy
                    if hasattr(colorized_result, 'mode'):  # PIL Image
                        ctx.img_colorized, _ = load_image(colorized_result)
                    else:
                        ctx.img_colorized = colorized_result
                else:
                    ctx.img_colorized = ctx.img_rgb
                
                if config.upscale.upscale_ratio:
                    upscaled_result = await self.translator._run_upscaling(config, ctx)
                    # upscaler 返回 PIL Image，需要转换为 numpy
                    if hasattr(upscaled_result, 'mode'):  # PIL Image
                        ctx.upscaled, _ = load_image(upscaled_result)
                    else:
                        ctx.upscaled = upscaled_result
                else:
                    ctx.upscaled = ctx.img_colorized
                
                # 更新 img_rgb 为 upscaled 结果（现在都是 numpy.ndarray）
                ctx.img_rgb = ctx.upscaled
                
                # 检测（在线程池中执行，避免阻塞事件循环）
                loop = asyncio.get_event_loop()
                detection_func = functools.partial(
                    asyncio.run,
                    self.translator._run_detection(config, ctx)
                )
                ctx.textlines, ctx.mask_raw, ctx.mask = await loop.run_in_executor(
                    self.executor, detection_func
                )
                
                # OCR（在线程池中执行）
                ocr_func = functools.partial(
                    asyncio.run,
                    self.translator._run_ocr(config, ctx)
                )
                ctx.textlines = await loop.run_in_executor(
                    self.executor, ocr_func
                )
                
                # 文本行合并
                if ctx.textlines:
                    ctx.text_regions = await self.translator._run_textline_merge(config, ctx)
                
                self.stats['detection_ocr'] += 1
                logger.info(f"[检测+OCR] 完成 {idx+1}/{self.total_images}: {ctx.image_name} "
                           f"({len(ctx.text_regions) if ctx.text_regions else 0} 个文本块)")
                
                # 保存图片尺寸（用于保存JSON）
                if hasattr(image, 'size'):
                    ctx.original_size = image.size
                
                # ✅ 保留原始图片数据用于渲染（resize_regions_to_font_size需要original_img）
                # 注意：不关闭image对象，因为dump_image和渲染都需要使用它
                ctx.input = image  # 保留原始输入供dump_image使用
                # ✅ 保留img_rgb用于渲染时的original_img参数（balloon_fill等布局模式需要）
                # ctx.img_rgb 会在渲染完成后由渲染函数自动清理
                
                # ✅ 保存基础ctx，供后续合并使用
                self.base_contexts[ctx.image_name] = ctx
                
                # 放入翻译队列和修复队列（只传image_name和config，不传ctx）
                if ctx.text_regions:
                    await self.translation_queue.put((ctx.image_name, config))
                    await self.inpaint_queue.put((ctx.image_name, config))
                    logger.info(f"[检测+OCR] {ctx.image_name} 已加入翻译队列和修复队列 (翻译队列大小: {self.translation_queue.qsize()})")
                    # 让出控制权，让其他线程有机会运行
                    await asyncio.sleep(0)
                else:
                    # 无文本，直接标记完成并放入渲染队列
                    self.translation_done[ctx.image_name] = ctx
                    self.inpaint_done[ctx.image_name] = ctx
                    ctx.result = ctx.upscaled
                    await self.render_queue.put((ctx, config))
                    logger.debug(f"[检测+OCR] {ctx.image_name} 无文本，直接进入渲染队列")
                
            except Exception as e:
                logger.error(f"[检测+OCR] 失败: {e}")
                logger.error(traceback.format_exc())
        
        # 标记检测+OCR全部完成
        self.detection_ocr_done = True
        logger.info("[检测+OCR线程] 处理完成")
    
    async def _translation_worker(self):
        """
        翻译工作线程（批量处理，串行执行）
        从翻译队列中取出文本，批量翻译
        一批翻译完成后才开始下一批
        """
        # 让出控制权，确保线程能被调度
        await asyncio.sleep(0)
        
        logger.info(f"[翻译线程] 启动，批量大小: {self.batch_size}")
        
        batch = []
        
        while not self.stop_workers:
            try:
                # 尝试从队列获取图片（非阻塞检查）
                try:
                    image_name, config = await asyncio.wait_for(self.translation_queue.get(), timeout=0.1)
                    # ✅ 从base_contexts获取ctx
                    ctx = self.base_contexts.get(image_name)
                    if ctx:
                        batch.append((ctx, config))
                    else:
                        logger.error(f"[翻译] 找不到 {image_name} 的基础上下文")
                except asyncio.TimeoutError:
                    # 队列暂时为空
                    if not batch:
                        # 批次为空，检查是否所有工作都完成了
                        if self.detection_ocr_done and self.translation_queue.empty():
                            break
                        continue
                
                # 已有图片，继续快速收集更多图片直到达到batch_size
                while len(batch) < self.batch_size:
                    try:
                        image_name, config = await asyncio.wait_for(self.translation_queue.get(), timeout=0.05)
                        # ✅ 从base_contexts获取ctx
                        ctx = self.base_contexts.get(image_name)
                        if ctx:
                            batch.append((ctx, config))
                        else:
                            logger.error(f"[翻译] 找不到 {image_name} 的基础上下文")
                    except asyncio.TimeoutError:
                        break
                
                # 判断是否应该翻译当前批次
                should_translate = False
                reason = ""
                
                if len(batch) >= self.batch_size:
                    # 达到批量大小，立即翻译
                    should_translate = True
                    reason = f"批次已满 ({len(batch)}/{self.batch_size})"
                elif batch and self.detection_ocr_done:
                    # OCR完成了，立即翻译剩余批次
                    should_translate = True
                    reason = f"OCR完成，翻译剩余 {len(batch)} 张图片"
                
                if should_translate:
                    logger.info(f"[翻译] {reason}，开始翻译")
                    # 串行执行：等待当前批次翻译完成后才继续
                    await self._process_translation_batch(batch)
                    batch = []
                
            except Exception as e:
                logger.error(f"[翻译线程] 错误: {e}")
                logger.error(traceback.format_exc())
        
        # 处理剩余批次
        if batch:
            logger.info(f"[翻译] 翻译剩余 {len(batch)} 张图片")
            await self._process_translation_batch(batch)
        
        # 检查是否所有图片都已翻译
        if self.stats['translation'] >= self.total_images:
            logger.info(f"[翻译线程] 所有图片已翻译 ({self.stats['translation']}/{self.total_images})")
        
        logger.info("[翻译线程] 停止")
    
    async def _process_translation_batch(self, batch: List[tuple]):
        """
        处理一个翻译批次
        
        直接复用 MangaTranslator._batch_translate_contexts 的翻译逻辑，
        确保与标准批量处理完全一致，便于维护。
        """
        if not batch:
            return
        
        logger.info(f"[翻译] 批量翻译 {len(batch)} 张图片")
        
        try:
            # ✅ 直接调用标准的批量翻译方法，复用所有翻译逻辑
            # 包括：翻译、后处理、过滤、译后检查等
            translated_batch = await self.translator._batch_translate_contexts(batch, len(batch))
            
            self.stats['translation'] += len(batch)
            logger.info(f"[翻译] 批次完成 ({self.stats['translation']}/{self.total_images})")
            
            # 更新翻译结果到batch（_batch_translate_contexts可能修改了text_regions）
            # 标记翻译完成，并立即逐张检查是否可以渲染
            ready_to_render = 0
            for ctx, config in translated_batch:
                # ✅ 保存翻译后的text_regions 到 translation_done
                self.translation_done[ctx.image_name] = ctx.text_regions
                
                # ✅ 同步更新 base_contexts（因为 _apply_post_translation_processing 可能替换了 text_regions 列表）
                if ctx.image_name in self.base_contexts:
                    self.base_contexts[ctx.image_name].text_regions = ctx.text_regions
                
                # 立即检查：如果修复也完成了，立即放入渲染队列
                if ctx.image_name in self.inpaint_done:
                    await self.render_queue.put((ctx, config))
                    ready_to_render += 1
                    logger.info(f"[翻译] {ctx.image_name} 翻译+修复都完成，立即加入渲染队列")
            
            if ready_to_render > 0:
                logger.info(f"[翻译] 批次中 {ready_to_render}/{len(batch)} 张图片立即加入渲染队列")
            else:
                logger.debug(f"[翻译] 批次中 0/{len(batch)} 张图片完成修复，等待修复完成后加入渲染队列")
            
        except Exception as e:
            logger.error(f"[翻译] 批次失败: {e}")
            logger.error(traceback.format_exc())
            # 标记所有上下文为失败
            for ctx, config in batch:
                ctx.translation_error = str(e)
                self.translation_done[ctx.image_name] = True
    
    async def _inpaint_worker(self):
        """
        修复工作线程
        从修复队列中取出上下文，进行修复
        """
        # 让出控制权，确保线程能被调度
        await asyncio.sleep(0)
        
        logger.info("[修复线程] 启动")
        
        inpaint_count = 0
        
        while not self.stop_workers:
            try:
                # 尝试获取任务（超时1秒）
                try:
                    image_name, config = await asyncio.wait_for(self.inpaint_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # ✅ 从base_contexts获取ctx
                ctx = self.base_contexts.get(image_name)
                if not ctx:
                    logger.error(f"[修复] 找不到 {image_name} 的基础上下文")
                    continue
                
                logger.info(f"[修复] 处理: {ctx.image_name}")
                
                # Mask refinement（在线程池中执行）
                if ctx.mask is None and ctx.text_regions:
                    loop = asyncio.get_event_loop()
                    mask_func = functools.partial(
                        asyncio.run,
                        self.translator._run_mask_refinement(config, ctx)
                    )
                    ctx.mask = await loop.run_in_executor(self.executor, mask_func)
                
                # Inpainting（在线程池中执行）
                if ctx.text_regions:
                    loop = asyncio.get_event_loop()
                    inpaint_func = functools.partial(
                        asyncio.run,
                        self.translator._run_inpainting(config, ctx)
                    )
                    ctx.img_inpainted = await loop.run_in_executor(self.executor, inpaint_func)
                
                self.stats['inpaint'] += 1
                inpaint_count += 1
                logger.info(f"[修复] 完成: {ctx.image_name} ({self.stats['inpaint']}/{self.total_images})")
                
                # ✅ 标记修复完成（img_inpainted已经设置到base_contexts中的ctx了）
                self.inpaint_done[ctx.image_name] = True
                
                # 如果翻译也完成了，放入渲染队列
                if ctx.image_name in self.translation_done:
                    # ✅ 从base_contexts获取完整的ctx，合并翻译和修复结果
                    render_ctx = self.base_contexts.get(ctx.image_name)
                    if render_ctx:
                        # 使用翻译后的text_regions
                        translated_regions = self.translation_done.get(ctx.image_name)
                        if translated_regions:
                            render_ctx.text_regions = translated_regions
                        # img_inpainted已经在上面设置好了
                        await self.render_queue.put((render_ctx, config))
                        logger.info(f"[修复] {ctx.image_name} 翻译+修复都完成，加入渲染队列")
                    else:
                        logger.error(f"[修复] 找不到 {ctx.image_name} 的基础上下文")
                
                # 检查是否完成所有任务
                if inpaint_count >= self.total_images:
                    break
                
            except Exception as e:
                logger.error(f"[修复线程] 错误: {e}")
                logger.error(traceback.format_exc())
        
        logger.info("[修复线程] 停止")
    
    async def _render_worker(self, results: List[Context]):
        """
        渲染工作线程
        从渲染队列中取出上下文，进行渲染
        渲染完成后立即清理内存
        """
        # 让出控制权，确保线程能被调度
        await asyncio.sleep(0)
        
        logger.info("[渲染线程] 启动")
        
        rendered_count = 0
        
        while not self.stop_workers or rendered_count < self.total_images:
            try:
                # 尝试获取任务（超时1秒）
                try:
                    ctx, config = await asyncio.wait_for(self.render_queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    # 超时，检查是否还有任务
                    if rendered_count >= self.total_images:
                        break
                    continue
                
                logger.info(f"[渲染] 从队列获取任务: {ctx.image_name} (队列剩余: {self.render_queue.qsize()})")
                
                # ✅ 验证：确保ctx是正确的（通过image_name匹配）
                # 从base_contexts重新获取，确保使用最新的数据
                verified_ctx = self.base_contexts.get(ctx.image_name)
                if not verified_ctx:
                    logger.error(f"[渲染] 找不到 {ctx.image_name} 的基础上下文，跳过")
                    continue
                
                # 使用验证后的ctx
                ctx = verified_ctx
                logger.info(f"[渲染] 开始处理: {ctx.image_name}")
                
                # ✅ 检查渲染所需的数据是否完整
                if not hasattr(ctx, 'img_rgb') or ctx.img_rgb is None:
                    logger.error("[渲染] ctx.img_rgb 为 None，无法渲染！跳过此图片")
                    ctx.translation_error = "渲染失败：缺少原始图片数据"
                    continue
                
                # 调试：检查关键数据
                logger.debug(f"[渲染调试] img_rgb shape: {ctx.img_rgb.shape if hasattr(ctx, 'img_rgb') and ctx.img_rgb is not None else 'None'}")
                logger.debug(f"[渲染调试] img_inpainted shape: {ctx.img_inpainted.shape if hasattr(ctx, 'img_inpainted') and ctx.img_inpainted is not None else 'None'}")
                logger.debug(f"[渲染调试] text_regions count: {len(ctx.text_regions) if ctx.text_regions else 0}")
                if ctx.text_regions:
                    for i, region in enumerate(ctx.text_regions[:3]):  # 只显示前3个
                        logger.debug(f"[渲染调试] Region {i}: translation='{region.translation[:30]}...', font_size={region.font_size}, xywh={region.xywh}")
                
                if not ctx.text_regions:
                    # 无文本，直接使用upscaled
                    from .utils.generic import dump_image
                    ctx.result = dump_image(ctx.input, ctx.upscaled, ctx.img_alpha)
                else:
                    # 渲染（在线程池中执行）
                    # img_rgb和img_inpainted已经在修复阶段更新为upscaled版本
                    loop = asyncio.get_event_loop()
                    render_func = functools.partial(
                        asyncio.run,
                        self.translator._run_text_rendering(config, ctx)
                    )
                    ctx.img_rendered = await loop.run_in_executor(self.executor, render_func)
                    
                    # 使用dump_image合并alpha通道（与标准流程一致）
                    from .utils.generic import dump_image
                    ctx.result = dump_image(ctx.input, ctx.img_rendered, ctx.img_alpha)
                
                self.stats['rendering'] += 1
                rendered_count += 1
                logger.info(f"[渲染] 完成: {ctx.image_name} ({self.stats['rendering']}/{self.total_images})")
                
                # ✅ 每张图片渲染完成后发送进度更新（UI进度条适配）
                try:
                    await self.translator._report_progress(f"batch:1:{rendered_count}:{self.total_images}")
                except Exception as e:
                    logger.debug(f"[渲染] 进度报告失败（可忽略）: {e}")
                
                # 检查result是否存在
                if ctx.result is not None:
                    logger.info(f"[渲染] ctx.result 已设置，类型: {type(ctx.result)}")
                    
                    # 立即保存图片和JSON
                    try:
                        # 获取save_info（从translator获取）
                        if hasattr(self.translator, '_current_save_info') and self.translator._current_save_info:
                            save_info = self.translator._current_save_info
                            
                            # 保存图片（与主流程一致：不管是否保存成功都继续）
                            overwrite = save_info.get('overwrite', True)
                            final_output_path = self.translator._calculate_output_path(ctx.image_name, save_info)
                            self.translator._save_translated_image(ctx.result, final_output_path, ctx.image_name, overwrite, "CONCURRENT")
                            
                            # 保存JSON（如果需要）
                            if (self.translator.save_text or self.translator.text_output_file) and ctx.text_regions is not None:
                                self.translator._save_text_to_file(ctx.image_name, ctx, config)
                        else:
                            logger.warning("[渲染] 无save_info，跳过保存")
                        
                        # 标记成功（与主流程一致）
                        ctx.success = True
                                
                    except Exception as save_err:
                        logger.error(f"[渲染] 保存失败 {os.path.basename(ctx.image_name)}: {save_err}")
                        logger.error(traceback.format_exc())
                        ctx.translation_error = str(save_err)
                else:
                    logger.error("[渲染] ctx.result 为 None！")
                
                # 添加到结果列表
                results.append(ctx)
                
                # 渲染完成后立即清理内存（注意：_run_text_rendering 已经清理了 ctx.img_rgb）
                logger.debug(f"[渲染] 清理内存: {ctx.image_name}")
                # ctx.img_rgb 已在 _run_text_rendering 中清理
                if hasattr(ctx, 'img_rgb') and ctx.img_rgb is not None:
                    del ctx.img_rgb
                    ctx.img_rgb = None
                # 保留 ctx.img_alpha 用于dump_image
                if hasattr(ctx, 'img_colorized') and ctx.img_colorized is not None:
                    del ctx.img_colorized
                    ctx.img_colorized = None
                if hasattr(ctx, 'upscaled') and ctx.upscaled is not None:
                    del ctx.upscaled
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
                # 保留 ctx.result 和 ctx.img_alpha 用于保存
                
                # 强制垃圾回收
                import gc
                gc.collect()
                
                # ✅ 清理base_contexts中的ctx，释放内存
                if ctx.image_name in self.base_contexts:
                    del self.base_contexts[ctx.image_name]
                    logger.debug(f"[渲染] 已清理 {ctx.image_name} 的基础上下文")
                
            except Exception as e:
                logger.error(f"[渲染线程] 错误: {e}")
                logger.error(traceback.format_exc())
        
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
        logger.info(f"[并发流水线] 流水线模式: 检测+OCR（顺序，分批加载）→ 翻译线程（批量={self.batch_size}）+ 修复线程 + 渲染线程")
        
        # 重置统计
        for key in self.stats:
            self.stats[key] = 0
        self.translation_done.clear()
        self.inpaint_done.clear()
        self.base_contexts.clear()  # ✅ 清理基础上下文
        self.detection_ocr_done = False  # 重置标志
        
        # 结果列表
        results = []
        
        # 启动4个工作线程
        tasks = [
            asyncio.create_task(self._detection_ocr_worker(file_paths, configs)),
            asyncio.create_task(self._translation_worker()),
            asyncio.create_task(self._inpaint_worker()),
            asyncio.create_task(self._render_worker(results))
        ]
        
        try:
            # 等待所有任务完成
            await asyncio.gather(*tasks)
        except Exception as e:
            logger.error(f"[并发流水线] 错误: {e}")
            logger.error(traceback.format_exc())
            self.stop_workers = True
            raise
        finally:
            self.stop_workers = True
            # 关闭线程池
            self.executor.shutdown(wait=True)
        
        # 统计
        elapsed = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        logger.info("[并发流水线] 完成！")
        logger.info(f"  总耗时: {elapsed:.2f}秒")
        logger.info(f"  平均速度: {elapsed/self.total_images:.2f}秒/张")
        logger.info(f"  处理统计: 检测+OCR={self.stats['detection_ocr']}, "
                   f"翻译={self.stats['translation']}, 修复={self.stats['inpaint']}, "
                   f"渲染={self.stats['rendering']}")
        
        return results
