import os
import re
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from PyQt6.QtCore import QSize, Qt, pyqtSignal, QObject, pyqtSlot
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
)


# 全局线程池，用于异步加载缩略图
_thumbnail_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="thumbnail_loader")


class ThumbnailSignals(QObject):
    """用于从工作线程发送信号到主线程"""
    thumbnail_loaded = pyqtSignal(str, QPixmap)  # file_path, pixmap


def natural_sort_key(path: str):
    """
    生成自然排序的键，支持数字排序
    例如: file1.jpg, file2.jpg, file10.jpg 会按 1, 2, 10 排序
    """
    filename = os.path.basename(path)
    parts = []
    for part in re.split(r'(\d+)', filename):
        if part.isdigit():
            parts.append(int(part))
        else:
            parts.append(part.lower())
    return parts


def _load_thumbnail_worker(file_path: str) -> tuple[str, Optional[QPixmap]]:
    """
    在工作线程中加载缩略图
    返回 (file_path, pixmap) 或 (file_path, None) 如果失败
    """
    try:
        img = Image.open(file_path)
        img.thumbnail((40, 40))
        
        # Convert PIL image to QPixmap
        if img.mode == 'RGB':
            q_img = QImage(img.tobytes(), img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
        elif img.mode == 'RGBA':
            q_img = QImage(img.tobytes(), img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)
        else:  # Fallback for other modes like L, P, etc.
            img = img.convert('RGBA')
            q_img = QImage(img.tobytes(), img.width, img.height, img.width * 4, QImage.Format.Format_RGBA8888)

        pixmap = QPixmap.fromImage(q_img)
        return (file_path, pixmap)
    except Exception as e:
        print(f"Error loading thumbnail for {file_path}: {e}")
        return (file_path, None)


class FileItemWidget(QWidget):
    """自定义列表项，用于显示缩略图、文件名和移除按钮"""
    remove_requested = pyqtSignal(str)
    
    # 类级别的缩略图缓存
    _thumbnail_cache: Dict[str, QPixmap] = {}
    # 类级别的信号对象（所有实例共享）
    _signals = ThumbnailSignals()
    # 存储所有活动的实例，用于分发信号
    _active_instances: Dict[str, List['FileItemWidget']] = {}

    def __init__(self, file_path, is_folder=False, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.is_folder = is_folder
        self._thumbnail_loading = False

        # 注册实例
        if not is_folder and not os.path.isdir(file_path):
            if file_path not in FileItemWidget._active_instances:
                FileItemWidget._active_instances[file_path] = []
            FileItemWidget._active_instances[file_path].append(self)

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)
        self.layout.setSpacing(10)

        # Thumbnail
        self.thumbnail_label = QLabel()
        self.thumbnail_label.setFixedSize(40, 40)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.thumbnail_label)

        if is_folder or os.path.isdir(self.file_path):
            style = QApplication.style()
            icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
            self.thumbnail_label.setPixmap(icon.pixmap(QSize(40,40)))
        else:
            # 连接全局信号（只连接一次）
            if not hasattr(FileItemWidget, '_signals_connected'):
                FileItemWidget._signals.thumbnail_loaded.connect(FileItemWidget._dispatch_thumbnail)
                FileItemWidget._signals_connected = True
            self._load_thumbnail()

        # File Name
        display_name = os.path.basename(file_path)
        self.base_display_name = display_name  # 保存基础名称
        
        self.name_label = QLabel(display_name)
        self.name_label.setWordWrap(True)
        self.layout.addWidget(self.name_label, 1)  # Stretch factor

        # Remove Button
        self.remove_button = QPushButton("✕")
        self.remove_button.setFixedSize(20, 20)
        self.remove_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # 防止获取焦点
        self.remove_button.clicked.connect(self._emit_remove_request)
        self.layout.addWidget(self.remove_button)
    
    def __del__(self):
        """析构时从活动实例列表中移除"""
        if self.file_path in FileItemWidget._active_instances:
            try:
                FileItemWidget._active_instances[self.file_path].remove(self)
                if not FileItemWidget._active_instances[self.file_path]:
                    del FileItemWidget._active_instances[self.file_path]
            except (ValueError, KeyError):
                pass
    
    @classmethod
    def _dispatch_thumbnail(cls, file_path: str, pixmap: Optional[QPixmap]):
        """分发缩略图到所有相关实例"""
        if file_path in cls._active_instances:
            for instance in cls._active_instances[file_path]:
                instance._on_thumbnail_loaded(file_path, pixmap)

    def update_file_count(self, count: int):
        """更新文件夹显示的文件数量"""
        if self.is_folder:
            display_name = f"{self.base_display_name} ({count}个文件)"
            self.name_label.setText(display_name)

    def _load_thumbnail(self):
        """异步加载缩略图，使用缓存机制"""
        # 检查缓存
        if self.file_path in FileItemWidget._thumbnail_cache:
            self.thumbnail_label.setPixmap(FileItemWidget._thumbnail_cache[self.file_path])
            return
        
        # 显示加载中提示
        self.thumbnail_label.setText("...")
        self._thumbnail_loading = True
        
        # 提交到线程池异步加载
        future = _thumbnail_executor.submit(_load_thumbnail_worker, self.file_path)
        future.add_done_callback(self._on_thumbnail_future_done)
    
    def _on_thumbnail_future_done(self, future):
        """线程池任务完成回调"""
        try:
            file_path, pixmap = future.result()
            # 通过信号发送到主线程
            FileItemWidget._signals.thumbnail_loaded.emit(file_path, pixmap)
        except Exception as e:
            print(f"Error in thumbnail future callback: {e}")
    
    def _on_thumbnail_loaded(self, file_path: str, pixmap: Optional[QPixmap]):
        """在主线程中接收缩略图加载完成的信号"""
        self._thumbnail_loading = False
        
        # 检查 widget 是否还存在
        try:
            if pixmap:
                self.thumbnail_label.setPixmap(pixmap)
                # 缓存缩略图（只缓存一次）
                if file_path not in FileItemWidget._thumbnail_cache:
                    FileItemWidget._thumbnail_cache[file_path] = pixmap
            else:
                self.thumbnail_label.setText("ERR")
        except RuntimeError:
            # Widget 已被删除，忽略
            pass

    def _emit_remove_request(self):
        """发射删除请求信号"""
        self.remove_requested.emit(self.file_path)

    def get_path(self):
        return self.file_path
    
    @classmethod
    def clear_thumbnail_cache(cls):
        """清空缩略图缓存"""
        cls._thumbnail_cache.clear()
    
    @classmethod
    def remove_from_cache(cls, file_path: str):
        """从缓存中移除指定文件的缩略图"""
        if file_path in cls._thumbnail_cache:
            del cls._thumbnail_cache[file_path]


