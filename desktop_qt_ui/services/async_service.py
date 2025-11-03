"""
Async Service
Provides a way to run asyncio tasks from a synchronous (Tkinter) context.

现在使用新的 AsyncJobManager 作为底层实现。
"""
import asyncio
import logging
from typing import Coroutine, Optional

# 使用绝对导入避免相对导入问题
from desktop_qt_ui.editor.core import AsyncJobManager, JobPriority


class AsyncService:
    """AsyncService - AsyncJobManager的兼容层
    
    保持与旧代码的接口兼容，内部使用新的AsyncJobManager实现。
    """
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._job_manager = AsyncJobManager()
        self._running = True
        self.logger.info("AsyncService initialized with new AsyncJobManager")

    def submit_task(self, coro: Coroutine):
        """Submits a coroutine to be run on the asyncio event loop.
        
        Args:
            coro: 要执行的协程
        
        Returns:
            Future: 任务的future对象（兼容旧代码）
        """
        if not self._running:
            self.logger.warning("AsyncService is not running, task ignored")
            return None
        
        try:
            # 将协程包装成异步函数
            async def _run_coro():
                return await coro
            
            # 提交到新的job manager
            job = self._job_manager.submit(
                _run_coro,
                priority=JobPriority.NORMAL,
            )
            
            # 返回一个兼容的future对象
            # 注意：旧代码可能不使用返回值，所以这里简单返回job对象
            return job
            
        except Exception as e:
            self.logger.error(f"Failed to submit task: {e}")
            return None
    
    def cancel_all_tasks(self):
        """取消所有活跃的异步任务（非阻塞）"""
        if not self._running:
            return
        
        try:
            count = self._job_manager.cancel_all()
            self.logger.info(f"Cancelled {count} tasks via AsyncService")
        except Exception as e:
            self.logger.error(f"Error cancelling tasks: {e}")

    def shutdown(self):
        """关闭服务"""
        self.logger.info("Shutting down AsyncService")
        self._running = False
        self._job_manager.shutdown(wait=False)

# Global instance
_async_service: Optional[AsyncService] = None

def get_async_service() -> AsyncService:
    global _async_service
    if _async_service is None:
        _async_service = AsyncService()
    return _async_service

def shutdown_async_service():
    global _async_service
    if _async_service:
        _async_service.shutdown()
        _async_service = None
