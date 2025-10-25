import itertools
import numpy as np
from typing import List, Set
from collections import Counter
import networkx as nx
from shapely.geometry import Polygon

from ..utils import TextBlock, Quadrilateral, quadrilateral_can_merge_region

def split_text_region(
        bboxes: List[Quadrilateral],
        connected_region_indices: Set[int],
        width,
        height,
        gamma = 0.5,
        sigma = 2,
        debug = False
    ) -> List[Set[int]]:

    connected_region_indices = list(connected_region_indices)

    # case 1
    if len(connected_region_indices) == 1:
        if debug:
            print(f"    [SPLIT] 单个框 {connected_region_indices[0]}, 不分割")
        return [set(connected_region_indices)]

    # case 2
    if len(connected_region_indices) == 2:
        fs1 = bboxes[connected_region_indices[0]].font_size
        fs2 = bboxes[connected_region_indices[1]].font_size
        fs = max(fs1, fs2)

        dist = bboxes[connected_region_indices[0]].distance(bboxes[connected_region_indices[1]])
        angle_diff = abs(bboxes[connected_region_indices[0]].angle - bboxes[connected_region_indices[1]].angle)

        if debug:
            print(f"    [SPLIT] 两个框 {connected_region_indices}")
            print(f"      距离: {dist:.1f} 阈值: {(1 + gamma) * fs:.1f}")
            print(f"      角度差: {np.rad2deg(angle_diff):.1f}° 阈值: {np.rad2deg(0.2 * np.pi):.1f}°")
            print(f"      assigned_direction: {bboxes[connected_region_indices[0]].assigned_direction}, {bboxes[connected_region_indices[1]].assigned_direction}")

        if dist < (1 + gamma) * fs and angle_diff < 0.2 * np.pi:
            if debug:
                print(f"      ✅ 不分割")
            return [set(connected_region_indices)]
        else:
            if debug:
                print(f"      ❌ 分割成两个区域")
            return [set([connected_region_indices[0]]), set([connected_region_indices[1]])]

    # case 3
    if debug:
        print(f"    [SPLIT] 多个框 {connected_region_indices}, 使用最小生成树分析")

    G = nx.Graph()
    for idx in connected_region_indices:
        G.add_node(idx)
    for (u, v) in itertools.combinations(connected_region_indices, 2):
        dist = bboxes[u].distance(bboxes[v])
        G.add_edge(u, v, weight=dist)
        if debug:
            print(f"      框{u}-框{v} 距离: {dist:.1f}")

    # Get distances from neighbouring bboxes
    edges = nx.algorithms.tree.minimum_spanning_edges(G, algorithm='kruskal', data=True)
    edges = sorted(edges, key=lambda a: a[2]['weight'], reverse=True)
    distances_sorted = [a[2]['weight'] for a in edges]
    fontsize = np.mean([bboxes[idx].font_size for idx in connected_region_indices])
    distances_std = np.std(distances_sorted)
    distances_mean = np.mean(distances_sorted)
    std_threshold = max(0.3 * fontsize + 5, 5)

    b1, b2 = bboxes[edges[0][0]], bboxes[edges[0][1]]
    max_poly_distance = Polygon(b1.pts).distance(Polygon(b2.pts))
    max_centroid_alignment = min(abs(b1.centroid[0] - b2.centroid[0]), abs(b1.centroid[1] - b2.centroid[1]))

    if debug:
        print(f"      最远边: 框{edges[0][0]}-框{edges[0][1]} 距离{distances_sorted[0]:.1f}")
        print(f"      平均字体: {fontsize:.1f}")
        print(f"      距离统计: mean={distances_mean:.1f} std={distances_std:.1f}")
        print(f"      std阈值: {std_threshold:.1f}")
        print(f"      条件A1: {distances_sorted[0]:.1f} <= {distances_mean + distances_std * sigma:.1f}? {distances_sorted[0] <= distances_mean + distances_std * sigma}")
        print(f"      条件A2: {distances_sorted[0]:.1f} <= {fontsize * (1 + gamma):.1f}? {distances_sorted[0] <= fontsize * (1 + gamma)}")
        print(f"      条件B1: {distances_std:.1f} < {std_threshold:.1f}? {distances_std < std_threshold}")
        print(f"      条件B2: poly_dist={max_poly_distance:.1f}==0 AND align={max_centroid_alignment:.1f}<5? {max_poly_distance == 0 and max_centroid_alignment < 5}")

    if (distances_sorted[0] <= distances_mean + distances_std * sigma \
            or distances_sorted[0] <= fontsize * (1 + gamma)) \
            and (distances_std < std_threshold \
            or max_poly_distance == 0 and max_centroid_alignment < 5):
        if debug:
            print(f"      ✅ 不分割")
        return [set(connected_region_indices)]
    else:
        if debug:
            print(f"      ❌ 移除最远边并递归分割")
        # (split_u, split_v, _) = edges[0]
        # print(f'split between "{bboxes[split_u].pts}", "{bboxes[split_v].pts}"')
        G = nx.Graph()
        for idx in connected_region_indices:
            G.add_node(idx)
        # Split out the most deviating bbox
        for edge in edges[1:]:
            G.add_edge(edge[0], edge[1])
        ans = []
        for node_set in nx.algorithms.components.connected_components(G):
            ans.extend(split_text_region(bboxes, node_set, width, height, gamma, sigma, debug))
        return ans

