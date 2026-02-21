import math
import re
from bisect import bisect_left
from dataclasses import dataclass
from typing import Any, List, Tuple

from . import text_render


@dataclass
class NoBrLayoutResult:
    text_with_br: str
    font_size: int
    n_segments: int
    required_width: float
    required_height: float


def _normalize_no_br_text(text: str) -> str:
    return re.sub(r"\s*(\[BR\]|<br>|【BR】)\s*", "", text or "", flags=re.IGNORECASE)


def _calculate_uniformity(values: List[float]) -> float:
    if not values or len(values) <= 1:
        return 0.0
    mean_v = sum(values) / len(values)
    if mean_v <= 0:
        return float("inf")
    variance = sum((v - mean_v) ** 2 for v in values) / len(values)
    return math.sqrt(variance) / mean_v


def _hyphenate_enabled(config: Any) -> bool:
    return not (config and hasattr(config, "render") and getattr(config.render, "no_hyphenation", False))


def _prepare_vertical_text(text: str, config: Any) -> str:
    prepared = text
    if config and hasattr(config, "render") and getattr(config.render, "auto_rotate_symbols", False):
        prepared = text_render.auto_add_horizontal_tags(prepared)
    return prepared


def _strip_h_tags(text: str) -> str:
    return re.sub(r"</?H>", "", text or "", flags=re.IGNORECASE)


def _calc_horizontal_layout(
    font_size: int,
    text: str,
    max_width: int,
    target_lang: str,
    hyphenate: bool
) -> Tuple[List[str], List[int]]:
    width = max(1, int(max_width))
    lang = target_lang or "en_US"
    is_cjk = hasattr(text_render, "is_cjk_lang") and text_render.is_cjk_lang(lang.lower())
    if is_cjk:
        lines, widths = text_render.calc_horizontal_cjk(font_size, text, width)
    else:
        lines, widths = text_render.calc_horizontal(
            font_size,
            text,
            max_width=width,
            max_height=99999,
            language=lang,
            hyphenate=hyphenate,
        )
    return lines or [], widths or []


def _calc_vertical_layout(
    font_size: int,
    text: str,
    max_height: int,
    config: Any
) -> Tuple[List[str], List[int]]:
    prepared = _prepare_vertical_text(text, config)
    height = max(1, int(max_height))
    lines, heights = text_render.calc_vertical(font_size, prepared, max_height=height, config=config)
    return lines or [], heights or []


def _insert_br_by_pixel_budget(text: str, n_segments: int, font_size: int, horizontal: bool) -> str:
    if not text or n_segments <= 1:
        return text

    text_len = len(text)
    if text_len <= 1:
        return text

    n_segments = max(1, min(n_segments, text_len))
    n_breaks = n_segments - 1
    if n_breaks <= 0:
        return text

    if horizontal:
        advances = [max(0, text_render.get_char_offset_x(font_size, c)) for c in text]
    else:
        advances = [max(0, text_render.get_char_offset_y(font_size, c)) for c in text]

    prefix = []
    total = 0
    for adv in advances:
        total += adv
        prefix.append(total)

    if total <= 0:
        step = text_len / n_segments
        break_positions = []
        prev = 0
        for k in range(1, n_segments):
            pos = int(round(step * k))
            pos = max(prev + 1, min(pos, text_len - (n_segments - k)))
            break_positions.append(pos)
            prev = pos
    else:
        break_positions = []
        prev = 0
        for k in range(1, n_segments):
            target = total * (k / n_segments)
            min_pos = prev + 1
            max_pos = text_len - (n_segments - k)
            if min_pos > max_pos:
                break

            idx = bisect_left(prefix, target)
            candidates = []
            for candidate_idx in (idx - 1, idx):
                pos = candidate_idx + 1
                if min_pos <= pos <= max_pos:
                    candidates.append(pos)

            if candidates:
                pos = min(candidates, key=lambda p: abs(prefix[p - 1] - target))
            else:
                pos = min(max(idx + 1, min_pos), max_pos)

            break_positions.append(pos)
            prev = pos

    if not break_positions:
        return text

    break_set = set(break_positions)
    out = []
    for i, ch in enumerate(text, start=1):
        out.append(ch)
        if i in break_set and i < text_len:
            out.append("[BR]")
    return "".join(out)


