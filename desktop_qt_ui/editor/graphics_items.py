
import math
import time
from typing import List

import cv2
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsPixmapItem,
    QGraphicsSceneMouseEvent,
    QStyle,
)

from editor.desktop_ui_geometry import (
    DesktopUIGeometry,
    handle_white_frame_edit,
    handle_vertex_edit,
    handle_edge_edit,
    rotate_point,
    get_polygon_center
)


class TransparentPixmapItem(QGraphicsPixmapItem):
    """一个对鼠标事件完全透明的Pixmap item，不会阻挡父item的选择"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 禁用所有鼠标交互
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setAcceptHoverEvents(False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)

    def shape(self) -> QPainterPath:
        """返回空路径，让这个item不参与碰撞检测"""
        return QPainterPath()


class RegionTextItem(QGraphicsItemGroup):

    def __init__(self, region_data, region_index, geometry_callback, parent=None):
        super().__init__(parent)
        self.region_data = region_data
        self.region_index = region_index
        self.geometry_callback = geometry_callback

        # 图像项引用，用于坐标转换
        self._image_item = None

        # 使用 desktop-ui 的几何管理器
        self.desktop_geometry = DesktopUIGeometry(region_data)

        # === 正确使用Qt坐标系：局部坐标+变换 ===
        # desktop_geometry.lines 是未旋转的世界坐标(绝对坐标)
        # desktop_geometry.center 是旋转中心点
        # desktop_geometry.angle 是旋转角度

        model_lines = self.desktop_geometry.lines
        self.rotation_angle = self.desktop_geometry.angle
        self.visual_center = QPointF(self.desktop_geometry.center[0], self.desktop_geometry.center[1])

        # 调试：打印原始数据
        # 设置Item的位置和旋转
        self.setPos(self.visual_center)
        self.setRotation(self.rotation_angle)
        self.setTransformOriginPoint(QPointF(0, 0))

        # lines 是模型坐标，需要转换为Qt局部坐标: local = model - center
        self.polygons = []
        for line in model_lines:
            local_poly = QPolygonF()
            for x, y in line:
                local_poly.append(QPointF(x - self.visual_center.x(), y - self.visual_center.y()))
            self.polygons.append(local_poly)

        self.text_item = TransparentPixmapItem(self)
        # 设置 text_item 的 Z-order 为负数,让它在父 item 的绘制内容(绿框、白框)之下
        self.text_item.setZValue(-1)

        self.setFlags(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable | QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setAcceptHoverEvents(True)
        self._interaction_mode = 'none'

        # 添加缺失的初始化
        self._drag_handle_indices = None
        self._drag_start_pos = QPointF()
        self._drag_start_polygons = []
        self._drag_start_rotation = 0.0
        self._polygons_visible = True
        self._setup_pens_and_brushes()

        # 初始化绿框/白框相关状态（局部坐标）
        self._green_box_items = []
        self._white_box_items = []
        self._show_green_box = True
        self._show_white_box = True
        self._dst_points_local = None  # 局部坐标
        self._white_frame_rect_local = None  # 局部坐标 [left, top, right, bottom]

        # 计算初始的绿框和白框(局部坐标)
        all_points = [p for poly in self.polygons for p in poly]
        if all_points:
            min_x = min(p.x() for p in all_points)
            max_x = max(p.x() for p in all_points)
            min_y = min(p.y() for p in all_points)
            max_y = max(p.y() for p in all_points)
            self._dst_points_local = np.array([[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]], dtype=np.float32)
            self._update_white_frame_from_green_box()

        # 调试输出控制：记录上次输出时间
        self._last_debug_time = 0
    
    def _get_image_item(self):
        """获取图像项用于坐标转换"""
        if self._image_item is None and self.scene():
            for item in self.scene().items():
                if isinstance(item, QGraphicsPixmapItem) and hasattr(item, 'pixmap'):
                    self._image_item = item
                    break
        return self._image_item
    
    def _scene_to_image_coords(self, scene_pos):
        """将场景坐标转换为图像坐标（与 desktop-ui 的 img_x, img_y 对应）"""
        image_item = self._get_image_item()
        if image_item:
            image_pos = image_item.mapFromScene(scene_pos)
            return image_pos.x(), image_pos.y()
        else:
            # 如果没有图像项，直接使用场景坐标
            return scene_pos.x(), scene_pos.y()
        self._drag_handle_indices = None
        self._drag_start_pos = QPointF()
        self._drag_start_polygons = []
        self._drag_start_rotation = 0.0
        self._polygons_visible = True
        self._setup_pens_and_brushes()
        
        # 初始化绿框/白框相关状态
        self._green_box_items = []
        self._white_box_items = []
        self._white_box_handles = []

    def _calculate_raw_center(self) -> QPointF:
        """计算原始多边形的中心点（边界框中心）"""
        # This now calculates the center of local coordinates, which should be (0,0)
        all_points = [p for poly in self.polygons for p in poly]
        if not all_points:
            return QPointF(0, 0)

        x_coords = [p.x() for p in all_points]
        y_coords = [p.y() for p in all_points]
        center_x = (min(x_coords) + max(x_coords)) / 2
        center_y = (min(y_coords) + max(y_coords)) / 2
        return QPointF(center_x, center_y)
    
    def _calculate_center_from_polygons(self, polygons: List[QPolygonF]) -> QPointF:
        """从多边形列表计算中心点（用于绝对坐标）"""
        # This method still works on absolute coordinates if they are passed in.
        all_points = [p for poly in polygons for p in poly]
        if not all_points:
            return QPointF(0, 0)

        x_coords = [p.x() for p in all_points]
        y_coords = [p.y() for p in all_points]
        center_x = (min(x_coords) + max(x_coords)) / 2
        center_y = (min(y_coords) + max(y_coords)) / 2
        return QPointF(center_x, center_y)

    def update_from_data(self, region_data: dict):
        """Updates the item's entire state from a new region_data dictionary."""
        print(f"[UPDATE_FROM_DATA] Region {self.region_index}: 开始更新")
        print(f"  当前 pos={self.pos()}, rotation={self.rotation()}")
        print(f"  新 region_data center={region_data.get('center', 'N/A')}, angle={region_data.get('angle', 'N/A')}")

        # 保存旧的场景边界矩形（在改变几何之前）
        old_scene_rect = self.sceneBoundingRect() if self.scene() else None

        # 保存选中状态
        was_selected = self.isSelected()

        # 确保 region_data 包含所有必要的字段
        # 如果新的 region_data 缺少某些字段,从旧的 self.region_data 中复制
        if hasattr(self, 'region_data') and self.region_data:
            # 合并旧数据和新数据,新数据优先
            merged_data = self.region_data.copy()
            merged_data.update(region_data)
            self.region_data = merged_data
        else:
            self.region_data = region_data

        self.desktop_geometry = DesktopUIGeometry(self.region_data)

        # lines是未旋转的世界坐标,需要转换为局部坐标
        model_lines = self.desktop_geometry.lines
        self.rotation_angle = self.desktop_geometry.angle
        self.visual_center = QPointF(self.desktop_geometry.center[0], self.desktop_geometry.center[1])

        # 在修改位置和旋转之前调用 prepareGeometryChange()
        self.prepareGeometryChange()

        self.setPos(self.visual_center)
        self.setRotation(self.rotation_angle)

        # 转换为局部坐标: local = world - center
        self.polygons = []
        for line in model_lines:
            local_poly = QPolygonF()
            for x, y in line:
                local_poly.append(QPointF(x - self.visual_center.x(), y - self.visual_center.y()))
            self.polygons.append(local_poly)

        # 更新白框和绿框
        self._update_frames_from_geometry(self.desktop_geometry)

        # 再次调用 prepareGeometryChange() 确保 shape() 缓存被清除
        self.prepareGeometryChange()

        # 恢复选中状态
        if was_selected != self.isSelected():
            print(f"[UPDATE_FROM_DATA] Region {self.region_index}: 恢复选中状态 {was_selected}")
            self.setSelected(was_selected)

        self.update()

        # 强制刷新场景空间索引 - 使用旧+新区域的并集
        if self.scene() and old_scene_rect is not None:
            from PyQt6.QtWidgets import QGraphicsScene
            new_scene_rect = self.sceneBoundingRect()
            # 合并旧和新的区域，确保空间索引完全更新
            update_rect = old_scene_rect.united(new_scene_rect)
            self.scene().invalidate(update_rect, QGraphicsScene.SceneLayer.ItemLayer)
            self.scene().update(update_rect)
            print(f"[UPDATE_FROM_DATA] Region {self.region_index}: 刷新空间索引，旧rect={old_scene_rect}, 新rect={new_scene_rect}")

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedChange:
            self.prepareGeometryChange()
            if value:
                # 变换原点始终是局部坐标的(0,0)
                self.setTransformOriginPoint(QPointF(0, 0))
        return super().itemChange(change, value)

    def _setup_pens_and_brushes(self):
        # 原始检测区域（蓝色/黄色框）
        self.pen = QPen(QColor("yellow"), 2)
        self.pen_selected = QPen(QColor("blue"), 2)
        self.brush = QBrush(QColor(255, 255, 0, 40))
        self.brush_selected = QBrush(QColor(0, 0, 255, 40))
        
        # 绿框（自动渲染区域）
        self.green_pen = QPen(QColor("green"), 2)
        self.green_brush = QBrush(Qt.BrushStyle.NoBrush)
        
        # 白框（手动调整边界）- 使用更明显的样式
        self.white_pen = QPen(QColor("white"), 3)
        self.white_pen.setStyle(Qt.PenStyle.DashLine)  # 虚线样式
        self.white_brush = QBrush(Qt.BrushStyle.NoBrush)
        
        # 缓存渲染区域数据
        self._dst_points_local = None
        self._white_frame_rect_local = None
        self._show_green_box = True  # 绿框默认显示
        self._show_white_box = True  # 白框也默认显示
        
        # 初始化白框为绿框外扩一定距离
        self._update_white_frame_from_green_box()

    def _get_core_polygon_path(self) -> QPainterPath:
        path = QPainterPath()
        seen_polygons = set()

        # 调试:记录是否打印过日志
        should_log = False
        if hasattr(self, '_last_path_log_time'):
            import time
            current_time = time.time()
            if current_time - self._last_path_log_time >= 1.0:
                should_log = True
                self._last_path_log_time = current_time
        else:
            should_log = True
            self._last_path_log_time = 0

        for i, poly in enumerate(self.polygons):
            if not poly.isEmpty():
                polygon_tuple = tuple((p.x(), p.y()) for p in poly)
                if polygon_tuple not in seen_polygons:
                    path.addPolygon(poly)
                    seen_polygons.add(polygon_tuple)
        return path

    def _get_stable_center(self) -> QPointF:
        """返回稳定的视觉中心点"""
        return self.visual_center

    def _get_handle_info(self) -> dict:
        lod = self.scene().views()[0].transform().m11() if self.scene() and self.scene().views() else 1.0
        handle_size = 10.0 / lod
        center_point = QPointF(0, 0)  # 在局部坐标系中,中心点就是(0,0)

        # 旋转手柄应该绑定在白框上方，而不是蓝框
        if self._white_frame_rect_local is not None:
            # 使用白框计算旋转手柄位置
            left, top, right, bottom = self._white_frame_rect_local
            center_x = (left + right) / 2
            base_rot_handle_pos = QPointF(center_x, top - 40.0 / lod)
        else:
            # 如果没有白框，退回到蓝框
            all_points = [p for poly in self.polygons for p in poly]
            if all_points:
                min_x = min(p.x() for p in all_points)
                max_x = max(p.x() for p in all_points)
                min_y = min(p.y() for p in all_points)
                max_y = max(p.y() for p in all_points)
                center_x = (min_x + max_x) / 2
                base_rot_handle_pos = QPointF(center_x, min_y - 40.0 / lod)
            else:
                base_rot_handle_pos = QPointF(0, -40.0 / lod)

        # 控制调试输出频率：每秒最多输出一次
        current_time = time.time()
        if current_time - self._last_debug_time >= 1.0:
            if self._white_frame_rect_local is not None:
                left, top, right, bottom = self._white_frame_rect_local

            self._last_debug_time = current_time

        # 不需要再旋转,因为Qt会自动处理item的旋转变换
        return {
            'lod': lod,
            'handle_size': handle_size,
            'pen_width': 1.5 / lod,
            'center': center_point,
            'rot_pos': base_rot_handle_pos,
            'vertex_pos': [p for poly in self.polygons for p in poly]
        }

    def shape(self) -> QPainterPath:
        path = self._get_core_polygon_path()
        if self.isSelected():
            handle_info = self._get_handle_info()
            handle_size = handle_info['handle_size']
            for p in handle_info['vertex_pos']:
                path.addEllipse(p, handle_size / 2, handle_size / 2)
            rot_pos = handle_info['rot_pos']
            path.addEllipse(rot_pos, handle_size / 2, handle_size / 2)
            path.moveTo(handle_info['center'])
            path.lineTo(rot_pos)

            # 添加白框区域(局部坐标)
            if self._show_white_box and self._white_frame_rect_local is not None:
                left, top, right, bottom = self._white_frame_rect_local

                # 添加白框矩形区域
                white_rect = QRectF(left, top, right - left, bottom - top)
                path.addRect(white_rect)

                # 添加白框手柄区域
                handle_size = 20  # 与 _get_white_frame_handle_at 中的检测范围一致
                corner_points = [
                    QPointF(left, top), QPointF(right, top),
                    QPointF(right, bottom), QPointF(left, bottom)
                ]
                edge_points = [
                    QPointF((left + right)/2, top), QPointF(right, (top + bottom)/2),
                    QPointF((left + right)/2, bottom), QPointF(left, (top + bottom)/2)
                ]

                # 添加手柄碰撞区域(局部坐标,Qt自动处理旋转)
                for p in corner_points + edge_points:
                    path.addEllipse(p.x() - handle_size//2, p.y() - handle_size//2, handle_size, handle_size)

        return path

    def boundingRect(self) -> QRectF:
        return self.shape().boundingRect().adjusted(-10, -10, 10, 10)

    def paint(self, painter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        is_selected = option.state & QStyle.StateFlag.State_Selected

        # 只绘制几何形状 (多边形)
        if self._polygons_visible:
            for i, poly in enumerate(self.polygons):
                if is_selected:
                    painter.setPen(self.pen_selected)
                    painter.setBrush(self.brush_selected)
                else:
                    painter.setPen(self.pen)
                    painter.setBrush(self.brush)
                painter.drawPolygon(poly)

        # 文本渲染现在由 GraphicsView 的 drawForeground 处理
        # if self._text_visible:
        #     self._render_wysiwyg_text(painter)

        # 绘制绿框（自动渲染区域）- 只要有数据就显示
        if self._show_green_box and self._dst_points_local is not None and self._polygons_visible:
            self._draw_green_box(painter)
        
        # 绘制白框（手动调整边界）- 选中时显示
        if is_selected and self._show_white_box and self._polygons_visible and self._white_frame_rect_local is not None:
            self._draw_white_box(painter)

        # 如果被选中，绘制交互手柄
        if is_selected:
            handle_info = self._get_handle_info()
            handle_size = handle_info['handle_size']
            pen_width = handle_info['pen_width']
            center_point = handle_info['center']
            rot_handle_pos = handle_info['rot_pos']

            painter.setBrush(QBrush(QColor("blue")))
            painter.setPen(QPen(QColor("white"), pen_width))
            for p in handle_info['vertex_pos']:
                # 使用正确的drawEllipse参数：中心点减去半径
                painter.drawEllipse(int(p.x() - handle_size / 2), int(p.y() - handle_size / 2), 
                                  int(handle_size), int(handle_size))
            
            painter.setPen(QPen(QColor("red"), pen_width * 1.5))
            painter.drawLine(center_point, rot_handle_pos)
            painter.setBrush(QBrush(QColor("red")))
            painter.setPen(QPen(QColor("white"), pen_width))
            painter.drawEllipse(int(rot_handle_pos.x() - handle_size / 2), int(rot_handle_pos.y() - handle_size / 2),
                              int(handle_size), int(handle_size))
            
            # 绘制白框手柄（如果显示白框）
            if self._show_white_box and self._white_frame_rect_local is not None and self._polygons_visible:
                self._draw_white_box_handles(painter)

        painter.restore()

    def hoverMoveEvent(self, event: QGraphicsSceneMouseEvent):
        # 检查当前工具，如果是绘图工具就不设置光标
        view = self.scene().views()[0] if self.scene().views() else None
        if view and hasattr(view, '_active_tool') and view._active_tool in ['pen', 'brush', 'eraser']:
            super().hoverMoveEvent(event)
            return

        if self.isSelected():
            handle, _ = self._get_handle_at(event.pos())
            if handle == 'vertex':
                self.setCursor(Qt.CursorShape.CrossCursor)
            elif handle == 'rotate':
                self.setCursor(Qt.CursorShape.SizeAllCursor) # Use a more distinct cursor
            elif handle == 'edge':
                poly_idx, edge_idx = _
                p1 = self.polygons[poly_idx][edge_idx]
                p2 = self.polygons[poly_idx][(edge_idx + 1) % len(self.polygons[poly_idx])]
                angle = np.arctan2(p2.y() - p1.y(), p2.x() - p1.x()) * 180 / np.pi
                angle = (angle + 360) % 360
                if (45 <= angle < 135) or (225 <= angle < 315):
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
                else:
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
            elif handle == 'white_corner':
                # 根据角点位置设置不同的对角线光标
                corner_idx = _
                if corner_idx in [0, 2]:  # 左上、右下
                    self.setCursor(Qt.CursorShape.SizeFDiagCursor)
                else:  # 右上、左下
                    self.setCursor(Qt.CursorShape.SizeBDiagCursor)
            elif handle == 'white_edge':
                edge_idx = _
                if edge_idx in [0, 2]:  # 上下边
                    self.setCursor(Qt.CursorShape.SizeVerCursor)
                else:  # 左右边
                    self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent):
        # 使用 Qt 自动计算的局部坐标（已考虑旋转）
        local_pos = event.pos()

        # 限制日志频率：每秒最多打印一次
        if event.button() == Qt.MouseButton.LeftButton:
            if self.isSelected():
                self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)

                # --- CRITICAL: Snapshot all initial state for the drag operation ---
                self._drag_start_pos = local_pos
                self._drag_start_polygons = [QPolygonF(poly) for poly in self.polygons]
                self._drag_start_rotation = self.rotation()  # Qt的当前旋转（应该是0）
                self._drag_start_angle = self.rotation_angle  # 我们的内部角度（真实的起始角度）
                self._drag_start_center = QPointF(0, 0)  # 局部坐标的中心点
                self._drag_start_scene_rect = self.sceneBoundingRect() if self.scene() else None  # 保存初始场景边界
                # 确保Qt变换的transform origin是局部坐标的(0,0)

                self.setTransformOriginPoint(QPointF(0, 0))
                # --- End Snapshot ---

                handle, indices = self._get_handle_at(local_pos)
                if handle:
                    self._interaction_mode = handle
                    self._drag_handle_indices = indices

                    # 为蓝色框编辑保存 desktop-ui 几何状态
                    if self._interaction_mode in ['vertex', 'edge']:
                        self._drag_start_geometry = DesktopUIGeometry(self.region_data)


                    if self._interaction_mode == 'rotate':
                        center_scene = self.mapToScene(self._drag_start_center)
                        start_pos_scene = event.scenePos()
                        start_vec_scene = start_pos_scene - center_scene
                        self._drag_start_angle_rad = np.arctan2(start_vec_scene.y(), start_vec_scene.x())
                    elif self._interaction_mode in ['white_corner', 'white_edge']:
                        # 保存 desktop-ui 几何状态
                        self._drag_start_geometry = DesktopUIGeometry(self.region_data)


                    if self._interaction_mode != 'move':
                        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
                    event.accept()
                    return

                # 点击多边形时进入移动模式
                self._interaction_mode = 'move'
                super().mousePressEvent(event)
                event.accept()
                return
            else:
                # 未选中状态：直接通过 model 设置选中（避免依赖 GraphicsView 的空间索引）
                # 获取 view 和 model
                if self.scene() and self.scene().views():
                    view = self.scene().views()[0]
                    if hasattr(view, 'model'):
                        view.model.set_selection([self.region_index])
                        event.accept()  # Accept 事件，阻止传播到 GraphicsView
                        return
                # 如果无法获取 model，fallback 到原来的行为
                super().mousePressEvent(event)
                event.ignore()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent):
        if self._interaction_mode == 'none':
            super().mouseMoveEvent(event)
            return

        if self._interaction_mode == 'rotate':
            center_scene = self.mapToScene(self._drag_start_center)
            new_pos_scene = event.scenePos()
            new_vec_scene = new_pos_scene - center_scene
            new_angle_rad = np.arctan2(new_vec_scene.y(), new_vec_scene.x())
            angle_delta_rad = new_angle_rad - self._drag_start_angle_rad
            angle_delta_deg = np.degrees(angle_delta_rad)
            self.setRotation(self._drag_start_rotation + angle_delta_deg)
            event.accept()
            return

        if self._interaction_mode == 'move':
            super().mouseMoveEvent(event)
            event.accept()
            return

        if self._interaction_mode in ['vertex', 'edge']:
            poly_idx, handle_idx = self._drag_handle_indices
            if not hasattr(self, '_drag_start_geometry'):
                return

            # 使用场景坐标（等于世界坐标），Qt会自动处理旋转
            scene_pos = event.scenePos()
            mouse_x = scene_pos.x()
            mouse_y = scene_pos.y()

            try:
                if self._interaction_mode == 'vertex':
                    new_geometry = handle_vertex_edit(
                        geometry=self._drag_start_geometry,
                        poly_index=poly_idx,
                        vertex_index=handle_idx,
                        mouse_x=mouse_x,
                        mouse_y=mouse_y
                    )
                elif self._interaction_mode == 'edge':
                    new_geometry = handle_edge_edit(
                        geometry=self._drag_start_geometry,
                        poly_index=poly_idx,
                        edge_index=handle_idx,
                        mouse_x=mouse_x,
                        mouse_y=mouse_y
                    )
                else:
                    return

                # Convert the new geometry back to region_data format and update the item
                new_region_data = new_geometry.to_region_data()
                self.update_from_data(new_region_data)

                # Also update the frames based on the new geometry
                self._update_frames_from_geometry(new_geometry)
                self.update()

            except Exception as e:

                return

            event.accept()
            return
        
        # 处理白框编辑
        if self._interaction_mode in ['white_corner', 'white_edge']:
            self._handle_white_frame_edit(event)
            event.accept()
            return

        super().mouseMoveEvent(event)
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent):
        # CRITICAL FIX: 即使 _interaction_mode 是 'none'，也要检查位置是否变化
        # Qt 的 ItemIsMovable 会自动移动 item，但不会触发我们的 move 逻辑
        current_pos = self.pos()
        if current_pos != self.visual_center:
            # 位置发生了变化，需要更新模型
            delta_x = current_pos.x() - self.visual_center.x()
            delta_y = current_pos.y() - self.visual_center.y()

            if abs(delta_x) >= 0.1 or abs(delta_y) >= 0.1:
                # 更新 lines：所有点都加上偏移量
                new_lines = []
                for poly in self.desktop_geometry.lines:
                    new_poly = [[p[0] + delta_x, p[1] + delta_y] for p in poly]
                    new_lines.append(new_poly)

                # 更新内部状态
                self.visual_center = current_pos
                self.desktop_geometry.center = [current_pos.x(), current_pos.y()]
                self.desktop_geometry.lines = new_lines

                import copy
                new_region_data = copy.deepcopy(self.region_data)
                new_region_data['center'] = [current_pos.x(), current_pos.y()]
                new_region_data['lines'] = new_lines

                # 更新模型
                self.geometry_callback(self.region_index, new_region_data)
                self.region_data.update(new_region_data)

        if self._interaction_mode != 'none':
            self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)

            # --- Start of Change ---
            if self._interaction_mode == 'move':
                # lines是未旋转的世界坐标（绝对位置），移动时需要同步更新lines和center
                new_center = self.pos()
                old_center = self.visual_center

                # 计算偏移量
                delta_x = new_center.x() - old_center.x()
                delta_y = new_center.y() - old_center.y()

                # 如果没有移动,跳过更新
                if abs(delta_x) < 0.1 and abs(delta_y) < 0.1:
                    self._interaction_mode = 'none'
                    return

                # 更新lines：所有点都加上偏移量
                new_lines = []
                for poly in self.desktop_geometry.lines:
                    new_poly = [[p[0] + delta_x, p[1] + delta_y] for p in poly]
                    new_lines.append(new_poly)

                # Update the internal state
                self.visual_center = new_center
                self.desktop_geometry.center = [new_center.x(), new_center.y()]
                self.desktop_geometry.lines = new_lines

                import copy
                new_region_data = copy.deepcopy(self.region_data)
                new_region_data['center'] = [new_center.x(), new_center.y()]
                new_region_data['lines'] = new_lines

                # Update the model via callback
                self.geometry_callback(self.region_index, new_region_data)
                self.region_data.update(new_region_data)


            elif self._interaction_mode == 'rotate':
                # --- REFACTOR START: Simplified rotate logic ---
                # The item's rotation is the new angle.
                new_angle = self.rotation()

                # Update internal state
                self.rotation_angle = new_angle
                self.desktop_geometry.angle = new_angle

                # Update the model
                import copy
                new_region_data = copy.deepcopy(self.region_data)
                new_region_data['angle'] = new_angle

                self.geometry_callback(self.region_index, new_region_data)
                self.region_data.update(new_region_data)
                # --- REFACTOR END ---

            elif self._interaction_mode in ['vertex', 'edge']:
                # 使用 desktop-ui 的数据结构保存蓝框编辑结果
                new_region_data = self.desktop_geometry.to_region_data()

                import copy
                final_region_data = copy.deepcopy(self.region_data)

                print(f"[BLUE FRAME DEBUG] Region {self.region_index}: before update")
                print(f"  texts: {final_region_data.get('texts', 'NOT FOUND')}")
                print(f"  translation: {final_region_data.get('translation', 'NOT FOUND')}")

                final_region_data.update(new_region_data)

                print(f"[BLUE FRAME DEBUG] Region {self.region_index}: after update")
                print(f"  texts: {final_region_data.get('texts', 'NOT FOUND')}")
                print(f"  translation: {final_region_data.get('translation', 'NOT FOUND')}")

                self.geometry_callback(self.region_index, final_region_data)
                self.region_data.update(final_region_data)

            elif self._interaction_mode in ['white_corner', 'white_edge']:
                # 使用 desktop-ui 的数据结构保存结果
                print(f"[RELEASE WHITE] Region {self.region_index}: 白框编辑完成")
                print(f"  当前 pos={self.pos()}, desktop_geometry.center={self.desktop_geometry.center}")

                new_region_data = self.desktop_geometry.to_region_data()

                print(f"  to_region_data 返回 center={new_region_data['center']}, angle={new_region_data['angle']}")

                import copy
                final_region_data = copy.deepcopy(self.region_data)
                final_region_data.update(new_region_data)

                print(f"[RELEASE WHITE] 调用 geometry_callback, final center={final_region_data['center']}")
                self.geometry_callback(self.region_index, final_region_data)
                self.region_data.update(final_region_data)

                # 使用保存的初始rect刷新空间索引
                if self.scene() and hasattr(self, '_drag_start_scene_rect') and self._drag_start_scene_rect is not None:
                    from PyQt6.QtWidgets import QGraphicsScene
                    new_scene_rect = self.sceneBoundingRect()
                    update_rect = self._drag_start_scene_rect.united(new_scene_rect)
                    print(f"[RELEASE WHITE] 刷新空间索引: 初始rect={self._drag_start_scene_rect}, 新rect={new_scene_rect}")
                    self.scene().invalidate(update_rect, QGraphicsScene.SceneLayer.ItemLayer)
                    self.scene().update(update_rect)

            # --- End of Change ---

        self._interaction_mode = 'none'
        super().mouseReleaseEvent(event)

    def _get_handle_at(self, pos: QPointF) -> (str, tuple):
        handle_info = self._get_handle_info()
        handle_detect_size = handle_info['handle_size']

        # 优先级1: 旋转手柄（红色，最明显）
        if (handle_info['rot_pos'] - pos).manhattanLength() < handle_detect_size:
            return 'rotate', (-1, -1)

        # 优先级2: 蓝框顶点手柄（蓝色圆点，用于调整检测区域）
        for poly_idx, poly in enumerate(self.polygons):
            for vert_idx, p in enumerate(poly):
                if (p - pos).manhattanLength() < handle_detect_size:
                    return 'vertex', (poly_idx, vert_idx)

        # 优先级3: 蓝框边缘手柄（用于添加新顶点）
        lod = handle_info['lod']
        for poly_idx, poly in enumerate(self.polygons):
            for edge_idx in range(len(poly)):
                p1 = poly[edge_idx]
                p2 = poly[(edge_idx + 1) % len(poly)]
                v_edge = p2 - p1
                norm_v_edge = np.sqrt(v_edge.x()**2 + v_edge.y()**2)
                if norm_v_edge < 1e-6: continue

                # Using a slightly more complex but standard point-to-line distance formula
                v_p1_to_pos = pos - p1
                cross_product = v_edge.x() * v_p1_to_pos.y() - v_edge.y() * v_p1_to_pos.x()
                dist = abs(cross_product) / norm_v_edge

                if dist < (5.0 / lod):
                    dot_product = v_p1_to_pos.x() * v_edge.x() + v_p1_to_pos.y() * v_edge.y()
                    if 0 <= dot_product <= norm_v_edge**2:
                        return 'edge', (poly_idx, edge_idx)

        # 优先级4: 白框手柄（最后检查，避免误触）
        if self.isSelected() and self._show_white_box and self._white_frame_rect_local is not None:
            white_handle_result = self._get_white_frame_handle_at(pos)
            if white_handle_result[0] is not None:
                return white_handle_result

        return None, (-1, -1)

    def _render_wysiwyg_text(self, painter):
        """使用后端渲染文本以实现WYSIWYG（已重构缓存逻辑）"""
        # ... (existing method body)

    def update_text_pixmap(self, pixmap, pos, rotation=0.0, pivot_point=None):
        """更新文本pixmap - pos是世界坐标,需要转换为局部坐标"""
        self.text_item.setPixmap(pixmap)



        # 将世界坐标转换为局部坐标: local = world - center
        local_pos = QPointF(
            pos.x() - self.desktop_geometry.center[0],
            pos.y() - self.desktop_geometry.center[1]
        )
        self.text_item.setPos(local_pos)

        if pivot_point is None:
            # Fallback: 使用pixmap自己的中心作为旋转中心
            origin = self.text_item.boundingRect().center()
            self.text_item.setTransformOriginPoint(origin)
        else:
            # 将世界坐标的pivot转换为相对于pixmap的局部坐标
            pivot_in_pixmap_coords = QPointF(
                pivot_point.x() - pos.x(),
                pivot_point.y() - pos.y()
            )
            self.text_item.setTransformOriginPoint(pivot_in_pixmap_coords)

        # 文字不需要额外旋转,因为父Item已经旋转了
        self.text_item.setRotation(0)

    def get_id(self):
        return self.region_data.get('id')

    def get_polygon_for_save(self):
        return self.polygon

    def set_text_visible(self, visible: bool):
        """设置文本的可见性"""
        self.text_item.setVisible(visible)

    def set_box_visible(self, visible: bool):
        """设置边界框的可见性"""
        if self._polygons_visible != visible:
            self._polygons_visible = visible
            self.update()
    
    def set_dst_points(self, dst_points):
        """设置渲染区域数据（绿框）- 输入是世界坐标"""
        if dst_points is None:
            self._dst_points_local = None
            self._white_frame_rect_local = None
            self.prepareGeometryChange()
            self.update()
            return

        # 将世界坐标转换为局部坐标
        if len(dst_points.shape) >= 2:
            self._dst_points_local = np.zeros_like(dst_points)
            for i, points in enumerate(dst_points):
                for j, point in enumerate(points):
                    # 世界坐标转局部坐标：减去中心点
                    self._dst_points_local[i][j] = [
                        point[0] - self.visual_center.x(),
                        point[1] - self.visual_center.y()
                    ]
        else:
            self._dst_points_local = np.array([
                [p[0] - self.visual_center.x(), p[1] - self.visual_center.y()]
                for p in dst_points
            ])


        self._update_white_frame_from_green_box()
        self.prepareGeometryChange()
        self.update()

    def _update_white_frame_from_green_box(self):
        """根据绿框更新白框位置 - 局部坐标"""
        if self._dst_points_local is None or self._dst_points_local.size == 0:
            self._white_frame_rect_local = None
            return

        points_2d = self._dst_points_local[0] if len(self._dst_points_local.shape) > 2 else self._dst_points_local

        if len(points_2d) < 4:
            return

        # 在局部坐标系中计算边界框
        min_x = min(p[0] for p in points_2d)
        max_x = max(p[0] for p in points_2d)
        min_y = min(p[1] for p in points_2d)
        max_y = max(p[1] for p in points_2d)

        # 创建白框（比绿框大40像素）
        padding = 40
        self._white_frame_rect_local = [
            min_x - padding,  # left
            min_y - padding,  # top
            max_x + padding,  # right
            max_y + padding   # bottom
        ]
    
    def _draw_green_box(self, painter):
        """绘制绿框 - 显示根据译文长度缩放后的实际渲染区域"""
        if self._dst_points_local is None or self._dst_points_local.size == 0:
            return

        painter.setPen(self.green_pen)
        painter.setBrush(self.green_brush)

        # 直接使用局部坐标绘制,Qt会自动处理旋转
        if len(self._dst_points_local.shape) >= 2 and self._dst_points_local.shape[0] > 0:
            points = self._dst_points_local[0]  # 取第一个区域
            if len(points) >= 4:
                green_poly = QPolygonF([QPointF(p[0], p[1]) for p in points])
                painter.drawPolygon(green_poly)
    
    def _draw_white_box(self, painter):
        """绘制白框 - 显示可手动调整的渲染边界外框"""
        if self._white_frame_rect_local is None:
            return

        # 绘制白色外框的矩形
        left, top, right, bottom = self._white_frame_rect_local

        # 创建白框的四个角点(局部坐标)
        white_points = [
            QPointF(left, top),     # 左上
            QPointF(right, top),    # 右上
            QPointF(right, bottom), # 右下
            QPointF(left, bottom)   # 左下
        ]

        # 直接使用局部坐标绘制,Qt会自动处理旋转
        white_poly = QPolygonF(white_points)

        # 使用鲜艳的青色作为主色，在任何背景下都明显
        painter.setPen(QPen(QColor(0, 255, 255), 4))  # 青色，4像素宽
        painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        painter.drawPolygon(white_poly)

        # 再绘制黑色描边增加对比度
        painter.setPen(QPen(QColor("black"), 2))
        painter.drawPolygon(white_poly)
    
    def set_green_box_visible(self, visible: bool):
        """设置绿框的可见性"""
        self._show_green_box = visible
        self.update()
    
    def set_white_box_visible(self, visible: bool):
        """设置白框的可见性"""
        self._show_white_box = visible
        self.update()
    
    def get_white_frame_rect(self):
        """获取白框的边界矩形"""
        return self._white_frame_rect_local
    
    def set_white_frame_rect(self, rect):
        """设置白框的边界矩形"""
        self._white_frame_rect_local = rect
        self.prepareGeometryChange()  # 通知Qt几何将变化
        self.update()
    
    def _draw_white_box_handles(self, painter):
        """绘制白框的交互手柄"""
        if self._white_frame_rect_local is None:
            return

        handle_size = 12  # 增加手柄大小
        pen_width = 2

        left, top, right, bottom = self._white_frame_rect_local

        # 角点手柄（局部坐标，Qt会自动处理旋转）
        corner_points = [
            QPointF(left, top),     # 左上
            QPointF(right, top),    # 右上
            QPointF(right, bottom), # 右下
            QPointF(left, bottom)   # 左下
        ]

        # 边中点手柄（局部坐标，Qt会自动处理旋转）
        edge_points = [
            QPointF((left + right)/2, top),      # 上边中点
            QPointF(right, (top + bottom)/2),    # 右边中点
            QPointF((left + right)/2, bottom),   # 下边中点
            QPointF(left, (top + bottom)/2)      # 左边中点
        ]

        # 角点手柄 - 黄色方形加黑色描边
        painter.setBrush(QBrush(QColor(255, 255, 100)))  # 亮黄色
        painter.setPen(QPen(QColor("black"), pen_width))
        for point in corner_points:
            x = int(point.x() - handle_size//2)
            y = int(point.y() - handle_size//2)
            painter.drawRect(x, y, handle_size, handle_size)

        # 边中点手柄 - 橙色圆形加黑色描边
        painter.setBrush(QBrush(QColor(255, 165, 0)))  # 亮橙色
        painter.setPen(QPen(QColor("black"), pen_width))
        for point in edge_points:
            x = int(point.x() - handle_size//2)
            y = int(point.y() - handle_size//2)
            painter.drawEllipse(x, y, handle_size, handle_size)
    
    def _get_white_frame_handle_at(self, pos: QPointF):
        """检查是否点击了白框的手柄（pos是局部坐标）"""
        if self._white_frame_rect_local is None:
            return None, (-1, -1)

        handle_size = 20  # 白框手柄的检测范围
        left, top, right, bottom = self._white_frame_rect_local

        # 角点手柄（局部坐标，Qt会自动处理旋转）
        corner_points = [
            QPointF(left, top),     # 0: 左上
            QPointF(right, top),    # 1: 右上
            QPointF(right, bottom), # 2: 右下
            QPointF(left, bottom)   # 3: 左下
        ]

        # 边中点手柄（局部坐标，Qt会自动处理旋转）
        edge_points = [
            QPointF((left + right)/2, top),      # 0: 上边中点
            QPointF(right, (top + bottom)/2),    # 1: 右边中点
            QPointF((left + right)/2, bottom),   # 2: 下边中点
            QPointF(left, (top + bottom)/2)      # 3: 左边中点
        ]

        # 碰撞检测（局部坐标，pos也是局部坐标，Qt已经处理了旋转）
        # 检测角点手柄
        for i, point in enumerate(corner_points):
            distance = (point - pos).manhattanLength()
            if distance < handle_size:
                return 'white_corner', i

        # 检测边中点手柄
        for i, point in enumerate(edge_points):
            distance = (point - pos).manhattanLength()
            if distance < handle_size:
                return 'white_edge', i

        return None, (-1, -1)
    
    def _handle_white_frame_edit(self, event: QGraphicsSceneMouseEvent):
        """使用 desktop-ui 的白框编辑逻辑"""
        if not hasattr(self, '_drag_start_geometry') or self._drag_handle_indices is None:
            return

        # 使用场景坐标（等于世界坐标），Qt会自动处理旋转
        scene_pos = event.scenePos()
        mouse_x = scene_pos.x()
        mouse_y = scene_pos.y()

        # 确定动作类型
        if self._interaction_mode == 'white_corner':
            action_type = 'white_frame_corner_edit'
        elif self._interaction_mode == 'white_edge':
            action_type = 'white_frame_edge_edit'
        else:
            return

        # 使用 desktop-ui 的白框编辑函数
        try:
            print(f"[MOVE WHITE] Region {self.region_index}: 调用 handle_white_frame_edit 前")
            print(f"  self.desktop_geometry.center={self.desktop_geometry.center}")

            new_geometry = handle_white_frame_edit(
                geometry=self._drag_start_geometry,
                action_type=action_type,
                handle_index=self._drag_handle_indices,
                mouse_x=mouse_x,
                mouse_y=mouse_y
            )

            print(f"[MOVE WHITE] Region {self.region_index}: handle_white_frame_edit 返回")
            print(f"  new_geometry.center={new_geometry.center}")

            # 更新Item的位置和旋转
            self.desktop_geometry = new_geometry

            print(f"[MOVE WHITE] Region {self.region_index}: 赋值后")
            print(f"  self.desktop_geometry.center={self.desktop_geometry.center}")
            model_lines = new_geometry.lines  # 未旋转的世界坐标
            self.rotation_angle = new_geometry.angle

            # 关键修复：先保存旧的场景边界矩形（在改变位置之前）
            old_scene_rect = self.sceneBoundingRect() if self.scene() else None

            # 通知Qt几何即将改变（必须在改变前调用）
            self.prepareGeometryChange()

            self.visual_center = QPointF(new_geometry.center[0], new_geometry.center[1])
            self.setPos(self.visual_center)
            self.setRotation(self.rotation_angle)

            # 转换为局部坐标: local = world - center
            self.polygons = []
            for line in model_lines:
                local_poly = QPolygonF()
                for x, y in line:
                    local_poly.append(QPointF(x - self.visual_center.x(), y - self.visual_center.y()))
                self.polygons.append(local_poly)

            # 更新白框和绿框
            self._update_frames_from_geometry(new_geometry)

            # 强制更新item
            self.update()

            # 立即刷新场景空间索引 - 刷新旧+新位置的并集区域
            if self.scene() and old_scene_rect is not None:
                new_scene_rect = self.sceneBoundingRect()
                # 合并旧和新的区域，确保空间索引完全更新
                update_rect = old_scene_rect.united(new_scene_rect)
                self.scene().invalidate(update_rect, QGraphicsScene.SceneLayer.ItemLayer)
                self.scene().update(update_rect)

        except Exception as e:

            return
    
    def _update_frames_from_geometry(self, geometry: DesktopUIGeometry):
        """从 desktop-ui 几何更新白框"""
        # geometry返回的是世界坐标,需要转换为局部坐标
        center_x, center_y = geometry.center[0], geometry.center[1]

        # --- FIX: Calculate bounds from un-rotated model coordinates ---
        all_vertices_model = [vertex for poly in geometry.lines for vertex in poly]
        if not all_vertices_model:
            self._white_frame_rect_local = None
            # 不要清空绿框,因为绿框是由 set_dst_points 设置的
            # self._dst_points_local = None
            return

        model_x_coords = [v[0] for v in all_vertices_model]
        model_y_coords = [v[1] for v in all_vertices_model]
        blue_min_x = min(model_x_coords)
        blue_max_x = max(model_x_coords)
        blue_min_y = min(model_y_coords)
        blue_max_y = max(model_y_coords)

        # 更新白框 (left, top, right, bottom) - 转换为局部坐标
        # 白框基于蓝框计算,不基于绿框
        padding = 40
        white_left = blue_min_x - padding
        white_top = blue_min_y - padding
        white_right = blue_max_x + padding
        white_bottom = blue_max_y + padding

        self._white_frame_rect_local = [
            white_left - center_x, white_top - center_y,
            white_right - center_x, white_bottom - center_y
        ]

        # 不要在这里更新绿框！
        # 绿框应该由 set_dst_points 根据文字渲染结果(经过排版缩放)来设置
        # 旧代码(已注释):
        # self._dst_points_local = np.array([[
        #     [blue_min_x - center_x, blue_min_y - center_y],
        #     [blue_max_x - center_x, blue_min_y - center_y],
        #     [blue_max_x - center_x, blue_max_y - center_y],
        #     [blue_min_x - center_x, blue_max_y - center_y]
        # ]], dtype=np.float32)