# def get_mini_boxes(contour):
#     bounding_box = cv2.minAreaRect(contour)
#     points = sorted(list(cv2.boxPoints(bounding_box)), key=lambda x: x[0])

#     index_1, index_2, index_3, index_4 = 0, 1, 2, 3
#     if points[1][1] > points[0][1]:
#         index_1 = 0
#         index_4 = 1
#     else:
#         index_1 = 1
#         index_4 = 0
#     if points[3][1] > points[2][1]:
#         index_2 = 2
#         index_3 = 3
#     else:
#         index_2 = 3
#         index_3 = 2

#     box = [points[index_1], points[index_2], points[index_3], points[index_4]]
#     box = np.array(box)
#     startidx = box.sum(axis=1).argmin()
#     box = np.roll(box, 4 - startidx, 0)
#     box = np.array(box)
#     return box

def merge_bboxes_text_region(bboxes: List[Quadrilateral], width, height, debug=False, edge_ratio_threshold=0.0):
    # step 0: merge quadrilaterals that belong to the same textline
    # u = 0
    # removed_counter = 0
    # while u < len(bboxes) - 1 - removed_counter:
    #     v = u
    #     while v < len(bboxes) - removed_counter:
    #         if quadrilateral_can_merge_region(bboxes[u], bboxes[v], aspect_ratio_tol=1.1, font_size_ratio_tol=1,
    #                                         char_gap_tolerance=1, char_gap_tolerance2=3, discard_connection_gap=0) \
    #            and abs(bboxes[u].centroid[0] - bboxes[v].centroid[0]) < 5 or abs(bboxes[u].centroid[1] - bboxes[v].centroid[1]) < 5:
    #                 bboxes[u] = merge_quadrilaterals(bboxes[u], bboxes[v])
    #                 removed_counter += 1
    #                 bboxes.pop(v)
    #         else:
    #             v += 1
    #     u += 1

    if debug:
        print(f"\n[MERGE_DEBUG] 开始合并 {len(bboxes)} 个文本框")
        for i, box in enumerate(bboxes):
            print(f"  框{i}: 中心({box.centroid[0]:.0f},{box.centroid[1]:.0f}) 字体{box.font_size:.0f}")

    # step 1: divide into multiple text region candidates
    G = nx.Graph()
    for i, box in enumerate(bboxes):
        G.add_node(i, box=box)

    # 记录边缘距离
    edge_distances = {}
    edge_count = 0
    for ((u, ubox), (v, vbox)) in itertools.combinations(enumerate(bboxes), 2):
        # if quadrilateral_can_merge_region_coarse(ubox, vbox):
        can_merge = quadrilateral_can_merge_region(ubox, vbox, aspect_ratio_tol=1.3, font_size_ratio_tol=2,
                                          char_gap_tolerance=1, char_gap_tolerance2=3, debug=debug)
        if can_merge:
            # 计算边缘距离
            poly_dist = ubox.poly_distance(vbox)
            G.add_edge(u, v, distance=poly_dist)
            edge_distances[(u, v)] = poly_dist
            edge_count += 1

    if debug:
        print(f"\n[MERGE_DEBUG] 建立了 {edge_count} 条连接边")

    # step 1.5: 边缘距离比例检测 - 断开距离差异过大的连接
    if edge_ratio_threshold > 0 and len(bboxes) > 2:
        edges_to_remove = []
        for node in G.nodes():
            neighbors = list(G.neighbors(node))
            if len(neighbors) >= 2:
                # 获取该节点到所有邻居的距离
                neighbor_distances = []
                for neighbor in neighbors:
                    edge = (min(node, neighbor), max(node, neighbor))
                    dist = edge_distances.get(edge, 0)
                    neighbor_distances.append((neighbor, dist))

                # 按距离排序
                neighbor_distances.sort(key=lambda x: x[1])

                # 检查最小距离和其他距离的比例
                min_dist = neighbor_distances[0][1]
                if min_dist > 0:  # 避免除以0
                    for neighbor, dist in neighbor_distances[1:]:
                        ratio = dist / min_dist
                        if ratio > edge_ratio_threshold:
                            edge_to_remove = (min(node, neighbor), max(node, neighbor))
                            if edge_to_remove not in edges_to_remove:
                                edges_to_remove.append(edge_to_remove)
                                if debug:
                                    print(f"  [EDGE_RATIO] 框{node}的邻居距离比例: {min_dist:.1f} vs {dist:.1f} = {ratio:.2f} > {edge_ratio_threshold:.2f}, 断开框{node}-框{neighbor}")

        # 移除边
        for edge in edges_to_remove:
            if G.has_edge(edge[0], edge[1]):
                G.remove_edge(edge[0], edge[1])
                if debug:
                    print(f"  [EDGE_RATIO] 移除边: 框{edge[0]}-框{edge[1]}")

    # step 2: postprocess - further split each region
    region_indices: List[Set[int]] = []
    connected_components = list(nx.algorithms.components.connected_components(G))
    if debug:
        print(f"\n[MERGE_DEBUG] 找到 {len(connected_components)} 个连通分量")
        for i, comp in enumerate(connected_components):
            print(f"  分量{i}: 包含框 {sorted(comp)}")

    for node_set in connected_components:
         split_result = split_text_region(bboxes, node_set, width, height, debug=debug)
         region_indices.extend(split_result)
         if debug:
             print(f"  分割后: {len(split_result)} 个区域")

    # step 3: return regions
    for node_set in region_indices:
    # for node_set in nx.algorithms.components.connected_components(G):
        nodes = list(node_set)
        txtlns: List[Quadrilateral] = np.array(bboxes)[nodes]

        # calculate average fg and bg color
        fg_r = round(np.mean([box.fg_r for box in txtlns]))
        fg_g = round(np.mean([box.fg_g for box in txtlns]))
        fg_b = round(np.mean([box.fg_b for box in txtlns]))
        bg_r = round(np.mean([box.bg_r for box in txtlns]))
        bg_g = round(np.mean([box.bg_g for box in txtlns]))
        bg_b = round(np.mean([box.bg_b for box in txtlns]))

        # majority vote for direction
        dirs = [box.direction for box in txtlns]
        majority_dir_top_2 = Counter(dirs).most_common(2)
        if len(majority_dir_top_2) == 1 :
            majority_dir = majority_dir_top_2[0][0]
        elif majority_dir_top_2[0][1] == majority_dir_top_2[1][1] : # if top 2 have the same counts
            max_aspect_ratio = -100
            for box in txtlns :
                if box.aspect_ratio > max_aspect_ratio :
                    max_aspect_ratio = box.aspect_ratio
                    majority_dir = box.direction
                if 1.0 / box.aspect_ratio > max_aspect_ratio :
                    max_aspect_ratio = 1.0 / box.aspect_ratio
                    majority_dir = box.direction
        else :
            majority_dir = majority_dir_top_2[0][0]

        # sort textlines
        if majority_dir == 'h':
            nodes = sorted(nodes, key=lambda x: bboxes[x].centroid[1])
        elif majority_dir == 'v':
            nodes = sorted(nodes, key=lambda x: -bboxes[x].centroid[0])
        txtlns = np.array(bboxes)[nodes]

        # yield overall bbox and sorted indices
        yield txtlns, (fg_r, fg_g, fg_b), (bg_r, bg_g, bg_b)

