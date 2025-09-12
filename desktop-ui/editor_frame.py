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

    def _build_ui(self):
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=0, minsize=250)
        self.grid_columnconfigure(2, weight=0, minsize=250)

        self.toolbar = EditorToolbar(self, back_callback=self.return_callback)
        self.toolbar.grid(row=0, column=0, columnspan=3, sticky="ew")

        self.property_panel = PropertyPanel(self, shortcut_manager=self.shortcut_manager)
        self.property_panel.grid(row=1, column=0, sticky="ns", padx=(2,1), pady=2)

        self.mask_edit_collapsible_frame = CollapsibleFrame(self.property_panel, title="蒙版编辑", start_expanded=True)
        self.mask_edit_collapsible_frame.grid(row=1, column=0, sticky="ew", padx=5, pady=5)
        self.mask_edit_collapsible_frame.grid_remove() # Hide by default
        content_frame = self.mask_edit_collapsible_frame.content_frame
        content_frame.grid_columnconfigure(0, weight=1)
        self.mask_tool_menu = ctk.CTkOptionMenu(content_frame, values=["不选择", "画笔", "橡皮擦"], command=self._on_mask_tool_changed)
        self.mask_tool_menu.grid(row=0, column=0, pady=5, padx=5, sticky="ew")
        ctk.CTkLabel(content_frame, text="笔刷大小:").grid(row=1, column=0, pady=5, padx=5, sticky="w")
        self.brush_size_slider = ctk.CTkSlider(content_frame, from_=1, to=100, command=self._on_brush_size_changed)
        self.brush_size_slider.set(20)
        self.brush_size_slider.grid(row=2, column=0, pady=5, padx=5, sticky="ew")
        self.show_mask_checkbox = ctk.CTkCheckBox(content_frame, text="显示蒙版", command=lambda: self._on_toggle_mask_visibility(self.show_mask_checkbox.get()))
        self.show_mask_checkbox.select()
        self.show_mask_checkbox.grid(row=3, column=0, pady=5, padx=5, sticky="w")
        
        # 新增：蒙版优化参数
        ctk.CTkLabel(content_frame, text="扩张偏移:").grid(row=4, column=0, pady=(10, 2), padx=5, sticky="w")
        self.mask_dilation_offset_entry = ctk.CTkEntry(content_frame, placeholder_text="0")
        self.mask_dilation_offset_entry.grid(row=5, column=0, pady=2, padx=5, sticky="ew")
        self.mask_dilation_offset_entry.bind("<FocusOut>", self._on_mask_setting_changed)

        ctk.CTkLabel(content_frame, text="内核大小:").grid(row=6, column=0, pady=(10, 2), padx=5, sticky="w")
        self.mask_kernel_size_entry = ctk.CTkEntry(content_frame, placeholder_text="3")
        self.mask_kernel_size_entry.grid(row=7, column=0, pady=2, padx=5, sticky="ew")
        self.mask_kernel_size_entry.bind("<FocusOut>", self._on_mask_setting_changed)

        self.ignore_bubble_checkbox = ctk.CTkCheckBox(content_frame, text="忽略气泡", command=self._on_mask_setting_changed)
        self.ignore_bubble_checkbox.grid(row=8, column=0, pady=10, padx=5, sticky="w")

        # 添加蒙版更新按钮
        self.update_mask_button = ctk.CTkButton(
            content_frame, 
            text="更新蒙版", 
            command=self._update_mask_with_config,
            height=28
        )
        self.update_mask_button.grid(row=9, column=0, pady=5, padx=5, sticky="ew")
        
        # 添加显示被优化掉区域的选项
        self.show_removed_checkbox = ctk.CTkCheckBox(content_frame, text="显示被优化掉的区域", command=lambda: self._on_toggle_removed_mask_visibility(self.show_removed_checkbox.get()))
        # 默认不显示被优化掉的区域
        self.show_removed_checkbox.deselect()
        self.show_removed_checkbox.grid(row=10, column=0, pady=5, padx=5, sticky="w")

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

        # Property Panel Mask Editing
        self.property_panel.register_callback('set_edit_mode', self._on_mask_tool_changed)
        self.property_panel.register_callback('brush_size_changed', self._on_brush_size_changed)
        self.property_panel.register_callback('toggle_mask_visibility', self._on_toggle_mask_visibility)
        self.property_panel.register_callback('update_mask', self._update_mask_with_config)
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
        
        
        # Config is now pushed to canvas frame separately.
        # This method just triggers a region update and recalculation.
        self.canvas_frame.set_regions(self.regions_data)

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
        if image_path in self.source_files and regions:
            # 这是为编辑而加载的原始图像
            self.regions_data = regions
            self.raw_mask = raw_mask
            self.original_size = original_size
            
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
            if not regions and image_path in self.source_files:
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
        """Adds new source and translated files to the editor's lists, preventing duplicates."""
        newly_added_for_ui = []
        # Using a copy of source_files to check for existence, as we modify it in the loop
        current_source_files = self.source_files.copy()

        for i, src in enumerate(source_files):
            if src not in current_source_files:
                self.source_files.append(src)
                if i < len(translated_files):
                    # This assumes parallel lists, which is how app.py constructs them.
                    trans = translated_files[i]
                    self.translated_files.append(trans)
                    newly_added_for_ui.append(trans)

        if newly_added_for_ui:
            self.file_list_frame.add_files(newly_added_for_ui)

    def _on_edit_clicked(self):
        """
        When viewing a translated image, this switches to editing the original file.
        """
        current_file = self.file_manager.current_file_path
        if not current_file or current_file not in self.translated_files:
            show_toast(self, "请先从右侧列表选择一个翻译后的图片", level="warning")
            return

        try:
            idx = self.translated_files.index(current_file)
            source_file_to_load = self.source_files[idx]
            
            show_toast(self, f"正在加载原图 {os.path.basename(source_file_to_load)} 进行编辑...", level="info")
            
            # This will trigger the full loading process including JSON
            self.file_manager.load_image_from_path(source_file_to_load)
            
            # Automatically run mask generation and inpainting as requested
            self.after(500, lambda: self.async_service.submit_task(self._generate_refined_mask_then_render()))

        except (ValueError, IndexError):
            show_toast(self, "无法找到对应的原始文件", level="error")
            print(f"Error finding source for {current_file}. Index not found or out of bounds.")

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
            is_translated = file_path in self.translated_files
            is_source = file_path in self.source_files

            # Remove from UI list
            self.file_list_frame.remove_file(file_path)

            if is_translated:
                idx = self.translated_files.index(file_path)
                self.translated_files.pop(idx)
                if idx < len(self.source_files):
                    self.source_files.pop(idx)
            elif is_source:
                # This handles files added manually through the editor
                self.source_files.remove(file_path)

            # If unloading the currently displayed file, clear the editor
            if (hasattr(self.file_manager, 'current_file_path') and 
                self.file_manager.current_file_path == file_path):
                self._clear_editor()
                
                # If there are other files, load the first one
                if self.translated_files:
                    self._on_file_selected_from_list(self.translated_files[0])
                elif self.source_files:
                    self._on_file_selected_from_list(self.source_files[0])
                    
            show_toast(self, f"已卸载文件: {os.path.basename(file_path)}", level="success")
        except Exception as e:
            print(f"Error in perform_unload: {e}")


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

        # 尝试释放GPU内存
        self._release_gpu_memory()
        
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
        # When adding files from within the editor, they are always treated as new source files.
        # If we were in a "translated view" mode, this will break the parallel structure.
        # For now, we just add to the source list and the UI list.
        # The "Edit" button might fail for these new files, which is expected.
        new_files = [fp for fp in file_paths if fp not in self.source_files]
        self.source_files.extend(new_files)
        self.file_list_frame.add_files(new_files)
        if new_files and not self.image:
            self._on_file_selected_from_list(new_files[0])

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
            
            self.mask_dilation_offset_entry.delete(0, "end")
            self.mask_dilation_offset_entry.insert(0, str(dilation))
            
            self.mask_kernel_size_entry.delete(0, "end")
            self.mask_kernel_size_entry.insert(0, str(kernel))
            
            if ignore_bubble:
                self.ignore_bubble_checkbox.select()
            else:
                self.ignore_bubble_checkbox.deselect()
        except Exception as e:
            print(f"Error loading mask settings to UI: {e}")

    def _save_mask_settings_to_config(self):
        """从UI获取蒙版设置并保存到配置"""
        try:
            config = self.config_service.get_config()
            
            # 保存到顶级配置，而不是OCR配置
            config['mask_dilation_offset'] = int(self.mask_dilation_offset_entry.get() or 20)
            config['kernel_size'] = int(self.mask_kernel_size_entry.get() or 3)
            
            # ignore_bubble 仍然保存在OCR配置中
            ocr_config = config.setdefault('ocr', {})
            ocr_config['ignore_bubble'] = self.ignore_bubble_checkbox.get()
            
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

    def _on_mask_draw_preview(self, points: List[Tuple[int, int]]):
        self.canvas_frame.draw_mask_preview(points, self.mask_brush_size, self.mask_edit_mode)

    def _on_display_mode_changed(self, choice: str):
        # print(f"--- DEBUG: Entering _on_display_mode_changed with choice: {choice} ---")
        # When switching away from mask view, reset the tool selection.
        if choice != "蒙版视图":
            self.mask_edit_mode = "不选择"
            # Update the visual state of the tool menu in the property panel
            if 'mask_tool_menu' in self.property_panel.widgets:
                self.property_panel.widgets['mask_tool_menu'].set("不选择")
            self.canvas_frame.mouse_handler.set_mode('select')

        self.mask_edit_collapsible_frame.grid_remove()
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
        elif choice == "蒙版视图":
            self.view_mode = 'mask'
            self.mask_edit_collapsible_frame.grid()
            if self.refined_mask is None:
                show_toast(self, "正在生成蒙版...", level="info")
                self.toolbar.set_render_button_state("disabled")
                self.async_service.submit_task(self._generate_refined_mask())
            else:
                self.canvas_frame.set_refined_mask(self.refined_mask)
            self.canvas_frame.set_view_mode('mask')

    def _on_preview_alpha_changed(self, alpha_value):
        alpha_float = alpha_value / 100.0
        self.canvas_frame.set_inpainted_alpha(alpha_float)

    def _render_inpainted_image(self):
        if self.inpainting_in_progress:
            show_toast(self, "渲染已经在进行中...", "info")
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
            new_text = self.property_panel.widgets['translation_text'].get("1.0", "end-1c")
            if self.regions_data[index].get('translation') != new_text:
                old_data = copy.deepcopy(self.regions_data[index])
                self.regions_data[index]['translation'] = new_text
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
            font_color = self.property_panel.widgets['font_color'].get()
            
            alignment_map = {"自动": "auto", "左对齐": "left", "居中": "center", "右对齐": "right"}
            alignment_display = self.property_panel.widgets['alignment'].get()
            alignment = alignment_map.get(alignment_display, "auto")

            direction_map = {"自动": "auto", "横排": "h", "竖排": "v"}
            direction_display = self.property_panel.widgets['direction'].get()
            direction = direction_map.get(direction_display, "auto")

            # Update region data
            self.regions_data[index]['font_size'] = font_size
            self.regions_data[index]['font_color'] = font_color
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
                # 情况1: 当前加载的是翻译图，直接覆盖翻译图文件
                output_path = current_file
                file_name = os.path.basename(output_path)
                
                print(f"[EXPORT] 检测到翻译图: {file_name}，将直接覆盖该文件")
                
                # 确认覆盖翻译图
                if not messagebox.askyesno("确认覆盖", f"是否要覆盖当前的翻译图片 '{file_name}'？\n\n这将直接替换原有的翻译图片文件。"):
                    show_toast(self, "导出已取消", level="info")
                    return
                    
                show_toast(self, f"正在覆盖翻译图片: {file_name}", level="info")
                
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

    def _clear_all_files(self):
        """Clears the file list, internal state, and editor canvas."""
        self.file_list_frame.clear_files()
        self.source_files.clear()
        self.translated_files.clear()
        self._clear_editor()
        show_toast(self, "列表已清空", "info")

    def _on_clear_list_requested(self):
        """Handles the request to clear the file list, with confirmations."""
        from tkinter import messagebox

        if not self.source_files and not self.translated_files:
            show_toast(self, "列表已经为空", "info")
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
