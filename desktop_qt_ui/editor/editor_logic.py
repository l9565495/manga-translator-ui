import json
import os
from typing import List, Optional

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QFileDialog

from services import get_config_service
from widgets.folder_dialog import select_folders


class EditorLogic(QObject):
    """
    Handles the business logic for the editor view, including file list management.
    """
    file_list_changed = pyqtSignal(list)
    file_list_with_tree_changed = pyqtSignal(list, dict)  # (files, folder_map)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.source_files: List[str] = []
        self.translated_files: List[str] = []
        self.translation_map_cache = {}
        self.config_service = get_config_service()
        self.folder_tree: dict = {}  # 保存文件夹树结构

    # --- File Management Methods ---

    @pyqtSlot()
    def open_and_add_files(self):
        """Opens a file dialog to add files to the editor's list."""
        last_dir = self.config_service.get_config().app.last_open_dir
        file_paths, _ = QFileDialog.getOpenFileNames(
            None, 
            "添加文件到编辑器", 
            last_dir, 
            "All Supported Files (*.png *.jpg *.jpeg *.bmp *.webp *.avif *.pdf *.epub *.cbz *.cbr *.zip);;"
            "Image Files (*.png *.jpg *.jpeg *.bmp *.webp *.avif);;"
            "PDF Files (*.pdf);;"
            "EPUB Files (*.epub);;"
            "Comic Book Archives (*.cbz *.cbr *.zip)"
        )
        if file_paths:
            self.add_files(file_paths)
            os.path.dirname(file_paths[0])
            # TODO: Find a way to save last_open_dir back to config service

    @pyqtSlot()
    def open_and_add_folder(self):
        """Opens a dialog to select folders (supports multiple selection) and adds all containing images to the list."""
        last_dir = self.config_service.get_config().app.last_open_dir

        # 使用自定义的现代化文件夹选择器
        folders = select_folders(
            parent=None,
            start_dir=last_dir,
            multi_select=True,
            config_service=self.config_service
        )

        if folders:
            # 扫描文件夹，添加所有图片文件路径
            for folder_path in folders:
                self.add_folder(folder_path)

    def add_files(self, files: List[str]):
        if not files:
            return
        new_files = [f for f in files if f not in self.source_files]
        if new_files:
            # 检查是否是第一次添加文件（列表为空）
            is_first_add = len(self.source_files) == 0

            self.source_files.extend(new_files)
            self.file_list_changed.emit(self.source_files)

            # 如果是第一次添加文件，自动加载第一个
            if is_first_add and len(new_files) > 0:
                try:
                    self.load_image_into_editor(new_files[0])
                except Exception:
                    pass  # 静默失败，避免崩溃

    def add_folder(self, folder_path: str):
        if not folder_path or not os.path.isdir(folder_path):
            return
        
        # 检查是否是第一次添加文件（列表为空）
        is_first_add = len(self.source_files) == 0
        
        # 添加文件夹路径到source_files，让FileListView创建树形结构
        if folder_path not in self.source_files:
            self.source_files.append(folder_path)
            self.file_list_changed.emit(self.source_files)
            
            # 如果是第一次添加，自动加载第一个图片
            if is_first_add:
                image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.avif'}
                try:
                    for root, dirs, files in os.walk(folder_path):
                        for f in sorted(files):
                            if os.path.splitext(f)[1].lower() in image_extensions:
                                first_image = os.path.join(root, f)
                                try:
                                    self.load_image_into_editor(first_image)
                                except Exception:
                                    pass  # 静默失败，避免崩溃
                                return
                except OSError:
                    pass  # 静默失败

    @pyqtSlot(list)
    def add_files_from_paths(self, paths: List[str]):
        """
        从拖放的路径列表中添加文件和文件夹
        
        Args:
            paths: 拖放的文件或文件夹路径列表
        """
        files_to_add = []
        for path in paths:
            if os.path.isfile(path):
                # 验证是否是图片文件
                image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.avif'}
                if os.path.splitext(path)[1].lower() in image_extensions:
                    files_to_add.append(path)
            elif os.path.isdir(path):
                # 添加文件夹中的所有图片
                self.add_folder(path)
        
        # 添加单独的文件
        if files_to_add:
            self.add_files(files_to_add)

    @pyqtSlot(str)
    def remove_file(self, file_path: str, emit_signal: bool = False):
        """
        移除文件或文件夹（可能是源文件、翻译后的文件、或文件夹）
        
        Args:
            file_path: 要移除的文件或文件夹路径
            emit_signal: 是否发射 file_list_changed 信号（默认 False，由视图自己处理）
        """
        norm_file = os.path.normpath(file_path) if file_path else None
        
        # 检查是否是文件夹
        if norm_file in self.folder_tree:
            # 这是一个文件夹，检查当前图片是否在其中
            current_image_path = self.controller.model.get_source_image_path()
            if current_image_path:
                norm_current = os.path.normpath(current_image_path)
                # 检查当前图片是否在被删除的文件夹内
                try:
                    if norm_current.startswith(norm_file + os.sep) or norm_current == norm_file:
                        self.controller.model.set_image(None)
                        self.controller._clear_editor_state()
                except:
                    pass
            
            # 从 folder_tree 中删除
            del self.folder_tree[norm_file]
            
            # 从 source_files 和 translated_files 中删除该文件夹下的所有文件
            files_to_remove = []
            for source_file in self.source_files:
                norm_source = os.path.normpath(source_file)
                try:
                    if norm_source.startswith(norm_file + os.sep):
                        files_to_remove.append(source_file)
                except:
                    pass
            
            for f in files_to_remove:
                self.source_files.remove(f)
            
            # 同样处理 translated_files
            files_to_remove = []
            for trans_file in self.translated_files:
                norm_trans = os.path.normpath(trans_file)
                try:
                    if norm_trans.startswith(norm_file + os.sep):
                        files_to_remove.append(trans_file)
                except:
                    pass
            
            for f in files_to_remove:
                self.translated_files.remove(f)
            
            return
        
        # 检查是否是文件
        # 查找文件对（源文件和翻译文件）
        source_path, translated_path = self._find_file_pair(file_path)
        norm_source = os.path.normpath(source_path) if source_path else None
        
        # 从 source_files 中删除（需要规范化路径进行比较）
        files_to_remove = []
        if source_path:
            norm_source = os.path.normpath(source_path)
            for f in self.source_files:
                if os.path.normpath(f) == norm_source:
                    files_to_remove.append(f)
            
            for f in files_to_remove:
                self.source_files.remove(f)
        
        # 从 translated_files 中删除（需要规范化路径进行比较）
        files_to_remove = []
        if translated_path:
            norm_trans = os.path.normpath(translated_path)
            for f in self.translated_files:
                if os.path.normpath(f) == norm_trans:
                    files_to_remove.append(f)
            
            for f in files_to_remove:
                self.translated_files.remove(f)
        
        # 检查当前加载的图片是否是被移除的文件
        current_image_path = self.controller.model.get_source_image_path()
        if current_image_path:
            norm_current = os.path.normpath(current_image_path)
            if norm_current == norm_file or norm_current == norm_source:
                self.controller.model.set_image(None)
                self.controller._clear_editor_state(release_image_cache=True)
        
        # 从资源管理器的缓存中释放被移除的图片
        if hasattr(self.controller, 'resource_manager'):
            if source_path:
                self.controller.resource_manager.release_image_from_cache(source_path)
            if translated_path:
                self.controller.resource_manager.release_image_from_cache(translated_path)

    @pyqtSlot()
    def clear_list(self):
        self.source_files.clear()
        self.translated_files.clear()
        self.folder_tree.clear()
        # 清空列表时发射空列表
        self.file_list_changed.emit([])
        
        # 先清空画布图片，这样后台任务会检测到图片为None而提前返回
        self.controller.model.set_image(None)
        # 然后清空编辑器状态（包括取消后台任务）
        self.controller._clear_editor_state(release_image_cache=True)
        
        # 清空所有图片缓存
        if hasattr(self.controller, 'resource_manager'):
            self.controller.resource_manager.clear_image_cache()

    # --- Image Loading Methods ---

    def load_file_lists(self, source_files: List[str], translated_files: List[str], folder_tree: dict = None):
        """
        Receives the file lists from the coordinator to populate the editor.
        folder_tree: 完整的文件夹树结构 {folder_path: {'files': [...], 'subfolders': [...]}}
        """
        self.source_files = source_files
        self.translated_files = translated_files
        self.folder_tree = folder_tree if folder_tree else {}
        self.translation_map_cache.clear() # Clear cache when lists change
        
        # 如果有folder_tree，使用树形结构显示
        if folder_tree:
            self.file_list_with_tree_changed.emit(source_files, folder_tree)
        else:
            # 否则使用平铺列表
            self.file_list_changed.emit(source_files)

    @pyqtSlot(str)
    def load_image_into_editor(self, file_path: str):
        """
        Loads a specific image into the editor view by finding its pair and calling the controller.
        如果是翻译后的图片，直接加载翻译后的图片（查看器模式）
        如果是源文件，加载源文件（编辑模式）
        """
        source_path, translated_path = self._find_file_pair(file_path)

        # 如果传入的是翻译后的文件（translated_path == file_path），直接加载翻译后的文件
        if translated_path and os.path.normpath(file_path) == os.path.normpath(translated_path):
            self.controller.load_image_and_regions(translated_path)
        elif source_path:
            self.controller.load_image_and_regions(source_path)
        else:
            # Fallback for safety
            self.controller.load_image_and_regions(file_path)

    def _find_file_pair(self, file_path: str) -> (str, Optional[str]):
        """Given a file path, find its source/translated pair using translation_map.json."""
        norm_path = os.path.normpath(file_path)

        # Case 1: The given file is a translated file (a key in a map)
        try:
            output_dir = os.path.dirname(norm_path)
            map_path = os.path.join(output_dir, 'translation_map.json')
            if os.path.exists(map_path):
                t_map = self.translation_map_cache.get(map_path)
                if t_map is None:
                    with open(map_path, 'r', encoding='utf-8') as f:
                        t_map = json.load(f)
                    self.translation_map_cache[map_path] = t_map
                
                if norm_path in t_map:
                    source = t_map[norm_path]
                    if os.path.exists(source):
                        return source, file_path
        except Exception: pass
        
        # Case 2: The given file is a source file (a value in a map)
        try:
            for trans_file in self.translated_files:
                if not trans_file: continue
                norm_trans = os.path.normpath(trans_file)
                output_dir = os.path.dirname(norm_trans)
                map_path = os.path.join(output_dir, 'translation_map.json')
                if os.path.exists(map_path):
                    t_map = self.translation_map_cache.get(map_path)
                    if t_map is None:
                        with open(map_path, 'r', encoding='utf-8') as f:
                            t_map = json.load(f)
                        self.translation_map_cache[map_path] = t_map

                    if t_map.get(norm_trans) == norm_path:
                        return file_path, trans_file
        except Exception: pass

        # Case 3: No pair found, it's a source file with no known translation.
        return file_path, None

    @pyqtSlot()
    def on_global_render_setting_changed(self):
        """Slot to handle changes in global render settings."""
        self.controller.handle_global_render_setting_change()