async def dispatch(textlines: List[Quadrilateral], width: int, height: int, config, verbose: bool = False) -> List[TextBlock]:
    # 启用调试模式 (临时)
    debug = verbose
    # 获取边缘距离比例阈值
    edge_ratio_threshold = getattr(config.ocr, 'merge_edge_ratio_threshold', 0.0)
    text_regions: List[TextBlock] = []
    for (txtlns, fg_color, bg_color) in merge_bboxes_text_region(textlines, width, height, debug=debug, edge_ratio_threshold=edge_ratio_threshold):
        # --- 在创建TextBlock之前进行去重 ---
        unique_txtlns = []
        seen_coords = set()
        for txtln in txtlns:
            # 将坐标数组转换为可哈希的元组以进行比较
            coords_tuple = tuple(txtln.pts.reshape(-1))
            if coords_tuple not in seen_coords:
                seen_coords.add(coords_tuple)
                unique_txtlns.append(txtln)
        # --- 去重结束 ---

        # 如果去重后没有任何行，则跳过此区域
        if not unique_txtlns:
            continue

        total_logprobs = 0
        # 使用去重后的 unique_txtlns
        for txtln in unique_txtlns:
            total_logprobs += np.log(txtln.prob) * txtln.area
        total_logprobs /= sum([txtln.area for txtln in unique_txtlns])

        font_size = int(min([txtln.font_size for txtln in unique_txtlns]))
        
        # 计算平均角度
        angle = np.rad2deg(np.mean([txtln.angle for txtln in unique_txtlns])) - 90
        
        # 检查是否有任何原始文本框接近 90 度（即调整后接近 0 度）
        # 如果有，说明有正常的垂直/水平文本框，整个合并后的文本框角度应该归零
        original_angles_deg = [np.rad2deg(txtln.angle) for txtln in unique_txtlns]
        has_near_90_degree = any(abs(orig_angle - 90.0) <= 1.0 for orig_angle in original_angles_deg)
        
        if has_near_90_degree:
            # 如果有接近 90 度的原始文本框，归零
            angle = 0
        elif abs(angle) < 3:
            # 否则，使用原来的小角度归零逻辑
            angle = 0
        
        lines = [txtln.pts for txtln in unique_txtlns]
        texts = [txtln.text for txtln in unique_txtlns]
        region = TextBlock(lines, texts, font_size=font_size, angle=angle, prob=np.exp(total_logprobs),
                           fg_color=fg_color, bg_color=bg_color)
        text_regions.append(region)
    return text_regions
