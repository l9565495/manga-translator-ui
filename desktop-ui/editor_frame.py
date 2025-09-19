import customtkinter as ctk
from PIL import Image
import os
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from tkinter import filedialog
import asyncio
import copy
import winsound
import traceback
import json
import cv2
import pathlib
import gc
import torch

from ui_components import show_toast, CollapsibleFrame
from canvas_frame_new import CanvasFrame
from components.editor_toolbar import EditorToolbar
from components.property_panel import PropertyPanel
from components.file_manager import FileManager
from services.editor_history import EditorStateManager, ActionType, GroupedAction
from services.transform_service import TransformService
from components.file_list_frame import FileListFrame
from components.context_menu import EditorContextMenu
from services.ocr_service import OcrService
from services.translation_service import TranslationService
from services.async_service import get_async_service
from services import get_config_service
import editing_logic
from manga_translator.rendering import resize_regions_to_font_size
from manga_translator.utils import TextBlock
from manga_translator.mask_refinement import dispatch as refine_mask_dispatch
from manga_translator.inpainting import dispatch as inpaint_dispatch
from manga_translator.config import Inpainter, InpainterConfig, InpaintPrecision


class EditorFrame(ctk.CTkFrame):
    """重构后的编辑器主框架"""
    
    def __init__(self, parent, return_callback=None, shortcut_manager=None):
        super().__init__(parent)
        
        self.return_callback = return_callback
        self.shortcut_manager = shortcut_manager
        self.image: Optional[Image.Image] = None
        self.regions_data: List[Dict[str, Any]] = []
        self.selected_indices: List[int] = []
        self.source_files: List[str] = []
        self.translated_files: List[str] = []
        self.last_mouse_event = None
        self.view_mode = 'normal'
        self.raw_mask: Optional[np.ndarray] = None
        self.original_size: Optional[Tuple[int, int]] = None
        self.inpainted_image: Optional[Image.Image] = None
        self.inpainting_in_progress: bool = False
        self.refined_mask: Optional[np.ndarray] = None
        self.removed_mask: Optional[np.ndarray] = None  # 存储被优化掉的原始蒙版区域
        self.mask_edit_mode: str = "不选择"
        self.mask_brush_size: int = 20
        self.mask_edit_start_state: Optional[np.ndarray] = None
        self.is_mask_edit_expanded: bool = True
        self.export_target_path: Optional[str] = None
        
        self.history_manager = EditorStateManager()
        self.transform_service = TransformService()
        self.file_manager = FileManager()
        self.ocr_service = OcrService()
        self.translation_service = TranslationService()
        self.async_service = get_async_service()
        self.config_service = get_config_service()
        self.config_service.register_callback(self.reload_config_and_redraw)

        self._build_ui()
        self._setup_component_connections()
        
        self.after(200, self._init_backend_config)
        
        self.after(100, self._setup_shortcuts)

        self.config_service.reload_from_disk()

    def _find_file_pair(self, file_path: str) -> (str, Optional[str]):
        """Given a file path, find its source/translated pair using translation_map.json."""
        norm_path = os.path.normpath(file_path)
        
        # Case 1: The given file is a translated file (a key in a map)
        try:
            output_dir = os.path.dirname(norm_path)
            map_path = os.path.join(output_dir, 'translation_map.json')
            if os.path.exists(map_path):
                with open(map_path, 'r', encoding='utf-8') as f:
                    t_map = json.load(f)
                if norm_path in t_map:
                    source = t_map[norm_path]
                    if os.path.exists(source):
                        return source, file_path
        except Exception: pass
        
        # Case 2: The given file is a source file (a value in a map)
        try:
            # This is inefficient, but necessary as the source file doesn't know its output dir.
            # We check against already known translated files.
            for trans_file in self.translated_files:
                if not trans_file: continue
                norm_trans = os.path.normpath(trans_file)
                output_dir = os.path.dirname(norm_trans)
                map_path = os.path.join(output_dir, 'translation_map.json')
                if os.path.exists(map_path):
                    with open(map_path, 'r', encoding='utf-8') as f:
                        t_map = json.load(f)
                    if t_map.get(norm_trans) == norm_path:
                        return file_path, trans_file
        except Exception: pass

        # Case 3: No pair found, it's a source file with no known translation.
        return file_path, None

    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=250)
        self.grid_columnconfigure(2, weight=0, minsize=250)

        self.toolbar = EditorToolbar(self, back_callback=self.return_callback)
        self.toolbar.grid(row=0, column=0, columnspan=3, sticky="ew")

        self.property_panel = PropertyPanel(self, shortcut_manager=self.shortcut_manager)
        self.property_panel.grid(row=1, column=0, sticky="ns", padx=(2,1), pady=2)



        self.canvas_frame = CanvasFrame(self, self.transform_service, 
                                        on_region_selected=self._on_region_selected, 
                                        on_region_moved=self._on_region_moved, 
                                        on_region_resized=self._on_region_resized,
                                        on_region_rotated=self._on_region_rotated,
                                        on_region_created=self._on_region_created,
                                        on_geometry_added=self._on_geometry_added,
                                        on_mask_draw_preview=self._on_mask_draw_preview,
                                        on_mask_edit_start=self._on_mask_edit_start,
                                        on_mask_edit_end=self._on_mask_edit_end)
        self.canvas_frame.grid(row=1, column=1, sticky="nsew", pady=2)
        self.property_panel.set_canvas_frame(self.canvas_frame)

        self.file_list_frame = FileListFrame(self, 
                                             on_file_select=self._on_file_selected_from_list,
                                             on_load_files=self._load_files_from_dialog,
                                             on_load_folder=self._load_folder_from_dialog,
                                             on_file_unload=self._on_file_unload,
                                             on_clear_list_requested=self._on_clear_list_requested)
        self.file_list_frame.grid(row=1, column=2, sticky="ns", padx=(1,2), pady=2)

        self.context_menu = EditorContextMenu(self)

    def _setup_component_connections(self):
        self.file_manager.register_callback('image_loaded', self._on_image_loaded)
        self.toolbar.register_callback('export_image', self._export_rendered_image)
        self.toolbar.register_callback('edit_file', self._on_edit_clicked)
        self.toolbar.register_callback('undo', self.undo)
        self.toolbar.register_callback('redo', self.redo)
        self.toolbar.register_callback('zoom_in', self._zoom_in)
        self.toolbar.register_callback('zoom_out', self._zoom_out)
        self.toolbar.register_callback('fit_window', self._fit_to_window)
        self.toolbar.register_callback('edit_geometry', self._enter_geometry_edit_mode)
        self.toolbar.register_callback('display_mode_changed', self._on_display_mode_changed)
        self.toolbar.register_callback('preview_alpha_changed', self._on_preview_alpha_changed)
        self.toolbar.register_callback('render_inpaint', self._render_inpainted_image)
        self.toolbar.register_callback('set_edit_mode', self._on_mask_tool_changed)
        self.toolbar.register_callback('brush_size_changed', self._on_brush_size_changed)
        self.toolbar.register_callback('toggle_mask_visibility', self._on_toggle_mask_visibility)
        self.transform_service.subscribe(self._on_transform_changed)
        self.canvas_frame.canvas.bind("<Button-3>", self._show_context_menu)
        
        self.context_menu.register_callback('add_text_box', self._enter_drawing_mode)
        self.context_menu.register_callback('copy_region', self._copy_selected_regions)
        self.context_menu.register_callback('paste_region', self._on_paste_shortcut)
        self.context_menu.register_callback('paste_style', self._paste_style_to_selected)
        self.context_menu.register_callback('delete_region', self._delete_selected_regions)
        self.context_menu.register_callback('ocr_recognize', self._ocr_selected_regions)
        self.context_menu.register_callback('translate_text', self._translate_selected_regions)
        self.property_panel.register_callback('text_changed', self._on_property_panel_text_changed)
        self.property_panel.register_callback('original_text_changed', self._on_property_panel_original_text_changed)
        self.property_panel.register_callback('style_changed', self._on_property_panel_style_changed)
        self.property_panel.register_callback('transform_changed', self._on_property_panel_transform_changed)

        # Property Panel Action Buttons
        self.property_panel.register_callback('copy_region', self._copy_selected_regions)
        self.property_panel.register_callback('paste_region', self._on_paste_shortcut)
        self.property_panel.register_callback('delete_region', self._delete_selected_regions)

        # Property Panel OCR/Translate Buttons
        self.property_panel.register_callback('ocr_recognize', self._ocr_selected_regions)
        self.property_panel.register_callback('translate_text', self._translate_selected_regions)

        # Property Panel Config Dropdowns
        self.property_panel.register_callback('ocr_model_changed', self._on_ocr_model_changed)
        self.property_panel.register_callback('translator_changed', self._on_translator_changed)
        self.property_panel.register_callback('target_language_changed', self._on_target_language_changed)

        # Property Panel Mask Editor Callbacks
        self.property_panel.register_callback('mask_tool_changed', self._on_mask_tool_changed)
        self.property_panel.register_callback('brush_size_changed', self._on_brush_size_changed)
        self.property_panel.register_callback('toggle_mask_visibility', self._on_toggle_mask_visibility)
        self.property_panel.register_callback('mask_setting_changed', self._on_mask_setting_changed)
        self.property_panel.register_callback('update_mask_with_config', self._update_mask_with_config)
        self.property_panel.register_callback('toggle_removed_mask_visibility', self._on_toggle_removed_mask_visibility)



    def _setup_shortcuts(self):
        canvas = self.canvas_frame.canvas
        canvas.bind("<Control-a>", lambda event: self._select_all_regions())
        canvas.bind("<Control-A>", lambda event: self._select_all_regions())
        canvas.bind("<Control-c>", lambda event: self._copy_selected_regions())
        canvas.bind("<Control-C>", lambda event: self._copy_selected_regions())
        canvas.bind("<Control-v>", lambda event: self._on_paste_shortcut(event))
        canvas.bind("<Control-V>", lambda event: self._on_paste_shortcut(event))
        canvas.bind("<Delete>", lambda event: self._delete_selected_regions())
        canvas.bind("<Control-z>", lambda event: self.undo())
        canvas.bind("<Control-Z>", lambda event: self.undo())
        canvas.bind("<Control-y>", lambda event: self.redo())
        canvas.bind("<Control-Y>", lambda event: self.redo())

    def _apply_action(self, action: Any, is_undo: bool):
        if isinstance(action, GroupedAction):
            actions = action.actions
            if is_undo:
                actions.reverse()
            for sub_action in actions:
                self._apply_single_action(sub_action, is_undo)
        else:
            self._apply_single_action(action, is_undo)
        self._update_canvas_regions()
        self._on_region_selected([])

    def _apply_single_action(self, action: Any, is_undo: bool):
        data_to_use = action.old_data if is_undo else action.new_data
        if action.action_type == ActionType.ADD:
            if is_undo:
                self.regions_data.pop(action.region_index)
            else:
                self.regions_data.insert(action.region_index, data_to_use)
        elif action.action_type == ActionType.DELETE:
            if is_undo:
                self.regions_data.insert(action.region_index, data_to_use)
            else:
                self.regions_data.pop(action.region_index)
        elif action.action_type == ActionType.EDIT_MASK:
            # Use a deepcopy to prevent modifying the history state directly
            self.refined_mask = copy.deepcopy(data_to_use)
            self.canvas_frame.set_refined_mask(self.refined_mask)
        else:
            self.regions_data[action.region_index] = data_to_use

    def _update_history_buttons(self):
        can_undo = self.history_manager.can_undo()
        can_redo = self.history_manager.can_redo()
        self.toolbar.update_undo_redo_state(can_undo, can_redo)

    def undo(self):
        action = self.history_manager.undo()
        if action:
            self._apply_action(action, is_undo=True)
            self._update_history_buttons()

    def redo(self):
        action = self.history_manager.redo()
        if action:
            self._apply_action(action, is_undo=False)
            self._update_history_buttons()

    def _on_region_selected(self, indices: List[int]):
        self.selected_indices = indices
        self.canvas_frame.redraw_canvas()
        self.context_menu.set_selected_region(indices[0] if len(indices) == 1 else None, self.regions_data[indices[0]] if len(indices) == 1 else None)
        if len(indices) == 1:
            self.property_panel.load_region_data(self.regions_data[indices[0]], indices[0])
        else:
            self.property_panel.clear_panel()

    def _on_region_moved(self, index, old_data, new_data):
        self.regions_data[index] = new_data
        self.history_manager.save_state(ActionType.MOVE, index, old_data, new_data)
        self._update_canvas_regions()  # 确保画布更新
        self._update_history_buttons()

    def _on_region_resized(self, index, old_data, new_data):
        self.regions_data[index] = new_data
        self.history_manager.save_state(ActionType.RESIZE, index, old_data, new_data)
        self._update_canvas_regions()  # 确保画布更新
        self._update_history_buttons()

    def _on_region_rotated(self, index, old_data, new_data):
        print(f"_on_region_rotated called for index {index}")
        self.regions_data[index] = new_data
        self.history_manager.save_state(ActionType.ROTATE, index, old_data, new_data) # Using ROTATE for history
        self._update_canvas_regions()  # 添加缺失的画布更新调用
        self._update_history_buttons()

    def _on_region_created(self, new_region):
        self.regions_data.append(new_region)
        self.history_manager.save_state(ActionType.ADD, len(self.regions_data) - 1, None, new_region)
        self._update_canvas_regions()
        self._update_history_buttons()

    def _push_config_to_canvas(self):
        # print("--- TRACE: editor_frame._push_config_to_canvas called ---")
        config = self.config_service.get_config()
        render_config = config.get('render', {})
        self.canvas_frame.set_render_config(render_config)
    
    def _init_backend_config(self):
        """初始化后端配置同步"""
        try:
            config = self.config_service.get_config()
            
            # 同步翻译器配置
            translator_config = config.get('translator', {})
            if 'translator' in translator_config:
                self.translation_service.set_translator(translator_config['translator'])
                print(f"初始化翻译器: {translator_config['translator']}")
            if 'target_lang' in translator_config:
                self.translation_service.set_target_language(translator_config['target_lang'])
                print(f"初始化目标语言: {translator_config['target_lang']}")
            
            # 同步OCR配置
            ocr_config = config.get('ocr', {})
            if 'ocr' in ocr_config:
                self.ocr_service.set_model(ocr_config['ocr'])
                print(f"初始化OCR模型: {ocr_config['ocr']}")
            
            print("后端配置初始化完成")
        except Exception as e:
            print(f"后端配置初始化失败: {e}")
            # 不抛出异常，避免影响启动
    
    def _update_canvas_regions(self):
        config = self.config_service.get_config()
        layout_mode = config.get('render', {}).get('layout_mode', 'default')

        updated_regions_data = []
        for region_data in self.regions_data:
            new_data = region_data.copy()
            new_data['layout_mode'] = layout_mode
            updated_regions_data.append(new_data)

        self.canvas_frame.set_regions(updated_regions_data)

    def _on_image_loaded(self, image: Image.Image, image_path: str):
        # 在加载新图片前，先彻底清空编辑器状态
        self._clear_editor()

        # 存储当前图片路径供导出使用
        self.current_image_path = image_path
        
        # 记住当前是否处于蒙版视图
        was_in_mask_view = self.view_mode == 'mask'
        
        # 清理之前的状态
        self.refined_mask = None
        self.inpainted_image = None
        self.inpainting_in_progress = False
        self.mask_edit_start_state = None
        if hasattr(self, 'history_manager'):
            self.history_manager.clear()
            self._update_history_buttons()
        if hasattr(self, 'file_manager'):
            self.file_manager.is_modified = False
        
        self.image = image
        self.canvas_frame.load_image(image_path)
        
        # 尝试加载JSON数据
        regions, raw_mask, original_size = self.file_manager.load_json_data(image_path)
        
        # 检查是否是作为源文件加载，并且找到了JSON
        if regions:
            # 这是为编辑而加载的原始图像
            self.regions_data = regions
            self.raw_mask = raw_mask
            self.original_size = original_size
            self.property_panel.show_mask_editor()
            
            show_toast(self, "检测到JSON，自动修复背景...", level="info")
            # 自动触发蒙版和修复渲染
            self.async_service.submit_task(self._generate_refined_mask_then_render())
            
            # 设置默认视图为“文字文本框显示”
            self.toolbar.display_menu.set("文字文本框显示")
            self._on_display_mode_changed("文字文本框显示")

        else:
            # 如果是翻译图（找不到JSON）或没有JSON的源图
            self.regions_data = []
            self.raw_mask = None
            self.original_size = image.size
            self.property_panel.hide_mask_editor()

            # 检查是否在translation_map中存在对应关系
            has_translation_mapping = False
            try:
                output_dir = os.path.dirname(image_path)
                map_path = os.path.join(output_dir, 'translation_map.json')
                if os.path.exists(map_path):
                    with open(map_path, 'r', encoding='utf-8') as f:
                        translation_map = json.load(f)
                    has_translation_mapping = os.path.normpath(image_path) in translation_map
            except:
                pass

            # 仅当文件在source_files列表中但未找到JSON时才显示提示
            # 如果在地图中有对应关系，说明是翻译图，不显示提示
            if image_path in self.source_files and not has_translation_mapping:
                 show_toast(self, "未找到JSON翻译数据，请返回主界面翻译或手动编辑", level="info")

        # Set default font for regions that don't have one
        config = self.config_service.get_config()
        render_config = config.get('render', {})
        font_filename = render_config.get('font_path')
        if font_filename and self.regions_data:
            full_font_path = os.path.join(os.path.dirname(__file__), '..', 'fonts', font_filename)
            full_font_path = os.path.abspath(full_font_path)
            final_font_path = pathlib.Path(full_font_path).as_posix()
            if os.path.exists(full_font_path):
                for i, region in enumerate(self.regions_data):
                    if 'font_family' not in region or not region['font_family']:
                        region['font_family'] = final_font_path

        self.canvas_frame.set_original_size(self.original_size)
        self.canvas_frame.set_mask(self.raw_mask)
        self.canvas_frame.set_refined_mask(None)
        self.canvas_frame.set_inpainted_image(None)
        
        self._push_config_to_canvas()
        self.canvas_frame.set_regions(self.regions_data)
        self.after(100, self._fit_to_window)
        
        if was_in_mask_view:
            self.after(200, self._generate_mask_for_new_file)
        
        print(f"已加载图片: {os.path.basename(image_path)}, 蒙版状态已重置")

    def _on_file_selected_from_list(self, file_path: str):
        self.file_manager.load_image_from_path(file_path)

        # 检查翻译映射
        output_dir = os.path.dirname(file_path)
        map_path = os.path.join(output_dir, 'translation_map.json')
        if os.path.exists(map_path):
            with open(map_path, 'r', encoding='utf-8') as f:
                try:
                    translation_map = json.load(f)
                    source_file = translation_map.get(os.path.normpath(file_path))
                    if source_file:
                        self.set_file_lists([source_file], [file_path])
                except json.JSONDecodeError:
                    pass # Ignore if map is corrupted
    
    def _generate_mask_for_new_file(self):
        """为新文件生成蒙版（在蒙版视图切换文件时使用）"""
        if self.view_mode == 'mask' and self.image is not None:
            print("正在为新文件生成蒙版...")
            self.async_service.submit_task(self._generate_refined_mask())
    
    def _has_unsaved_changes(self):
        """检测是否有未保存的修改"""
        try:
            # 检查历史记录中是否有任何编辑操作
            if hasattr(self, 'history_manager') and self.history_manager.undo_stack:
                # 如果有撤销栈中有操作，说明有修改
                return len(self.history_manager.undo_stack) > 0
            
            # 检查FileManager的修改状态
            if hasattr(self, 'file_manager') and hasattr(self.file_manager, 'is_modified'):
                return self.file_manager.is_modified
            
            # 检查是否有精细蒙版（通常意味着用户编辑过）
            if self.refined_mask is not None:
                return True
            
            return False
            
        except:
            # 出错时保守处理，认为有未保存的修改
            return True

    def set_file_lists(self, source_files: List[str], translated_files: List[str]):
        """
        Adds new source and translated files to the editor's lists using the unified logic.
        It processes the translated files first as they are the primary items of interest.
        """
        # We process the translated files first, then sources. 
        # The robust `_add_files_to_list` will handle duplicates and find pairs correctly.
        files_to_process = [f for f in translated_files if f] + [f for f in source_files if f]
        self._add_files_to_list(files_to_process)

    def load_first_file(self):
        """Selects and loads the first file in the file list."""
        if self.file_list_frame.get_file_count() > 0:
            first_file_path = self.file_list_frame.get_path_at_index(0)
            if first_file_path:
                print(f"--- EDITOR DEBUG: Auto-loading first file: {first_file_path} ---")
                # Select the item in the listbox
                self.file_list_frame.select_file_at_index(0)
                # Trigger the loading mechanism
                self._on_file_selected_from_list(first_file_path)

    def _on_edit_clicked(self):
        """
        当查看翻译图时，此方法会查找并切换到其原始文件进行编辑。
        """
        current_file = self.file_manager.current_file_path
        if not current_file:
            show_toast(self, "当前没有加载任何文件", level="warning")
            return

        # 如果已经有regions数据，说明已经是编辑模式
        if self.regions_data:
            show_toast(self, "已经是编辑模式。", level="info")
            return

        # 从translation_map.json中查找源文件
        source_file = None
        try:
            # 假设地图在翻译文件的同级目录
            output_dir = os.path.dirname(current_file)
            map_path = os.path.join(output_dir, 'translation_map.json')
            
            if os.path.exists(map_path):
                with open(map_path, 'r', encoding='utf-8') as f:
                    translation_map = json.load(f)
                # 使用规范化路径进行查找
                source_file = translation_map.get(os.path.normpath(current_file))
        except Exception as e:
            show_toast(self, f"查找翻译地图时出错: {e}", level="error")
            return

        if source_file and os.path.exists(source_file):
            # 关键步骤：在加载前，先更新内部文件列表状态
            self.set_file_lists([source_file], [current_file])

            show_toast(self, f"正在加载原图 {os.path.basename(source_file)} 进行编辑...", level="info")
            # 加载原图，这将触发_on_image_loaded并加载JSON
            self.file_manager.load_image_from_path(source_file)
        else:
            show_toast(self, "在翻译地图中未找到对应的源文件。", level="warning")

    def _on_file_unload(self, file_path: str):
        """处理文件卸载请求"""
        try:
            from tkinter import messagebox
            file_name = os.path.basename(file_path)

            # Check for unsaved changes only if we are in edit mode (i.e., a source file is loaded)
            if self._has_unsaved_changes() and self.file_manager.current_file_path in self.source_files:
                result = messagebox.askyesno(
                    "应用更改?",
                    f"您对 {os.path.basename(self.file_manager.current_file_path)} 进行了修改。是否应用更改并覆盖翻译后的图片 {file_name}？"
                )

                if result: # Yes, apply changes
                    # The output path is the translated file path from the list that the user right-clicked on
                    output_path = file_path
                    show_toast(self, f"正在应用更改并覆盖 {os.path.basename(output_path)}...", level="info")
                    
                    # The async task will handle exporting, and then unloading
                    self.async_service.submit_task(self._async_export_and_unload(output_path, file_path))
                    return # Let the async task handle the final unload

            # If no changes or user selected "No", proceed with normal unload
            self.perform_unload(file_path)
        except Exception as e:
            print(f"Error in _on_file_unload: {e}")
            traceback.print_exc()
            # Fallback to just unloading
            self.perform_unload(file_path)

    def perform_unload(self, file_path: str):
        """Helper function to actually perform the unload operation."""
        try:
            print(f"\n=== UNLOAD DEBUG START ===")
            print(f"要卸载的文件: {file_path}")
            print(f"当前显示文件: {getattr(self.file_manager, 'current_file_path', None)}")
            print(f"source_files: {self.source_files}")
            print(f"translated_files: {self.translated_files}")

            is_translated = file_path in self.translated_files
            is_source = file_path in self.source_files

            print(f"is_translated: {is_translated}, is_source: {is_source}")

            # 保存当前状态
            current_file = getattr(self.file_manager, 'current_file_path', None)

            # 检查是否需要清空编辑器（在删除之前检查）
            should_clear_editor = False

            # 标准化路径以进行比较
            normalized_file_path = os.path.normpath(file_path)
            normalized_current_file = os.path.normpath(current_file) if current_file else None

            # 情况1：直接卸载当前显示的文件
            if normalized_current_file and normalized_current_file == normalized_file_path:
                should_clear_editor = True
                print(f"情况1: 直接卸载当前显示的文件")

            # 情况2：卸载翻译图，但当前显示的是对应的源图（编辑模式）
            elif is_translated and normalized_current_file:
                print(f"检查情况2: 卸载翻译图，当前显示文件是否为对应源图")
                try:
                    corresponding_source = None
                    output_dir = os.path.dirname(file_path)
                    map_path = os.path.join(output_dir, 'translation_map.json')
                    if os.path.exists(map_path):
                        with open(map_path, 'r', encoding='utf-8') as f:
                            translation_map = json.load(f)
                        # Use normpath for lookup to match the key format
                        corresponding_source = translation_map.get(os.path.normpath(file_path))

                    if corresponding_source:
                        normalized_corresponding_source = os.path.normpath(corresponding_source)
                        print(f"对应的源图 (来自地图): {corresponding_source}")
                        print(f"标准化后比较: {normalized_current_file} vs {normalized_corresponding_source}")
                        if normalized_current_file == normalized_corresponding_source:
                            should_clear_editor = True
                            print(f"匹配! 检测到卸载翻译图 {os.path.basename(file_path)}，当前编辑的源图 {os.path.basename(current_file)} 对应此翻译图，将清空编辑器")
                        else:
                            print(f"不匹配: 当前文件 {normalized_current_file} != 对应源图 {normalized_corresponding_source}")
                    else:
                        print(f"在 translation_map.json 中未找到 {file_path} 的源图")
                except Exception as e:
                    print(f"查找翻译地图时出错: {e}")
                    pass

            # 情况3：卸载源图，但当前显示的是对应的翻译图
            elif is_source and normalized_current_file:
                print(f"检查情况3: 卸载源图，当前显示文件是否为对应翻译图")
                try:
                    source_idx = self.source_files.index(file_path)
                    print(f"源图索引: {source_idx}")
                    if source_idx < len(self.translated_files):
                        corresponding_trans = self.translated_files[source_idx]
                        normalized_corresponding_trans = os.path.normpath(corresponding_trans)
                        print(f"对应的翻译图: {corresponding_trans}")
                        print(f"标准化后比较: {normalized_current_file} vs {normalized_corresponding_trans}")
                        if normalized_current_file == normalized_corresponding_trans:
                            should_clear_editor = True
                            print(f"匹配! 需要清空编辑器")
                        else:
                            print(f"不匹配: 当前文件 {normalized_current_file} != 对应翻译图 {normalized_corresponding_trans}")
                    else:
                        print(f"索引超出范围: {source_idx} >= {len(self.translated_files)}")
                except (ValueError, IndexError) as e:
                    print(f"异常: {e}")
                    pass
            else:
                print(f"未匹配任何情况")

            print(f"should_clear_editor: {should_clear_editor}")

            # --- 执行卸载操作 ---
            source_to_remove = None
            translated_to_remove = None
            norm_file_path = os.path.normpath(file_path)

            # 确定要删除的完整文件对
            if is_translated:
                translated_to_remove = file_path
                try:
                    output_dir = os.path.dirname(norm_file_path)
                    map_path = os.path.join(output_dir, 'translation_map.json')
                    if os.path.exists(map_path):
                        with open(map_path, 'r', encoding='utf-8') as f:
                            t_map = json.load(f)
                        source_to_remove = t_map.get(norm_file_path)
                except Exception:
                    pass # 忽略地图读取错误
            elif is_source:
                source_to_remove = file_path
                # 通过遍历查找对应的翻译文件
                try:
                    found = False
                    for f in self.translated_files:
                        output_dir = os.path.dirname(os.path.normpath(f))
                        map_path = os.path.join(output_dir, 'translation_map.json')
                        if os.path.exists(map_path):
                            with open(map_path, 'r', encoding='utf-8') as f:
                                t_map = json.load(f)
                            for trans, src in t_map.items():
                                if os.path.normpath(src) == norm_file_path:
                                    translated_to_remove = trans
                                    found = True
                                    break
                        if found: break
                except Exception:
                    pass

            # 为提示消息收集将要被移除的文件
            files_to_remove = []
            if source_to_remove:
                files_to_remove.append(source_to_remove)
            if translated_to_remove:
                files_to_remove.append(translated_to_remove)

            # 从内部列表中精确移除（按值移除）
            if translated_to_remove and translated_to_remove in self.translated_files:
                self.translated_files.remove(translated_to_remove)
                print(f"从translated_files中移除了: {translated_to_remove}")
            
            if source_to_remove and source_to_remove in self.source_files:
                self.source_files.remove(source_to_remove)
                print(f"从source_files中移除了: {source_to_remove}")

            # 清理可能被污染的列表项
            if translated_to_remove and translated_to_remove in self.source_files:
                self.source_files.remove(translated_to_remove)
                print(f"从source_files中清理了污染的翻译文件: {translated_to_remove}")
            if source_to_remove and source_to_remove in self.translated_files:
                self.translated_files.remove(source_to_remove)
                print(f"从translated_files中清理了污染的源文件: {source_to_remove}")

            # 从UI列表中移除 (file_path 是用户右键点击的文件)
            self.file_list_frame.remove_file(file_path)
            print(f"从UI列表中移除了: {file_path}")

            # 如果需要清空编辑器
            if should_clear_editor:
                print(f"执行清空编辑器...")
                self._clear_editor()
                print("已清空编辑器状态")

                # 如果还有其他文件，加载第一个有效的文件
                next_file_to_load = None
                if self.translated_files:
                    for f in self.translated_files:
                        if f:
                            next_file_to_load = f
                            break
                
                if not next_file_to_load and self.source_files:
                    for f in self.source_files:
                        if f:
                            next_file_to_load = f
                            break

                if next_file_to_load:
                    print(f"加载下一个文件: {next_file_to_load}")
                    self._on_file_selected_from_list(next_file_to_load)
                else:
                    print("没有其他文件可加载")
            else:
                print("不需要清空编辑器")

            file_names = [os.path.basename(f) for f in files_to_remove if f != file_path]
            if file_names:
                show_toast(self, f"已卸载文件: {os.path.basename(file_path)} 及关联文件: {', '.join(file_names)}", level="success")
            else:
                show_toast(self, f"已卸载文件: {os.path.basename(file_path)}", level="success")

            print(f"=== UNLOAD DEBUG END ===\n")

        except Exception as e:
            print(f"Error in perform_unload: {e}")
            import traceback
            traceback.print_exc()


    async def _async_export_and_unload(self, output_path: str, file_to_unload: str):
        """Chain export and unload operations."""
        await self._async_export_with_mask(output_path)
        
        # Give some time for the file to be written
        await asyncio.sleep(0.5)

        # Now, unload from the UI thread
        self.after(0, self.perform_unload, file_to_unload)
            
    def _clear_editor(self):
        """清空编辑器状态"""
        self.image = None
        self.regions_data = []
        self.selected_indices = []
        self.raw_mask = None
        self.refined_mask = None
        self.inpainted_image = None
        self.inpainting_in_progress = False
        self.original_size = None
        
        if hasattr(self, 'history_manager'):
            self.history_manager.clear()
            self._update_history_buttons()
        
        # 清空画布
        self.canvas_frame.clear_image()
        self.canvas_frame.set_regions([])
        self.canvas_frame.set_mask(None)
        self.canvas_frame.set_refined_mask(None)
        self.canvas_frame.set_inpainted_image(None)
        
        # 清空属性面板
        self.property_panel.clear_panel()


        
        print("编辑器状态已清空")

    def _release_gpu_memory(self):
        """尝试通过垃圾回收和清空CUDA缓存来释放GPU内存"""
        try:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                print("CUDA cache cleared.")
        except Exception as e:
            print(f"Error while releasing GPU memory: {e}")

    def _load_files_from_dialog(self):
        files = filedialog.askopenfilenames(title="选择图片文件", filetypes=[("Image Files", "*.png *.jpg *.jpeg *.bmp *.gif *.webp")])
        if files:
            self._add_files_to_list(list(files))

    def _load_folder_from_dialog(self):
        folder = filedialog.askdirectory(title="选择文件夹")
        if folder:
            files = [os.path.join(folder, f) for f in sorted(os.listdir(folder)) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'))]
            self._add_files_to_list(files)

    def _add_files_to_list(self, file_paths: List[str]):
        """
        Rigorously finds file pairs and adds them to the internal lists and UI.
        This is the new unified and cumulative file adding logic.
        """
        existing_sources_norm = [os.path.normpath(f) for f in self.source_files]
        existing_trans_norm = [os.path.normpath(f) for f in self.translated_files if f]
        
        new_ui_files = []
        files_added_to_internal_lists = False

        for file_path in file_paths:
            norm_path = os.path.normpath(file_path)
            
            # Skip if this exact path is already in either list
            if norm_path in existing_sources_norm or norm_path in existing_trans_norm:
                continue

            source_to_add, translated_to_add = self._find_file_pair(file_path)

            if source_to_add:
                norm_src = os.path.normpath(source_to_add)
                if norm_src not in existing_sources_norm:
                    self.source_files.append(source_to_add)
                    self.translated_files.append(translated_to_add) # Can be None
                    existing_sources_norm.append(norm_src)
                    if translated_to_add:
                        existing_trans_norm.append(os.path.normpath(translated_to_add))

                    file_for_ui = translated_to_add if translated_to_add else source_to_add
                    new_ui_files.append(file_for_ui)
                    files_added_to_internal_lists = True

        if new_ui_files:
            self.file_list_frame.add_files(new_ui_files)
        
        # If we added files and nothing is displayed yet, load the first new one
        if files_added_to_internal_lists and not self.image and new_ui_files:
            self._on_file_selected_from_list(new_ui_files[0])

    def _show_context_menu(self, event):
        self.last_mouse_event = event
        self.context_menu.show_menu(event, len(self.selected_indices))

    

    def _enter_drawing_mode(self):
        print("--- DEBUG: Entering drawing mode.")
        # Clear any existing selection before drawing a new box
        if self.selected_indices:
            self._on_region_selected([])
        self.canvas_frame.mouse_handler.set_mode('draw')

    def _enter_geometry_edit_mode(self):
        print(f"--- DEBUG: _enter_geometry_edit_mode called, selected_indices: {self.selected_indices}")
        print(f"--- DEBUG: canvas_frame.mouse_handler.selected_indices: {self.canvas_frame.mouse_handler.selected_indices}")
        
        # 同步选中状态，确保两边一致
        if hasattr(self.canvas_frame.mouse_handler, 'selected_indices'):
            mouse_handler_selected = self.canvas_frame.mouse_handler.selected_indices
            if mouse_handler_selected and len(mouse_handler_selected) == 1:
                # 使用mouse_handler的选中状态
                self.selected_indices = list(mouse_handler_selected)
                print(f"--- DEBUG: Synced selected_indices to: {self.selected_indices}")
        
        if len(self.selected_indices) == 1:
            print("--- DEBUG: Entering geometry edit mode.")
            self.canvas_frame.mouse_handler.set_mode('geometry_edit')
            # 强制重绘以确保蓝色框显示
            print(f"--- DEBUG: Forcing redraw with selected_indices: {self.selected_indices}")
            self.canvas_frame.redraw_canvas()
        else:
            print(f"--- DEBUG: Cannot enter geometry edit mode. Selected count: {len(self.selected_indices)}")
            show_toast(self, "请选择一个文本框来编辑其形状。", level="info")

    def _on_geometry_added(self, region_index, new_polygon_world):
        print("\n\n--- DEBUGGING _on_geometry_added ---")
        if region_index >= len(self.regions_data):
            print(f"--- DEBUG: Invalid region_index {region_index}. Aborting. ---")
            return

        region_data = self.regions_data[region_index]
        old_data_for_history = copy.deepcopy(region_data)
        
        old_angle = region_data.get('angle', 0)
        old_lines_model = region_data.get('lines', [])
        
        old_center = region_data.get('center')
        if not old_center:
            all_old_model_points = [tuple(p) for poly in old_lines_model for p in poly]
            old_center = editing_logic.get_polygon_center(all_old_model_points) if all_old_model_points else (0,0)

        # Convert the new world-space polygon to the existing model space
        new_polygon_model = [
            list(editing_logic.rotate_point(p[0], p[1], -old_angle, old_center[0], old_center[1]))
            for p in new_polygon_world
        ]

        # Add the new model-space polygon to the region's lines
        region_data['lines'].append(new_polygon_model)

        # The center and angle of the region should not change when adding a new polygon

        # Recalculate direction based on the new shape
        try:
            temp_text_block = TextBlock(**region_data)
            new_direction = temp_text_block.direction
            region_data['direction'] = new_direction
        except Exception as e:
            print(f"--- DEBUG: Failed to recalculate direction: {e}")

        # Save history and update UI
        self.history_manager.save_state(ActionType.RESIZE, region_index, old_data_for_history, self.regions_data[region_index])
        self._update_canvas_regions()
        self._update_history_buttons()
        print("--- DEBUGGING END ---\n\n")

    def _on_mask_tool_changed(self, tool: str):
        self.mask_edit_mode = tool
        if tool in ["画笔", "橡皮擦"]:
            self.canvas_frame.mouse_handler.set_mode('mask_edit')
        else:
            self.canvas_frame.mouse_handler.set_mode('pan') # Or whatever the default mode is

    def _on_brush_size_changed(self, size: str):
        self.mask_brush_size = int(size)
        self.canvas_frame.mouse_handler.set_brush_size(self.mask_brush_size)

    def _on_toggle_mask_visibility(self, value):
        self.canvas_frame.set_mask_visibility(value)

    def _on_toggle_removed_mask_visibility(self, value):
        """切换被优化掉区域的显示"""
        self.canvas_frame.set_removed_mask_visibility(value)

    def _update_mask_with_config(self):
        """根据最新配置参数更新蒙版，保留用户的手动编辑"""
        self._save_mask_settings_to_config()
        if self.refined_mask is None:
            show_toast(self, "请先生成初始蒙版", level="warning")
            return
        
        # 保存当前用户编辑的蒙版状态
        current_edited_mask = self.refined_mask.copy()
        
        # 获取最新的完整配置
        latest_config = self.config_service.get_config()
        
        # 异步更新蒙版，并传递最新配置
        self.async_service.submit_task(self._update_refined_mask_with_config(current_edited_mask))

    def _load_mask_settings_from_config(self):
        """从配置服务加载蒙版设置并更新UI"""
        try:
            config = self.config_service.get_config()
            
            # 从顶级配置获取参数，而不是OCR配置
            dilation = config.get('mask_dilation_offset', 20)
            kernel = config.get('kernel_size', 3)
            ignore_bubble = config.get('ocr', {}).get('ignore_bubble', 0)  # ignore_bubble仍然在OCR中
            
            self.property_panel.widgets['mask_dilation_offset_entry'].delete(0, "end")
            self.property_panel.widgets['mask_dilation_offset_entry'].insert(0, str(dilation))
            
            self.property_panel.widgets['mask_kernel_size_entry'].delete(0, "end")
            self.property_panel.widgets['mask_kernel_size_entry'].insert(0, str(kernel))
            
            if ignore_bubble:
                self.property_panel.widgets['ignore_bubble_checkbox'].select()
            else:
                self.property_panel.widgets['ignore_bubble_checkbox'].deselect()
        except Exception as e:
            print(f"Error loading mask settings to UI: {e}")

    def _save_mask_settings_to_config(self):
        """从UI获取蒙版设置并保存到配置"""
        try:
            config = self.config_service.get_config()
            
            # 保存到顶级配置，而不是OCR配置
            config['mask_dilation_offset'] = int(self.property_panel.widgets['mask_dilation_offset_entry'].get() or 20)
            config['kernel_size'] = int(self.property_panel.widgets['mask_kernel_size_entry'].get() or 3)
            
            # ignore_bubble 仍然保存在OCR配置中
            ocr_config = config.setdefault('ocr', {})
            ocr_config['ignore_bubble'] = self.property_panel.widgets['ignore_bubble_checkbox'].get()
            
            self.config_service.set_config(config)
            self.config_service.save_config_file()
            print("Mask settings saved to config file.")
        except (ValueError, TypeError) as e:
            print(f"Error saving mask settings: Invalid value. {e}")
        except Exception as e:
            print(f"Error saving mask settings: {e}")

    def _on_mask_setting_changed(self, event=None):
        """蒙版设置UI控件的回调函数"""
        self._save_mask_settings_to_config()
    
    async def _update_refined_mask_with_config(self, edited_mask: np.ndarray):
        """异步更新蒙版的实现"""
        try:
            if self.image is None or self.raw_mask is None:
                show_toast(self, "图片或原始蒙版不存在", level="error")
                return
                
            show_toast(self, "正在更新蒙版...", level="info")
            
            # 重新生成基础精细蒙版
            image_np = np.array(self.image.convert("RGB"))
            text_blocks = [TextBlock(**region_data) for region_data in self.regions_data]
            
            if len(self.raw_mask.shape) == 3:
                raw_mask_2d = cv2.cvtColor(self.raw_mask, cv2.COLOR_BGR2GRAY)
            else:
                raw_mask_2d = self.raw_mask
            raw_mask_contiguous = np.ascontiguousarray(raw_mask_2d, dtype=np.uint8)
            
            # 获取最新的配置参数
            config = self.config_service.get_config()
            
            # 从顶级配置获取参数
            kernel_size = config.get('kernel_size', 3)
            mask_dilation_offset = config.get('mask_dilation_offset', 20)
            
            # ignore_bubble 仍然从OCR配置获取
            ocr_config = config.get('ocr', {})
            ignore_bubble = ocr_config.get('ignore_bubble', 0)
            
            # --- DEBUG: 打印将要传递给后端的蒙版偏移值 (更新蒙版时) ---
            print(f"--- MASK_DEBUG (UPDATE): Preparing to refine mask with dilation_offset: {mask_dilation_offset} ---")

            print(f"更新蒙版使用配置: kernel_size={kernel_size}, ignore_bubble={ignore_bubble}, dilation_offset={mask_dilation_offset}")
            
            # 生成新的基础蒙版
            new_base_mask = await refine_mask_dispatch(
                text_blocks, 
                image_np, 
                raw_mask_contiguous,
                method='fit_text', 
                dilation_offset=mask_dilation_offset, 
                ignore_bubble=ignore_bubble,
                kernel_size=kernel_size
            )
            
            if new_base_mask is not None:
                # 计算被优化掉的区域（原始蒙版有但新蒙版没有的区域）
                if self.raw_mask is not None:
                    if len(self.raw_mask.shape) == 3:
                        raw_mask_2d = cv2.cvtColor(self.raw_mask, cv2.COLOR_BGR2GRAY)
                    else:
                        raw_mask_2d = self.raw_mask
                    
                    # 确保两个蒙版尺寸一致
                    if raw_mask_2d.shape != new_base_mask.shape:
                        print(f"警告: 原始蒙版尺寸 {raw_mask_2d.shape} 与新蒙版尺寸 {new_base_mask.shape} 不匹配，调整尺寸...")
                        raw_mask_2d = cv2.resize(raw_mask_2d, (new_base_mask.shape[1], new_base_mask.shape[0]), interpolation=cv2.INTER_NEAREST)
                    
                    # 计算被移除的区域：原始蒙版中的白色区域减去新蒙版中的白色区域
                    raw_mask_binary = (raw_mask_2d > 127).astype(np.uint8)
                    new_mask_binary = (new_base_mask > 127).astype(np.uint8)
                    self.removed_mask = np.maximum(0, raw_mask_binary - new_mask_binary) * 255
                
                # 简化逻辑：直接使用新的基础蒙版，但尝试保留明显的用户编辑
                if edited_mask.shape == new_base_mask.shape:
                    # 生成一个参考蒙版用于比较用户编辑
                    ref_mask = await refine_mask_dispatch(
                        text_blocks, 
                        image_np, 
                        raw_mask_contiguous,
                        method='fit_text', 
                        dilation_offset=0,  # 使用默认参数作为参考
                        ignore_bubble=0,
                        kernel_size=3
                    )
                    
                    if ref_mask is not None:
                        # 检测用户手动编辑的区域（与参考蒙版差异较大的地方）
                        diff = np.abs(edited_mask.astype(np.int16) - ref_mask.astype(np.int16))
                        user_edit_regions = (diff > 50).astype(np.uint8)  # 阈值可调整
                        
                        # 在用户编辑区域保留原编辑，其他区域使用新蒙版
                        final_mask = new_base_mask.copy()
                        final_mask[user_edit_regions > 0] = edited_mask[user_edit_regions > 0]
                        
                        self.refined_mask = final_mask
                    else:
                        self.refined_mask = new_base_mask
                else:
                    self.refined_mask = new_base_mask
                
                # 保存到历史记录
                self.history_manager.save_state(
                    ActionType.EDIT_MASK, 
                    0, 
                    edited_mask, 
                    self.refined_mask.copy(), 
                    description="Update Mask Config"
                )
                
                # 更新显示
                self.canvas_frame.set_refined_mask(self.refined_mask)
                if hasattr(self.canvas_frame, 'set_removed_mask'):
                    self.canvas_frame.set_removed_mask(self.removed_mask)
                self._update_history_buttons()
                
                show_toast(self, "蒙版已根据最新配置更新！", level="success")
            else:
                show_toast(self, "蒙版更新失败", level="error")
                
        except Exception as e:
            print(f"更新蒙版失败: {e}")
            import traceback
            traceback.print_exc()
            show_toast(self, f"更新蒙版失败: {e}", level="error")
        finally:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _on_mask_edit_start(self):
        if self.refined_mask is not None:
            self.mask_edit_start_state = self.refined_mask.copy()

    def _on_mask_edit_end(self, points: List[Tuple[int, int]]):
        if self.refined_mask is not None and self.mask_edit_start_state is not None:
            # Calculate the brush size in image space by accounting for zoom
            # Use int() instead of int(round()) to make the line slightly thinner to compensate for anti-aliasing perception.
            brush_thickness = int(self.mask_brush_size / self.transform_service.zoom_level)
            brush_thickness = max(1, brush_thickness) # Ensure thickness is at least 1

            for i in range(len(points) - 1):
                p1 = (int(points[i][0]), int(points[i][1]))
                p2 = (int(points[i+1][0]), int(points[i+1][1]))
                color = 255 if self.mask_edit_mode == "画笔" else 0
                cv2.line(self.refined_mask, p1, p2, color, brush_thickness, cv2.LINE_AA)
            
            self.history_manager.save_state(ActionType.EDIT_MASK, 0, self.mask_edit_start_state, self.refined_mask.copy(), description="Mask Edit")
            self.mask_edit_start_state = None
            self.canvas_frame.set_refined_mask(self.refined_mask)
            self._update_history_buttons()
            # Trigger immediate inpainting preview
            if self.refined_mask is not None:
                self.async_service.submit_task(self._generate_inpainted_preview(mask_to_use=self.refined_mask.copy()))

    def _on_mask_draw_preview(self, points: List[Tuple[int, int]]):
        self.canvas_frame.draw_mask_preview(points, self.mask_brush_size, self.mask_edit_mode)

    def _on_display_mode_changed(self, choice: str):
        # print(f"--- DEBUG: Entering _on_display_mode_changed with choice: {choice} ---")
        # When switching away from mask view, reset the tool selection.
        self.mask_edit_mode = "不选择"
        self.canvas_frame.mouse_handler.set_mode('select')

        self.canvas_frame.set_view_mode('normal')

        if choice == "文字文本框显示":
            self.canvas_frame.set_text_visibility(True)
            self.canvas_frame.set_boxes_visibility(True)
        elif choice == "只显示文字":
            self.canvas_frame.set_text_visibility(True)
            self.canvas_frame.set_boxes_visibility(False)
        elif choice == "只显示框线":
            self.canvas_frame.set_text_visibility(False)
            self.canvas_frame.set_boxes_visibility(True)
        elif choice == "都不显示":
            self.canvas_frame.set_text_visibility(False)
            self.canvas_frame.set_boxes_visibility(False)

    def _on_preview_alpha_changed(self, alpha_value):
        alpha_float = alpha_value / 100.0
        self.canvas_frame.set_inpainted_alpha(alpha_float)

    def _render_inpainted_image(self):
        if self.inpainting_in_progress:
            show_toast(self, "渲染已经在进行中...", level="info")
            return
        
        # 如果没有蒙版，先生成蒙版
        if self.refined_mask is None:
            show_toast(self, "正在生成蒙版...", level="info")
            self.async_service.submit_task(self._generate_refined_mask_then_render())
            return

        self.inpainting_in_progress = True
        show_toast(self, "正在生成预览...", level="info")
        
        # 创建蒙版的副本以避免数据竞争
        mask_copy = self.refined_mask.copy()
        self.async_service.submit_task(self._generate_inpainted_preview(mask_to_use=mask_copy))

    async def _generate_refined_mask_then_render(self):
        """生成蒙版然后自动渲染"""
        try:
            # 先生成蒙版
            await self._generate_refined_mask()
            
            # 如果蒙版生成成功，自动开始渲染
            if self.refined_mask is not None:
                show_toast(self, "蒙版生成完成，开始渲染...", level="info")
                self.inpainting_in_progress = True
                mask_copy = self.refined_mask.copy()
                await self._generate_inpainted_preview(mask_to_use=mask_copy)
            else:
                show_toast(self, "蒙版生成失败，无法渲染", level="error")
                
        except Exception as e:
            print(f"生成蒙版并渲染失败: {e}")
            show_toast(self, f"操作失败: {e}", level="error")
            self.inpainting_in_progress = False

    async def _generate_refined_mask(self):
        try:
            if self.image is None or self.raw_mask is None or self.raw_mask.size == 0 or self.raw_mask.ndim < 2:
                print("Error: Image or raw mask not loaded, empty, or not at least 2D.")
                return

            image_np = np.array(self.image.convert("RGB"))
            text_blocks = [TextBlock(**region_data) for region_data in self.regions_data]

            if len(self.raw_mask.shape) == 3:
                raw_mask_2d = cv2.cvtColor(self.raw_mask, cv2.COLOR_BGR2GRAY)
            else:
                raw_mask_2d = self.raw_mask
            raw_mask_contiguous = np.ascontiguousarray(raw_mask_2d, dtype=np.uint8)
            
            # 从配置服务获取蒙版精细化参数
            config = self.config_service.get_config()
            
            # 从顶级配置获取参数
            kernel_size = config.get('kernel_size', 3)
            mask_dilation_offset = config.get('mask_dilation_offset', 20)
            
            # ignore_bubble 仍然从OCR配置获取
            ocr_config = config.get('ocr', {})
            ignore_bubble = ocr_config.get('ignore_bubble', 0)

            # --- DEBUG: 打印将要传递给后端的蒙版偏移值 ---
            print(f"--- MASK_DEBUG: Preparing to refine mask with dilation_offset: {mask_dilation_offset} ---")
            
            print(f"使用蒙版精细化配置: kernel_size={kernel_size}, ignore_bubble={ignore_bubble}, dilation_offset={mask_dilation_offset}")
            
            self.refined_mask = await refine_mask_dispatch(
                text_blocks, 
                image_np, 
                raw_mask_contiguous,
                method='fit_text', 
                dilation_offset=mask_dilation_offset, 
                ignore_bubble=ignore_bubble,
                kernel_size=kernel_size
            )

            if self.refined_mask is not None:
                print(f"DEBUG: Mask generated. ID: {id(self.refined_mask)}, Sum: {np.sum(self.refined_mask)}")
                
                # 计算被优化掉的区域（原始蒙版有但新蒙版没有的区域）
                if self.raw_mask is not None:
                    if len(self.raw_mask.shape) == 3:
                        raw_mask_2d_for_removed = cv2.cvtColor(self.raw_mask, cv2.COLOR_BGR2GRAY)
                    else:
                        raw_mask_2d_for_removed = self.raw_mask
                    
                    # 确保两个蒙版尺寸一致
                    if raw_mask_2d_for_removed.shape != self.refined_mask.shape:
                        print(f"警告: 原始蒙版尺寸 {raw_mask_2d_for_removed.shape} 与精细蒙版尺寸 {self.refined_mask.shape} 不匹配，调整尺寸...")
                        raw_mask_2d_for_removed = cv2.resize(raw_mask_2d_for_removed, (self.refined_mask.shape[1], self.refined_mask.shape[0]), interpolation=cv2.INTER_NEAREST)
                    
                    # 计算被移除的区域：原始蒙版中的白色区域减去新蒙版中的白色区域
                    raw_mask_binary = (raw_mask_2d_for_removed > 127).astype(np.uint8)
                    new_mask_binary = (self.refined_mask > 127).astype(np.uint8)
                    self.removed_mask = np.maximum(0, raw_mask_binary - new_mask_binary) * 255
                    
                    # 设置到canvas
                    self.canvas_frame.set_removed_mask(self.removed_mask)
                
                self.canvas_frame.set_refined_mask(self.refined_mask)
                show_toast(self, "蒙版生成完毕！", level="success")
            else:
                show_toast(self, "蒙版生成失败", level="error")

        except Exception as e:
            print(f"Error generating refined mask: {e}")
            traceback.print_exc()
            show_toast(self, f"蒙版生成失败: {e}", level="error")
        finally:
            self.toolbar.set_render_button_state("normal")
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    async def _generate_inpainted_preview(self, mask_to_use: np.ndarray):
        try:
            if self.image is None:
                print("Error: Image not loaded.")
                return

            if mask_to_use is None:
                show_toast(self, "没有有效的蒙版可供渲染", "error")
                return

            image_np = np.array(self.image.convert("RGB"))
            
            # 从配置服务获取inpainter配置
            config = self.config_service.get_config()
            inpainter_config_dict = config.get('inpainter', {})
            
            # 创建InpainterConfig实例并应用配置
            inpainter_config = InpainterConfig()
            if 'inpainting_precision' in inpainter_config_dict:
                inpainter_config.inpainting_precision = InpaintPrecision(inpainter_config_dict['inpainting_precision'])
            
            # 从配置获取inpainter模型
            inpainter_name = inpainter_config_dict.get('inpainter', 'lama_large')
            try:
                inpainter_key = Inpainter(inpainter_name)
            except ValueError:
                print(f"未知的inpainter模型: {inpainter_name}，使用默认的lama_large")
                inpainter_key = Inpainter.lama_large
            
            # 从配置获取inpainting尺寸
            inpainting_size = inpainter_config_dict.get('inpainting_size', 1024)
            
            # 从配置获取GPU设置
            cli_config = config.get('cli', {})
            use_gpu = cli_config.get('use_gpu', False)
            device = 'cuda' if use_gpu else 'cpu'
            
            print(f"使用inpainter配置: 模型={inpainter_key.value}, 尺寸={inpainting_size}, 设备={device}")

            inpainted_image_np = await inpaint_dispatch(
                inpainter_key=inpainter_key, 
                image=image_np, 
                mask=mask_to_use,
                config=inpainter_config,
                inpainting_size=inpainting_size, 
                device=device 
            )
            
            self.inpainted_image = Image.fromarray(inpainted_image_np)

            self.canvas_frame.set_inpainted_image(self.inpainted_image)
            self.canvas_frame.set_inpainted_alpha(1.0)
            self.toolbar.preview_slider.set(100)
            show_toast(self, "预览生成完毕！", level="success")

        except Exception as e:
            print(f"Error generating inpainting preview: {e}")
            traceback.print_exc()
            show_toast(self, f"预览生成失败: {e}", level="error")
        finally:
            self.inpainting_in_progress = False
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def _zoom_in(self):
        center_x = self.canvas_frame.canvas.winfo_width() / 2
        center_y = self.canvas_frame.canvas.winfo_height() / 2
        self.transform_service.zoom(1.2, center_x, center_y)

    def _zoom_out(self):
        center_x = self.canvas_frame.canvas.winfo_width() / 2
        center_y = self.canvas_frame.canvas.winfo_height() / 2
        self.transform_service.zoom(1 / 1.2, center_x, center_y)

    def _fit_to_window(self):
        self.canvas_frame.after(50, self.canvas_frame.fit_to_window)

    def _on_transform_changed(self):
        zoom = self.transform_service.zoom_level
        self.toolbar.update_zoom_level(zoom)
        self.canvas_frame.redraw_canvas()

    def _select_all_regions(self):
        self.selected_indices = list(range(len(self.regions_data)))
        self._on_region_selected(self.selected_indices)

    def _copy_selected_regions(self):
        if self.selected_indices:
            last_selected_index = self.selected_indices[-1]
            region_data = self.regions_data[last_selected_index]
            self.history_manager.copy_to_clipboard(region_data)
            show_toast(self, f"Region {last_selected_index} copied.", level="info")

    def _on_paste_shortcut(self, event=None):
        if self.selected_indices:
            self._paste_style_to_selected()
        else:
            self._paste_region(event)

    def _paste_region(self, event=None):
        clipboard_data = self.history_manager.paste_from_clipboard()
        if not clipboard_data: return
        if event and hasattr(event, 'x'):
            self.last_mouse_event = event

        if self.last_mouse_event:
            paste_x_img, paste_y_img = self.transform_service.screen_to_image(self.last_mouse_event.x, self.last_mouse_event.y)
        else:
            canvas_width = self.canvas_frame.canvas.winfo_width()
            canvas_height = self.canvas_frame.canvas.winfo_height()
            paste_x_img, paste_y_img = self.transform_service.screen_to_image(canvas_width / 2, canvas_height / 2)

        new_region = copy.deepcopy(clipboard_data)
        try:
            all_points = [p for poly in new_region.get('lines', []) for p in poly]
            if not all_points: return
            original_anchor_x = min(p[0] for p in all_points)
            original_anchor_y = min(p[1] for p in all_points)
            offset_x = paste_x_img - original_anchor_x
            offset_y = paste_y_img - original_anchor_y
            for poly in new_region['lines']:
                for point in poly:
                    point[0] += offset_x
                    point[1] += offset_y
            self.regions_data.append(new_region)
            self.history_manager.save_state(ActionType.ADD, len(self.regions_data) - 1, None, new_region)
            self._update_canvas_regions()
            self._update_history_buttons()
        except Exception as e:
            print(f"Error during paste operation: {e}")

    def _paste_style_to_selected(self):
        clipboard_data = self.history_manager.paste_from_clipboard()
        if not clipboard_data or not self.selected_indices: return
        self.history_manager.start_action_group()
        try:
            for index in self.selected_indices:
                target_region = self.regions_data[index]
                old_data = copy.deepcopy(target_region)
                source_lines = copy.deepcopy(clipboard_data.get('lines', []))
                target_lines = target_region.get('lines', [])
                if source_lines and target_lines:
                    source_all_points = [p for poly in source_lines for p in poly]
                    source_anchor_x = min(p[0] for p in source_all_points)
                    source_anchor_y = min(p[1] for p in source_all_points)
                    target_all_points = [p for poly in target_lines for p in poly]
                    target_anchor_x = min(p[0] for p in target_all_points)
                    target_anchor_y = min(p[1] for p in target_all_points)
                    offset_x = target_anchor_x - source_anchor_x
                    offset_y = target_anchor_y - source_anchor_y
                    new_target_lines = [[ [p[0] + offset_x, p[1] + offset_y] for p in poly] for poly in source_lines]
                    target_region['lines'] = new_target_lines

                for key, value in clipboard_data.items():
                    if key not in ['lines']:
                        target_region[key] = copy.deepcopy(value)
                self.history_manager.save_state(ActionType.MODIFY_STYLE, index, old_data, target_region)
            self._update_canvas_regions()
            if len(self.selected_indices) == 1:
                self.property_panel.load_region_data(self.regions_data[self.selected_indices[0]], self.selected_indices[0])
        finally:
            self.history_manager.end_action_group("Paste Style/Shape")
            self._update_history_buttons()

    def _delete_selected_regions(self):
        if not self.selected_indices: return
        self.history_manager.start_action_group()
        try:
            for index in sorted(self.selected_indices, reverse=True):
                old_data = self.regions_data.pop(index)
                self.history_manager.save_state(ActionType.DELETE, index, old_data, None)
            self.selected_indices = []
            self.canvas_frame.mouse_handler.selected_indices = []
            self.property_panel.clear_panel()
            self._update_canvas_regions()
        finally:
            self.history_manager.end_action_group("Delete Regions")
            self._update_history_buttons()

    

    def _ocr_selected_regions(self):
        if not self.selected_indices or self.image is None: return
        self.async_service.submit_task(self._run_ocr_for_selection())

    async def _run_ocr_for_selection(self):
        self.history_manager.start_action_group()
        success_count = 0
        try:
            for index in self.selected_indices:
                region_data = self.regions_data[index]
                
                image_np = np.array(self.image.convert("RGB"))

                # DEBUG: Save the image being sent to OCR
                try:
                    debug_path = os.path.join(os.path.dirname(__file__), 'debug_ocr_input.png')
                    cv2.imwrite(debug_path, cv2.cvtColor(image_np, cv2.COLOR_RGB2BGR))
                    print(f"--- OCR DEBUG: Saved image for OCR to {debug_path} ---")
                except Exception as e:
                    print(f"--- OCR DEBUG: Failed to save debug image: {e} ---")

                result = await self.ocr_service.recognize_region(image_np, region_data)
                if result and result.text:
                    old_data = copy.deepcopy(region_data)
                    region_data['text'] = result.text
                    self.history_manager.save_state(ActionType.MODIFY_TEXT, index, old_data, self.regions_data[index])
                    success_count += 1
        finally:
            self.history_manager.end_action_group("OCR")
            self._update_history_buttons()
        if success_count > 0:
            show_toast(self, f"OCR successful for {success_count} region(s).", level="success")
            winsound.MessageBeep(winsound.MB_OK)
        self._update_canvas_regions()
        if len(self.selected_indices) == 1:
            self.property_panel.load_region_data(self.regions_data[self.selected_indices[0]], self.selected_indices[0])
    




    def _translate_selected_regions(self):
        if not self.selected_indices: return
        self.async_service.submit_task(self._run_translation_for_selection())

    async def _run_translation_for_selection(self):
        self.history_manager.start_action_group()
        success_count = 0
        try:
            # 收集所有页面的原文以获得上下文
            all_texts = []
            for region_data in self.regions_data:
                text = region_data.get('text', '').strip()
                all_texts.append(text if text else '')
            
            if not any(all_texts):
                print("页面中没有可翻译的文本")
                return
            
            # 批量翻译所有文本（带上下文）
            print(f"正在翻译页面中的 {len([t for t in all_texts if t])} 段文本...")
            translation_results = await self.translation_service.translate_text_batch(
                all_texts,
                image=self.image, 
                regions=self.regions_data
            )
            
            # 只更新选中的区域
            for index in self.selected_indices:
                if index < len(translation_results) and translation_results[index]:
                    result = translation_results[index]
                    if result and result.translated_text:
                        old_data = copy.deepcopy(self.regions_data[index])
                        self.regions_data[index]['translation'] = result.translated_text
                        self.history_manager.save_state(ActionType.MODIFY_TEXT, index, old_data, self.regions_data[index])
                        success_count += 1
                        print(f"翻译成功: '{result.original_text[:30]}...' -> '{result.translated_text[:30]}...'")
            
        except Exception as e:
            print(f"翻译过程中出现错误: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.history_manager.end_action_group("Translate")
            self._update_history_buttons()
        if success_count > 0:
            show_toast(self, f"Translation successful for {success_count} region(s).", level="success")
            winsound.MessageBeep(winsound.MB_OK)
        self._update_canvas_regions()
        if len(self.selected_indices) == 1:
            self.property_panel.load_region_data(self.regions_data[self.selected_indices[0]], self.selected_indices[0])

    def _on_property_panel_text_changed(self):
        if len(self.selected_indices) == 1:
            index = self.selected_indices[0]
            raw_text = self.property_panel.widgets['translation_text'].get("1.0", "end-1c")
            
            # Clean the text before saving
            import re
            text_with_newlines = raw_text.replace('↵', '\n')
            clean_text = re.sub(r'</?H>', '', text_with_newlines, flags=re.IGNORECASE)

            if self.regions_data[index].get('translation') != clean_text:
                old_data = copy.deepcopy(self.regions_data[index])
                self.regions_data[index]['translation'] = clean_text
                self.history_manager.save_state(ActionType.MODIFY_TEXT, index, old_data, self.regions_data[index])
                self._update_canvas_regions()
                self._update_history_buttons()

    def _on_property_panel_original_text_changed(self):
        if len(self.selected_indices) == 1:
            index = self.selected_indices[0]
            new_text = self.property_panel.widgets['original_text'].get("1.0", "end-1c")
            if self.regions_data[index].get('text') != new_text:
                old_data = copy.deepcopy(self.regions_data[index])
                self.regions_data[index]['text'] = new_text
                self.history_manager.save_state(ActionType.MODIFY_TEXT, index, old_data, self.regions_data[index])
                self._update_canvas_regions()
                self._update_history_buttons()

    def _on_property_panel_style_changed(self):
        if len(self.selected_indices) == 1:
            index = self.selected_indices[0]
            old_data = copy.deepcopy(self.regions_data[index])
            
            # Read values from all style widgets
            font_size = int(self.property_panel.widgets['font_size'].get())
            hex_color = self.property_panel.widgets['font_color'].get()
            
            # --- UNIFICATION: Convert hex to RGB tuple ---
            try:
                if hex_color.startswith('#') and len(hex_color) == 7:
                    r = int(hex_color[1:3], 16)
                    g = int(hex_color[3:5], 16)
                    b = int(hex_color[5:7], 16)
                    fg_color_tuple = (r, g, b)
                else:
                    fg_color_tuple = (0, 0, 0) # Default to black on invalid format
            except (ValueError, TypeError):
                fg_color_tuple = (0, 0, 0) # Default to black on error

            alignment_map = {"自动": "auto", "左对齐": "left", "居中": "center", "右对齐": "right"}
            alignment_display = self.property_panel.widgets['alignment'].get()
            alignment = alignment_map.get(alignment_display, "auto")

            direction_map = {"自动": "auto", "横排": "h", "竖排": "v"}
            direction_display = self.property_panel.widgets['direction'].get()
            direction = direction_map.get(direction_display, "auto")

            # Update region data with unified format
            self.regions_data[index]['font_size'] = font_size
            self.regions_data[index]['fg_colors'] = fg_color_tuple # Use the unified key and format (plural)
            if 'font_color' in self.regions_data[index]:
                del self.regions_data[index]['font_color'] # Remove old key
            if 'fg_color' in self.regions_data[index]:
                del self.regions_data[index]['fg_color'] # Remove incorrect singular key if it exists
            self.regions_data[index]['alignment'] = alignment
            self.regions_data[index]['direction'] = direction

            self.history_manager.save_state(ActionType.MODIFY_STYLE, index, old_data, self.regions_data[index])
            self._update_canvas_regions()
            self._update_history_buttons()

    def _on_property_panel_transform_changed(self):
        print("_on_property_panel_transform_changed called")
        if len(self.selected_indices) == 1:
            index = self.selected_indices[0]
            old_data = copy.deepcopy(self.regions_data[index])
            new_angle = float(self.property_panel.widgets['angle'].get())
            
            # 核心修复：只更新角度，不再调用已删除的 rotate_region
            self.regions_data[index]['angle'] = new_angle
            
            self.history_manager.save_state(ActionType.MODIFY_STYLE, index, old_data, self.regions_data[index])
            self._update_canvas_regions()
            self._update_history_buttons()

    def _on_ocr_model_changed(self, model_name: str):
        """处理OCR模型变化"""
        print(f"OCR模型变化: {model_name}")
        
        # 更新配置文件
        config = self.config_service.get_config()
        if config.get('ocr', {}).get('ocr') != model_name:
            config.setdefault('ocr', {})['ocr'] = model_name
            self.config_service.set_config(config)
            self._push_config_to_canvas()
        
        # 更新OCR服务
        self.ocr_service.set_model(model_name)
        
        # 显示确认消息
        try:
            show_toast(self, f"OCR模型已设置为: {model_name}", level="success")
        except Exception as e:
            print(f"显示提示失败: {e}")

    def _on_translator_changed(self, translator_name: str):
        """处理翻译器变化"""
        print(f"翻译器变化: {translator_name}")
        
        # 更新配置文件
        config = self.config_service.get_config()
        if config.get('translator', {}).get('translator') != translator_name:
            config.setdefault('translator', {})['translator'] = translator_name
            self.config_service.set_config(config)
            self._push_config_to_canvas()
        
        # 更新翻译服务
        self.translation_service.set_translator(translator_name)
        
        # 显示确认消息
        try:
            show_toast(self, f"翻译器已设置为: {translator_name}", level="success")
        except Exception as e:
            print(f"显示提示失败: {e}")

    def _on_target_language_changed(self, language_name: str):
        """处理目标语言变化"""
        print(f"目标语言变化: {language_name}")
        
        # 通过属性面板获取语言代码映射
        if hasattr(self.property_panel, 'lang_name_to_code'):
            lang_code = self.property_panel.lang_name_to_code.get(language_name)
            if lang_code:
                # 更新配置文件
                config = self.config_service.get_config()
                if config.get('translator', {}).get('target_lang') != lang_code:
                    config.setdefault('translator', {})['target_lang'] = lang_code
                    self.config_service.set_config(config)
                    self._push_config_to_canvas()
                
                # 更新翻译服务
                self.translation_service.set_target_language(lang_code)
                
                # 显示确认消息
                try:
                    show_toast(self, f"目标语言已设置为: {language_name} ({lang_code})", level="success")
                except Exception as e:
                    print(f"显示提示失败: {e}")
            else:
                print(f"无法找到语言代码: {language_name}")
        else:
            print("属性面板缺少语言代码映射")

    def _export_rendered_image(self):
        """导出后端渲染的图片 - 处理用户交互并启动异步导出任务"""
        self._save_mask_settings_to_config()
        if not self.image or not self.regions_data:
            show_toast(self, "没有图片或区域数据可导出", level="warning")
            return
        
        try:
            # Use export_service to get initial path and config
            from services.export_service import get_export_service
            from tkinter import messagebox

            export_service = get_export_service()
            config = self.config_service.get_config()
            output_format = export_service.get_output_format_from_config(config)

            # 智能判断导出目标
            current_file = getattr(self.file_manager, 'current_file_path', None) or self.current_image_path
            
            if current_file and current_file in self.translated_files:
                # Situation 1: Overwriting a translated file, but respecting the chosen format
                base_name, _ = os.path.splitext(current_file)
                new_extension = f".{output_format}" if output_format else os.path.splitext(current_file)[1]
                output_path = base_name + new_extension
                file_name_for_prompt = os.path.basename(output_path)

                print(f"[EXPORT] Detected translated file. Target path: {output_path}")
                
                # Confirm overwrite
                if not messagebox.askyesno("确认覆盖", f"是否要覆盖/保存为 '{file_name_for_prompt}'？"):
                    show_toast(self, "导出已取消", level="info")
                    return
                    
                show_toast(self, f"正在导出: {file_name_for_prompt}", level="info")
                
            else:
                # 情况2: 当前加载的是源图或其他情况，导出到输出目录
                print(f"[EXPORT] 当前文件不是翻译图，将导出到输出目录")
                output_dir = export_service.get_output_directory()

                if not output_dir:
                    show_toast(self, "请先在主界面设置输出目录", level="error")
                    messagebox.showerror("错误", "未设置输出目录。请返回主界面设置输出目录。")
                    return

                # Generate default filename
                if hasattr(self, 'current_image_path') and self.current_image_path:
                    # 编辑器导出使用原始文件名，不添加前缀
                    default_filename = export_service.generate_output_filename(self.current_image_path, output_format, add_prefix=False)
                else:
                    default_filename = f"image.{output_format or 'png'}"

                output_path = os.path.join(output_dir, default_filename)

                # Check if file exists and ask for overwrite confirmation
                if os.path.exists(output_path):
                    if not messagebox.askyesno("确认覆盖", f"文件 '{default_filename}' 已存在于输出目录中。是否要覆盖它？"):
                        show_toast(self, "导出已取消", level="info")
                        return

            # Submit the actual export process to the async service
            self.async_service.submit_task(self._async_export_with_mask(output_path))
            
        except Exception as e:
            print(f"导出图片失败: {e}")
            traceback.print_exc()
            show_toast(self, f"导出图片失败: {e}", level="error")

    async def _async_export_with_mask(self, output_path: str):
        """Asynchronously handles the export process, including mask generation."""
        try:
            # 1. Ensure a refined mask exists, generating one if necessary.
            if self.refined_mask is None:
                show_toast(self, "未找到优化蒙版，正在自动生成...", level="info")
                await self._generate_refined_mask()
                # After generation, check if it was successful
                if self.refined_mask is None:
                    show_toast(self, "蒙版生成失败，无法导出。", level="error")
                    return

            show_toast(self, "正在导出图片...", level="info")

            # 2. Get services and configuration
            from services.export_service import get_export_service
            export_service = get_export_service()
            config = self.config_service.get_config()

            # 3. Define callbacks for the export service
            def progress_callback(message):
                self.after(0, lambda: show_toast(self, message, level="info"))
            
            def success_callback(message):
                self.after(0, lambda: show_toast(self, message, level="success"))
            
            def error_callback(message):
                self.after(0, lambda: show_toast(self, message, level="error"))

            # 4. Execute export with the refined mask
            export_service.export_rendered_image(
                image=self.image,
                regions_data=self.regions_data,
                config=config,
                output_path=output_path,
                mask=self.refined_mask,  # Pass the refined mask
                progress_callback=progress_callback,
                success_callback=success_callback,
                error_callback=error_callback
            )
        except Exception as e:
            print(f"异步导出图片失败: {e}")
            traceback.print_exc()
            show_toast(self, f"导出图片时发生意外错误: {e}", level="error")
        finally:
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    def reload_config_and_redraw(self):
        """Public method to reload configuration and trigger a full redraw."""
        try:
            config = self.config_service.get_config()
            render_config = config.get('render', {})
            font_filename = render_config.get('font_path')

            if font_filename and self.regions_data:
                full_font_path = os.path.join(os.path.dirname(__file__), '..', 'fonts', font_filename)
                full_font_path = os.path.abspath(full_font_path)
                final_font_path = pathlib.Path(full_font_path).as_posix()

                if os.path.exists(full_font_path):
                    for region in self.regions_data:
                        region['font_family'] = final_font_path
        except Exception as e:
            print(f"[ERROR] Failed to update font properties in regions_data: {e}")

        # Clear the text render cache and update font config
        if hasattr(self, 'canvas_frame') and hasattr(self.canvas_frame, 'renderer') and hasattr(self.canvas_frame.renderer, 'text_renderer'):
            self.canvas_frame.renderer.text_renderer._text_render_cache.clear()
            # 同时更新文本渲染器的字体配置
            if font_filename:
                self.canvas_frame.renderer.text_renderer.update_font_config(font_filename)

        # Push other render configs and redraw
        self._push_config_to_canvas()
        self._update_canvas_regions()

        # Also update the new mask settings UI
        if hasattr(self, '_load_mask_settings_from_config'):
            self._load_mask_settings_from_config()

        # Force reload of property panel to reflect text processing changes
        if self.selected_indices and len(self.selected_indices) == 1:
            index = self.selected_indices[0]
            if index < len(self.regions_data):
                self.property_panel.load_region_data(self.regions_data[index], index)

    def _clear_all_files(self):
        """Clears the file list, internal state, and editor canvas."""
        self.file_list_frame.clear_files()
        self.source_files.clear()
        self.translated_files.clear()
        self._clear_editor()
        self.after(10, lambda: show_toast(self.winfo_toplevel(), "列表已清空", "info"))

    def _on_clear_list_requested(self):
        """Handles the request to clear the file list, with confirmations."""
        from tkinter import messagebox

        if not self.source_files and not self.translated_files:
            self.after(10, lambda: show_toast(self.winfo_toplevel(), "列表已经为空", "info"))
            return

        # Check for unsaved changes in the currently loaded file
        if self._has_unsaved_changes():
            messagebox.showwarning(
                "请先保存",
                "当前文件有未保存的修改。请先手动保存或放弃更改，然后再清空列表。"
            )
            return
        
        # No unsaved changes, just confirm
        if messagebox.askyesno(
            "确认清空",
            "您确定要清空所有文件列表吗？此操作不可撤销。"
        ):
            self._clear_all_files()
