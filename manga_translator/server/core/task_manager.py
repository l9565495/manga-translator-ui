"""
任务管理模块

负责并发控制、活动任务跟踪和任务取消管理。
使用 ThreadPoolExecutor 管理翻译线程，最大并发数 = 最大线程数。
全局复用 MangaTranslator 实例以避免重复加载模型。
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from datetime import datetime, timezone
from typing import Optional, Callable, Any
import logging

from manga_translator.server.core.logging_manager import add_log


logger = logging.getLogger('manga_translator.server')


# 翻译线程池（根据 max_concurrent_tasks 动态创建）
translation_executor: Optional[ThreadPoolExecutor] = None

# 并发控制信号量（用于限制同时进行的翻译任务数）
translation_semaphore: Optional[asyncio.Semaphore] = None

# 全局翻译器实例（复用模型，避免重复加载）
_global_translator = None
_translator_lock = threading.Lock()
_translator_params_hash = None  # 记录当前翻译器的参数哈希，用于判断是否需要重建

# 全局服务器配置（从启动参数设置）
server_config = {
    'use_gpu': False,
    'use_gpu_limited': False,
    'verbose': False,
    'models_ttl': 0,
    'retry_attempts': None,
    'admin_password': None,
    'max_concurrent_tasks': 3,
}

# 活动任务跟踪
active_tasks = {}
active_tasks_lock = threading.Lock()


def init_semaphore():
    """初始化并发控制信号量和线程池"""
    global translation_semaphore, translation_executor
    
    max_concurrent = server_config.get('max_concurrent_tasks', 3)
    logger.info(f"[init_semaphore] 从 server_config 读取 max_concurrent_tasks = {max_concurrent}")
    
    # 关闭旧的线程池（如果存在）
    if translation_executor is not None:
        translation_executor.shutdown(wait=False)
    
    # 创建新的线程池，最大线程数 = 最大并发任务数
    translation_executor = ThreadPoolExecutor(
        max_workers=max_concurrent,
        thread_name_prefix="translator_"
    )
    
    # 创建信号量用于异步等待
    translation_semaphore = asyncio.Semaphore(max_concurrent)
    
    logger.info(f"翻译线程池已初始化: 最大线程数 = {max_concurrent}")


def get_semaphore() -> Optional[asyncio.Semaphore]:
    """获取并发控制信号量"""
    return translation_semaphore


def get_executor() -> Optional[ThreadPoolExecutor]:
    """获取翻译线程池"""
    return translation_executor


async def run_in_translator_thread(func: Callable, *args, **kwargs) -> Any:
    """
    在翻译线程池中执行函数，不阻塞事件循环。
    """
    if translation_executor is None:
        init_semaphore()
    
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        translation_executor,
        lambda: func(*args, **kwargs)
    )


def register_active_task(
    task_id: str, 
    task: Optional[asyncio.Task] = None,
    username: Optional[str] = None,
    translator: Optional[str] = None,
    future: Optional[Future] = None,
    status: str = "queued"
):
    """注册活动任务，默认状态为 queued"""
    with active_tasks_lock:
        active_tasks[task_id] = {
            "start_time": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "cancel_requested": False,
            "task": task,
            "future": future,
            "username": username or "unknown",
            "translator": translator or "unknown",
            "thread_id": None
        }


def update_task_status(task_id: str, status: str):
    """更新任务状态（queued -> running -> completed）"""
    with active_tasks_lock:
        if task_id in active_tasks:
            active_tasks[task_id]["status"] = status


def update_task_thread_id(task_id: str, thread_id: int):
    """更新任务的线程ID"""
    with active_tasks_lock:
        if task_id in active_tasks:
            active_tasks[task_id]["thread_id"] = thread_id


def unregister_active_task(task_id: str):
    """注销活动任务"""
    with active_tasks_lock:
        if task_id in active_tasks:
            del active_tasks[task_id]


def get_active_tasks() -> list:
    """获取所有活动任务"""
    with active_tasks_lock:
        tasks = []
        for task_id, info in active_tasks.items():
            start_time = info["start_time"]
            if isinstance(start_time, str):
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            else:
                start_dt = start_time
            
            now = datetime.now(timezone.utc)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            
            task_data = {
                "task_id": task_id,
                "start_time": info["start_time"],
                "status": info["status"],
                "duration": (now - start_dt).total_seconds(),
                "username": info.get("username", "unknown"),
                "translator": info.get("translator", "unknown"),
                "thread_id": info.get("thread_id")
            }
            tasks.append(task_data)
        return tasks


def is_task_cancelled(task_id: str) -> bool:
    """检查任务是否被取消"""
    with active_tasks_lock:
        if task_id in active_tasks:
            return active_tasks[task_id].get("cancel_requested", False)
        return False


def cancel_task(task_id: str, force: bool = False) -> dict:
    """取消指定的翻译任务"""
    with active_tasks_lock:
        if task_id in active_tasks:
            active_tasks[task_id]["cancel_requested"] = True
            
            if force:
                task = active_tasks[task_id].get("task")
                future = active_tasks[task_id].get("future")
                cancelled = False
                
                if task and not task.done():
                    task.cancel()
                    cancelled = True
                
                if future and not future.done():
                    future.cancel()
                    cancelled = True
                
                if cancelled:
                    add_log(f"管理员强制取消任务: {task_id[:8]}", "WARNING")
                    return {"success": True, "message": "任务已强制终止"}
                else:
                    add_log(f"管理员请求强制取消任务，但任务已完成: {task_id[:8]}", "INFO")
                    return {"success": True, "message": "任务已完成，无需取消"}
            else:
                add_log(f"管理员请求取消任务: {task_id[:8]}", "WARNING")
                return {"success": True, "message": "取消请求已发送（协作式取消）"}
        else:
            return {"success": False, "message": "任务不存在或已完成"}


def update_server_config(config: dict):
    """更新服务器配置"""
    global server_config, _global_translator, _translator_params_hash
    
    # 检查是否需要重建翻译器
    rebuild_translator = False
    key_params = ['use_gpu', 'use_gpu_limited', 'verbose', 'models_ttl']
    for key in key_params:
        if key in config and config[key] != server_config.get(key):
            rebuild_translator = True
            break
    
    if 'max_concurrent_tasks' in config:
        old_value = server_config.get('max_concurrent_tasks', 3)
        new_value = config['max_concurrent_tasks']
        server_config['max_concurrent_tasks'] = new_value
        
        if old_value != new_value:
            init_semaphore()
            logger.info(f"并发数已更新: {old_value} -> {new_value}")
    
    for key in ['use_gpu', 'use_gpu_limited', 'verbose', 'models_ttl', 'retry_attempts', 'admin_password']:
        if key in config:
            server_config[key] = config[key]
    
    # 如果关键参数变化，重置全局翻译器
    if rebuild_translator and _global_translator is not None:
        with _translator_lock:
            logger.info("服务器配置变化，重置全局翻译器...")
            _global_translator = None
            _translator_params_hash = None


def get_server_config() -> dict:
    """获取服务器配置"""
    return server_config.copy()


def get_thread_pool_status() -> dict:
    """获取线程池状态"""
    if translation_executor is None:
        return {"initialized": False, "max_workers": 0, "active_threads": 0}
    
    with active_tasks_lock:
        active_count = len(active_tasks)
    
    return {
        "initialized": True,
        "max_workers": server_config.get('max_concurrent_tasks', 3),
        "active_tasks": active_count,
        "translator_loaded": _global_translator is not None
    }


def shutdown_executor():
    """关闭线程池和翻译器（服务器关闭时调用）"""
    global translation_executor, _global_translator
    
    if translation_executor is not None:
        logger.info("正在关闭翻译线程池...")
        translation_executor.shutdown(wait=True)
        translation_executor = None
    
    if _global_translator is not None:
        logger.info("正在卸载全局翻译器...")
        with _translator_lock:
            _global_translator = None
    
    logger.info("资源清理完成")



# ============================================================================
# 全局翻译器实例管理（复用模型，避免重复加载）
# ============================================================================

def _get_params_hash(params: dict) -> str:
    """计算参数哈希，用于判断是否需要重建翻译器"""
    key_params = ['use_gpu', 'use_gpu_limited', 'verbose', 'models_ttl']
    values = tuple(params.get(k) for k in key_params)
    return str(values)


def get_global_translator(params: dict = None):
    """
    获取全局翻译器实例，复用模型避免重复加载。
    
    模型复用原理：
    1. MangaTranslator 内部会缓存已加载的模型（OCR、检测器、修复器等）
    2. 通过复用同一个 MangaTranslator 实例，模型只需加载一次
    3. 每次翻译时传入不同的 Config，翻译器会根据配置选择对应的模型
    4. models_ttl 参数控制模型在内存中保留的时间
    
    Args:
        params: 翻译器参数（use_gpu, verbose, models_ttl 等）
    
    Returns:
        MangaTranslator 实例
    """
    global _global_translator, _translator_params_hash
    
    from manga_translator import MangaTranslator
    
    # 如果没有传入参数，使用服务器配置
    if params is None:
        params = {
            'use_gpu': server_config.get('use_gpu', False),
            'use_gpu_limited': server_config.get('use_gpu_limited', False),
            'verbose': server_config.get('verbose', False),
            'models_ttl': server_config.get('models_ttl', 0),
        }
        retry_attempts = server_config.get('retry_attempts')
        if retry_attempts is not None:
            params['attempts'] = retry_attempts
    
    params_hash = _get_params_hash(params)
    
    with _translator_lock:
        # 检查是否需要重建翻译器
        if _global_translator is None or _translator_params_hash != params_hash:
            if _global_translator is not None:
                logger.info(f"翻译器参数变化，重建实例...")
            else:
                logger.info(f"创建全局翻译器实例 (GPU={params.get('use_gpu')}, models_ttl={params.get('models_ttl')}s)...")
            
            _global_translator = MangaTranslator(params=params)
            _translator_params_hash = params_hash
            logger.info("全局翻译器实例已创建，模型将按需加载并缓存")
        
        return _global_translator


def reset_global_translator():
    """
    重置全局翻译器（用于管理员手动释放内存）
    """
    global _global_translator, _translator_params_hash
    
    with _translator_lock:
        if _global_translator is not None:
            logger.info("正在重置全局翻译器...")
            try:
                if hasattr(_global_translator, 'unload_models'):
                    _global_translator.unload_models()
            except Exception as e:
                logger.warning(f"卸载模型时出错: {e}")
            
            _global_translator = None
            _translator_params_hash = None
            
            # 强制垃圾回收
            import gc
            gc.collect()
            
            # 清理 GPU 显存
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    logger.info("GPU 显存已清理")
            except Exception:
                pass
            
            logger.info("全局翻译器已重置")
            return {"success": True, "message": "翻译器已重置，模型已卸载"}
        else:
            return {"success": True, "message": "翻译器未初始化，无需重置"}


def get_translator_status() -> dict:
    """
    获取翻译器状态
    """
    with _translator_lock:
        if _global_translator is None:
            return {
                "initialized": False,
                "models_loaded": []
            }
        
        # 获取已加载的模型信息
        models_loaded = []
        if hasattr(_global_translator, '_model_usage_timestamps'):
            for (tool, model), timestamp in _global_translator._model_usage_timestamps.items():
                models_loaded.append({
                    "tool": tool,
                    "model": model,
                    "last_used": timestamp
                })
        
        return {
            "initialized": True,
            "models_loaded": models_loaded,
            "models_ttl": server_config.get('models_ttl', 0),
            "use_gpu": server_config.get('use_gpu', False)
        }