def _find_best_lines_for_target_segments(
    clean_text: str,
    font_size: int,
    horizontal: bool,
    target_segments: int,
    target_lang: str,
    config: Any,
) -> List[str]:
    if not clean_text:
        return []

    hyphenate = _hyphenate_enabled(config)

    if horizontal:
        base_lines, base_metrics = _calc_horizontal_layout(font_size, clean_text, 99999, target_lang, hyphenate)
        if base_metrics:
            total_budget = max(1, int(max(base_metrics)))
        else:
            total_budget = max(1, int(text_render.get_string_width(font_size, clean_text)))
    else:
        base_lines, base_metrics = _calc_vertical_layout(font_size, clean_text, 99999, config)
        if base_metrics:
            total_budget = max(1, int(max(base_metrics)))
        else:
            total_budget = max(1, int(text_render.get_string_height(font_size, clean_text)))

    _ = base_lines
    min_budget = max(1, int(font_size))
    max_budget = max(min_budget, total_budget)
    target_segments = max(1, target_segments)

    evaluated = {}

    def evaluate(budget: int):
        budget = max(min_budget, min(int(budget), max_budget))
        if budget in evaluated:
            return evaluated[budget]

        if horizontal:
            lines, metrics = _calc_horizontal_layout(font_size, clean_text, budget, target_lang, hyphenate)
        else:
            lines, metrics = _calc_vertical_layout(font_size, clean_text, budget, config)

        if not lines:
            evaluated[budget] = None
            return None

        line_count = len(lines)
        uniformity = _calculate_uniformity(metrics if metrics else [len(line) for line in lines])
        score = (abs(line_count - target_segments), 1 if line_count > target_segments else 0, uniformity)
        evaluated[budget] = (score, lines, line_count)
        return evaluated[budget]

    low, high = min_budget, max_budget
    for _ in range(24):
        if low > high:
            break
        mid = (low + high) // 2
        result = evaluate(mid)
        if result is None:
            break
        _, _, line_count = result
        if line_count > target_segments:
            low = mid + 1
        else:
            high = mid - 1

    anchors = {min_budget, max_budget, low, high, low - 1, low + 1, high - 1, high + 1}
    base = max_budget / max(1, target_segments)
    for factor in (0.75, 0.9, 1.0, 1.1, 1.25):
        anchors.add(int(round(base * factor)))
    for anchor in anchors:
        evaluate(anchor)

    candidates = [v for v in evaluated.values() if v is not None]
    if not candidates:
        return []
    _, best_lines, _ = min(candidates, key=lambda item: item[0])
    if not horizontal:
        return [_strip_h_tags(line) for line in best_lines]
    return best_lines


def _measure_required_size(
    text_with_br: str,
    font_size: int,
    horizontal: bool,
    line_spacing_multiplier: float,
    target_lang: str,
    config: Any,
) -> Tuple[int, float, float]:
    hyphenate = _hyphenate_enabled(config)

    if horizontal:
        lines, widths = _calc_horizontal_layout(font_size, text_with_br, 99999, target_lang, hyphenate)
        n = max(1, len(lines))
        spacing_y = int(font_size * 0.01 * line_spacing_multiplier)
        required_width = max(widths) if widths else text_render.get_string_width(font_size, _normalize_no_br_text(text_with_br))
        required_height = font_size * n + spacing_y * max(0, n - 1)
        return n, float(required_width), float(required_height)

    lines, heights = _calc_vertical_layout(font_size, text_with_br, 99999, config)
    n = max(1, len(lines))
    spacing_x = int(font_size * 0.2 * line_spacing_multiplier)
    required_height = max(heights) if heights else text_render.get_string_height(font_size, _normalize_no_br_text(text_with_br))
    required_width = font_size * n + spacing_x * max(0, n - 1)
    return n, float(required_width), float(required_height)


def solve_no_br_layout(
    text: str,
    horizontal: bool,
    seed_segments: int,
    seed_font_size: int,
    bubble_width: float,
    bubble_height: float,
    min_font_size: int,
    max_font_size: int,
    line_spacing_multiplier: float,
    target_lang: str = "en_US",
    config: Any = None,
    iterations: int = 3,
) -> NoBrLayoutResult:
    clean_text = _normalize_no_br_text(text)
    if not clean_text:
        return NoBrLayoutResult("", max(1, min_font_size), 1, 0.0, 0.0)

    text_len = len(clean_text)
    safe_min_font = max(1, int(min_font_size))
    safe_max_font = max(safe_min_font, int(max_font_size))
    current_font = max(safe_min_font, min(int(seed_font_size), safe_max_font))
    current_segments = max(1, min(int(seed_segments), text_len))
    line_spacing_multiplier = line_spacing_multiplier or 1.0

    bw = bubble_width if isinstance(bubble_width, (int, float)) and bubble_width > 0 else 1.0
    bh = bubble_height if isinstance(bubble_height, (int, float)) and bubble_height > 0 else 1.0

    for _ in range(max(1, int(iterations))):
        lines = _find_best_lines_for_target_segments(
            clean_text,
            current_font,
            horizontal,
            current_segments,
            target_lang,
            config,
        )
        if lines and len(lines) > 1:
            text_with_br = "[BR]".join(lines)
        elif current_segments > 1:
            text_with_br = _insert_br_by_pixel_budget(clean_text, current_segments, current_font, horizontal)
        else:
            text_with_br = clean_text

        n_actual, required_width, required_height = _measure_required_size(
            text_with_br,
            current_font,
            horizontal,
            line_spacing_multiplier,
            target_lang,
            config,
        )

        if required_width <= 0 or required_height <= 0:
            break

        fit_scale = min(bw / required_width, bh / required_height)
        if not math.isfinite(fit_scale) or fit_scale <= 0:
            fit_scale = 1.0
        next_font = max(safe_min_font, min(int(current_font * fit_scale), safe_max_font))
        next_segments = max(1, min(n_actual, text_len))

        if next_font == current_font and next_segments == current_segments:
            return NoBrLayoutResult(text_with_br, current_font, n_actual, required_width, required_height)

        current_font = next_font
        current_segments = next_segments

    final_lines = _find_best_lines_for_target_segments(
        clean_text,
        current_font,
        horizontal,
        current_segments,
        target_lang,
        config,
    )
    if final_lines and len(final_lines) > 1:
        final_text = "[BR]".join(final_lines)
    elif current_segments > 1:
        final_text = _insert_br_by_pixel_budget(clean_text, current_segments, current_font, horizontal)
    else:
        final_text = clean_text

    n_final, required_width, required_height = _measure_required_size(
        final_text,
        current_font,
        horizontal,
        line_spacing_multiplier,
        target_lang,
        config,
    )
    return NoBrLayoutResult(final_text, current_font, n_final, required_width, required_height)