class FileListView(QTreeWidget):
    """显示文件列表的自定义控件（支持文件夹分组）"""
    file_remove_requested = pyqtSignal(str)
    file_selected = pyqtSignal(str)
    files_dropped = pyqtSignal(list)  # 新增：拖放文件信号

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self.model = model
        
        # 导入i18n
        from services import get_i18n_manager
        self.i18n = get_i18n_manager()
        
        # 设置树形控件属性
        self.setHeaderHidden(True)  # 隐藏标题栏
        self.setIndentation(20)  # 设置缩进
        self.setAnimated(True)  # 启用展开/折叠动画
        
        # 启用拖放
        self.setAcceptDrops(True)
        self.setDragEnabled(False)  # 禁用拖出，只允许拖入
        
        # 存储文件夹到树节点的映射
        self.folder_nodes: Dict[str, QTreeWidgetItem] = {}
        
        # 连接选择信号
        self.itemSelectionChanged.connect(self._on_selection_changed)
    
    def _t(self, key: str, **kwargs) -> str:
        """翻译辅助方法"""
        if self.i18n:
            return self.i18n.translate(key, **kwargs)
        return key
    
    def refresh_ui_texts(self):
        """刷新UI文本（用于语言切换）"""
        # 强制重绘以更新拖拽提示文本
        self.viewport().update()
        self.update()

    def paintEvent(self, event):
        """重写绘制事件，在列表为空时显示提示"""
        super().paintEvent(event)
        
        # 只在列表为空时显示提示
        if self.topLevelItemCount() == 0:
            from PyQt6.QtGui import QPainter, QColor, QFont
            from PyQt6.QtCore import Qt, QRect
            
            painter = QPainter(self.viewport())
            painter.setPen(QColor(150, 150, 150))  # 灰色
            
            # 设置字体
            font = QFont()
            font.setPointSize(10)
            painter.setFont(font)
            
            # 绘制提示文本
            rect = self.viewport().rect()
            text = self._t("Drag and drop files or folders here\nor click the buttons above to add")
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
            
            painter.end()

    def _on_selection_changed(self):
        """处理选择变化"""
        selected_items = self.selectedItems()
        if not selected_items:
            return
        
        tree_item = selected_items[0]
        file_path = tree_item.data(0, Qt.ItemDataRole.UserRole)
        
        # 只有当选中的是文件（不是文件夹节点）时才发出信号
        if file_path and not os.path.isdir(file_path):
            self.file_selected.emit(file_path)

    def add_files(self, file_paths: List[str]):
        """添加多个文件/文件夹到列表"""
        # 按文件夹分组
        folder_groups: Dict[str, List[str]] = {}
        standalone_files: List[str] = []
        
        for path in file_paths:
            norm_path = os.path.normpath(path)
            
            if os.path.isdir(norm_path):
                # 如果传入的是文件夹路径，递归扫描其中的所有图片（包括子文件夹）
                try:
                    image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}
                    files = []
                    
                    # 递归遍历文件夹及其子文件夹，按子文件夹顺序排序
                    for root, dirs, filenames in os.walk(norm_path):
                        # 忽略 manga_translator_work 目录
                        if 'manga_translator_work' in dirs:
                            dirs.remove('manga_translator_work')
                        
                        # 对子文件夹进行自然排序，确保按正确顺序遍历
                        dirs.sort(key=natural_sort_key)
                        
                        # 收集当前目录的图片并排序
                        current_files = []
                        for f in filenames:
                            if os.path.splitext(f)[1].lower() in image_extensions:
                                current_files.append(os.path.join(root, f))
                        
                        # 对当前目录的文件进行自然排序后添加
                        current_files.sort(key=natural_sort_key)
                        files.extend(current_files)
                    
                    if files:
                        folder_groups[norm_path] = files
                except Exception as e:
                    print(f"Error loading files from folder {norm_path}: {e}")
            else:
                # 检查文件是否已存在
                file_dir = os.path.dirname(norm_path)
                
                # 如果文件的父目录已经在分组中，添加到该分组
                if file_dir in folder_groups:
                    if norm_path not in folder_groups[file_dir]:
                        folder_groups[file_dir].append(norm_path)
                else:
                    # 检查是否有其他文件来自同一目录
                    found_group = False
                    for existing_file in file_paths:
                        if existing_file != path and os.path.dirname(os.path.normpath(existing_file)) == file_dir:
                            # 找到同目录的文件，创建分组
                            if file_dir not in folder_groups:
                                folder_groups[file_dir] = []
                            if norm_path not in folder_groups[file_dir]:
                                folder_groups[file_dir].append(norm_path)
                            found_group = True
                            break
                    
                    if not found_group:
                        # 独立文件
                        standalone_files.append(norm_path)
        
        # 添加文件夹分组
        for folder_path, files in folder_groups.items():
            self._add_folder_group(folder_path, files)
        
        # 添加独立文件
        for file_path in standalone_files:
            self._add_single_file(file_path)
        
        # 触发重绘以隐藏占位提示
        self.viewport().update()

    def _add_folder(self, folder_path: str):
        """添加文件夹及其包含的所有图片文件"""
        if folder_path in self.folder_nodes:
            return  # 文件夹已存在
        
        # 创建文件夹节点
        folder_item = QTreeWidgetItem(self)
        folder_item.setData(0, Qt.ItemDataRole.UserRole, folder_path)
        
        # 创建文件夹项的自定义控件
        folder_widget = FileItemWidget(folder_path, is_folder=True)
        folder_widget.remove_requested.connect(self.file_remove_requested.emit)
        
        self.addTopLevelItem(folder_item)
        self.setItemWidget(folder_item, 0, folder_widget)
        
        # 保存文件夹节点
        self.folder_nodes[folder_path] = folder_item
        
        # 递归添加文件夹中的所有文件（包括子文件夹），按子文件夹顺序排序
        try:
            image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}
            files = []
            
            # 递归遍历文件夹及其子文件夹，按子文件夹顺序排序
            for root, dirs, filenames in os.walk(folder_path):
                # 忽略 manga_translator_work 目录
                if 'manga_translator_work' in dirs:
                    dirs.remove('manga_translator_work')
                
                # 对子文件夹进行自然排序，确保按正确顺序遍历
                dirs.sort(key=natural_sort_key)
                
                # 收集当前目录的图片并排序
                current_files = []
                for f in filenames:
                    if os.path.splitext(f)[1].lower() in image_extensions:
                        current_files.append(os.path.join(root, f))
                
                # 对当前目录的文件进行自然排序后添加
                current_files.sort(key=natural_sort_key)
                files.extend(current_files)
            
            for file_path in files:
                self._add_file_to_folder(file_path, folder_item)
            
            # 更新文件夹显示的文件数
            self._update_folder_count(folder_item)
        except Exception as e:
            print(f"Error loading files from folder {folder_path}: {e}")
    
    def _add_folder_group(self, folder_path: str, files: List[str]):
        """添加文件夹分组（使用提供的文件列表）"""
        if folder_path in self.folder_nodes:
            # 文件夹已存在，添加新文件
            folder_item = self.folder_nodes[folder_path]
            existing_files = set()
            for i in range(folder_item.childCount()):
                child = folder_item.child(i)
                existing_files.add(child.data(0, Qt.ItemDataRole.UserRole))
            
            for file_path in files:
                if file_path not in existing_files:
                    self._add_file_to_folder(file_path, folder_item)
            
            # 更新文件夹显示的文件数
            self._update_folder_count(folder_item)
            return
        
        # 创建文件夹节点
        folder_item = QTreeWidgetItem(self)
        folder_item.setData(0, Qt.ItemDataRole.UserRole, folder_path)
        
        # 创建文件夹项的自定义控件
        folder_widget = FileItemWidget(folder_path, is_folder=True)
        folder_widget.remove_requested.connect(self.file_remove_requested.emit)
        
        self.addTopLevelItem(folder_item)
        self.setItemWidget(folder_item, 0, folder_widget)
        
        # 保存文件夹节点
        self.folder_nodes[folder_path] = folder_item
        
        # 添加文件列表（保持传入的顺序，已经按子文件夹排序好了）
        for file_path in files:
            self._add_file_to_folder(file_path, folder_item)
        
        # 更新文件夹显示的文件数
        self._update_folder_count(folder_item)

    def _add_file_to_folder(self, file_path: str, parent_item: QTreeWidgetItem):
        """将文件添加到文件夹节点下"""
        file_item = QTreeWidgetItem(parent_item)
        file_item.setData(0, Qt.ItemDataRole.UserRole, file_path)
        
        file_widget = FileItemWidget(file_path, is_folder=False)
        file_widget.remove_requested.connect(self.file_remove_requested.emit)
        
        parent_item.addChild(file_item)
        self.setItemWidget(file_item, 0, file_widget)

    def _add_single_file(self, file_path: str):
        """添加单个文件（不属于任何文件夹）"""
        # 检查文件是否已存在
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == file_path:
                return  # 文件已存在
        
        file_item = QTreeWidgetItem(self)
        file_item.setData(0, Qt.ItemDataRole.UserRole, file_path)
        
        file_widget = FileItemWidget(file_path, is_folder=False)
        file_widget.remove_requested.connect(self.file_remove_requested.emit)
        
        self.addTopLevelItem(file_item)
        self.setItemWidget(file_item, 0, file_widget)

    def remove_file(self, file_path: str):
        """移除指定文件或文件夹"""
        norm_path = os.path.normpath(file_path)
        
        # 临时断开选择信号，避免删除时触发选择事件
        self.itemSelectionChanged.disconnect(self._on_selection_changed)
        
        try:
            # 如果是文件夹
            if norm_path in self.folder_nodes:
                # 移除文件夹节点
                folder_item = self.folder_nodes[norm_path]
                index = self.indexOfTopLevelItem(folder_item)
                if index >= 0:
                    self.takeTopLevelItem(index)
                del self.folder_nodes[norm_path]
                return
            
            # 如果是文件，查找并移除
            def find_and_remove(parent_item: Optional[QTreeWidgetItem] = None):
                if parent_item is None:
                    # 搜索顶层项
                    for i in range(self.topLevelItemCount()):
                        item = self.topLevelItem(i)
                        if item.data(0, Qt.ItemDataRole.UserRole) == norm_path:
                            self.takeTopLevelItem(i)
                            return True, None
                        # 递归搜索子项
                        result, parent = find_and_remove(item)
                        if result:
                            return True, parent
                else:
                    # 搜索子项
                    for i in range(parent_item.childCount()):
                        child = parent_item.child(i)
                        if child.data(0, Qt.ItemDataRole.UserRole) == norm_path:
                            parent_item.removeChild(child)
                            # 检查父文件夹是否还有子项
                            if parent_item.childCount() == 0:
                                # 文件夹为空，移除文件夹节点
                                folder_path = parent_item.data(0, Qt.ItemDataRole.UserRole)
                                if folder_path in self.folder_nodes:
                                    del self.folder_nodes[folder_path]
                                index = self.indexOfTopLevelItem(parent_item)
                                if index >= 0:
                                    self.takeTopLevelItem(index)
                            else:
                                # 文件夹还有子项，更新文件数显示
                                self._update_folder_count(parent_item)
                            return True, parent_item
                return False, None
            
            find_and_remove()
        finally:
            # 重新连接选择信号
            self.itemSelectionChanged.connect(self._on_selection_changed)

    def _update_folder_count(self, folder_item: QTreeWidgetItem):
        """更新文件夹显示的文件数量"""
        if folder_item:
            widget = self.itemWidget(folder_item, 0)
            if isinstance(widget, FileItemWidget) and widget.is_folder:
                count = folder_item.childCount()
                widget.update_file_count(count)

    def clear(self, clear_cache: bool = False):
        """
        清空所有项
        
        Args:
            clear_cache: 是否同时清空缩略图缓存（默认 False，保留缓存以便重用）
        """
        super().clear()
        self.folder_nodes.clear()
        
        if clear_cache:
            FileItemWidget.clear_thumbnail_cache()
        
        # 触发重绘以显示占位提示
        self.viewport().update()

    # 拖放事件处理
    def dragEnterEvent(self, event):
        """拖入事件：检查是否包含文件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        """拖动移动事件"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        """放下事件：处理拖入的文件和文件夹"""
        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if path:
                    paths.append(path)
            
            if paths:
                # 发射信号，让业务逻辑层处理
                self.files_dropped.emit(paths)
            
            event.acceptProposedAction()
        else:
            event.ignore()
