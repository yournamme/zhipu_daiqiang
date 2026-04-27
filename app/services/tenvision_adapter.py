from __future__ import annotations

from typing import Any

import cv2
import numpy as np

try:
    from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR
except ImportError:
    EngineType = None
    LangDet = None
    LangRec = None
    ModelType = None
    OCRVersion = None
    RapidOCR = None

PROMPT_PREFIX = '请依次点击'
IGNORE_TEXTS = {
    '确定',
    '安全验证',
    'AI生成背景',
    'AI生',
    'AI生成',
    '刷新',
    '验证码',
}

_engine = None


def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    if RapidOCR is None:
        raise RuntimeError('缺少 rapidocr 依赖，无法使用 catpcha_v2 识别算法。')

    from app.config import get_settings

    settings = get_settings()
    onnx_threads = max(1, settings.tencent_ocr_onnx_threads)

    _engine = RapidOCR(
        params={
            'EngineConfig.onnxruntime.intra_op_num_threads': onnx_threads,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
            'Det.engine_type': EngineType.ONNXRUNTIME,
            'Det.lang_type': LangDet.CH,
            'Det.model_type': ModelType.MOBILE,
            'Det.ocr_version': OCRVersion.PPOCRV5,
            'Rec.engine_type': EngineType.ONNXRUNTIME,
            'Rec.lang_type': LangRec.CH,
            'Rec.model_type': ModelType.MOBILE,
            'Rec.ocr_version': OCRVersion.PPOCRV5,
        }
    )
    return _engine


def normalize_text(text):
    return (text or '').replace(' ', '').replace('\n', '').strip()


def extract_chinese_chars(text):
    return [char for char in normalize_text(text) if '\u4e00' <= char <= '\u9fff']


def is_prompt_like_text(text):
    compact = normalize_text(text)
    if not compact:
        return False
    return PROMPT_PREFIX in compact or '点击' in compact or compact.startswith('请')


def parse_prompt_chars(text):
    compact = normalize_text(text)
    if PROMPT_PREFIX in compact:
        compact = compact.split(PROMPT_PREFIX, 1)[1]
    compact = compact.replace('：', '').replace(':', '')
    return extract_chinese_chars(compact)


def order_points(points):
    pts = np.asarray(points, dtype=np.float32)
    if pts.shape != (4, 2):
        return pts
    sums = pts.sum(axis=1)
    diffs = np.diff(pts, axis=1).reshape(-1)
    top_left = pts[np.argmin(sums)]
    bottom_right = pts[np.argmax(sums)]
    top_right = pts[np.argmin(diffs)]
    bottom_left = pts[np.argmax(diffs)]
    return np.array([top_left, top_right, bottom_right, bottom_left], dtype=np.float32)


def poly_to_bbox(poly):
    xs = poly[:, 0]
    ys = poly[:, 1]
    x1 = float(xs.min())
    y1 = float(ys.min())
    x2 = float(xs.max())
    y2 = float(ys.max())
    return int(round(x1)), int(round(y1)), int(round(x2 - x1)), int(round(y2 - y1))


def bbox_iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh

    ix1 = max(ax, bx)
    iy1 = max(ay, by)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return float(inter / union) if union > 0 else 0.0


def crop_bbox(img, bbox, pad=2):
    x, y, w, h = bbox
    x1 = max(0, x - pad)
    y1 = max(0, y - pad)
    x2 = min(img.shape[1], x + w + pad)
    y2 = min(img.shape[0], y + h + pad)
    return img[y1:y2, x1:x2].copy(), (x1, y1, x2, y2)


def connected_components(mask, min_area=4):
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    comps = []
    for idx in range(1, num_labels):
        x, y, w, h, area = stats[idx]
        if area < min_area:
            continue
        comps.append({'bbox': (int(x), int(y), int(w), int(h)), 'area': int(area)})
    return comps


def bbox_from_mask(mask):
    ys, xs = np.where(mask > 0)
    if xs.size == 0:
        return None
    x1 = int(xs.min())
    x2 = int(xs.max()) + 1
    y1 = int(ys.min())
    y2 = int(ys.max()) + 1
    return x1, y1, x2 - x1, y2 - y1


def smooth_projection(values, window=5):
    if values.size < window or window <= 1:
        return values.astype(np.float32)
    kernel = np.ones(window, dtype=np.float32) / window
    return np.convolve(values.astype(np.float32), kernel, mode='same')


def contiguous_runs(flags):
    runs = []
    start = None
    for idx, flag in enumerate(flags):
        if flag and start is None:
            start = idx
        elif not flag and start is not None:
            runs.append((start, idx))
            start = None
    if start is not None:
        runs.append((start, len(flags)))
    return runs


def to_list(value):
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    return list(value)


def ocr_items(result, x_offset=0, y_offset=0):
    items = []
    boxes = to_list(getattr(result, 'boxes', None))
    txts = to_list(getattr(result, 'txts', None))
    scores = to_list(getattr(result, 'scores', None))
    for index, (poly, text, score) in enumerate(zip(boxes, txts, scores)):
        poly = order_points(np.asarray(poly, dtype=np.float32))
        bbox = poly_to_bbox(poly)
        x, y, w, h = bbox
        items.append(
            {
                'index': index,
                'poly': poly,
                'bbox': (x + x_offset, y + y_offset, w, h),
                'text': normalize_text(str(text)),
                'score': float(score),
                'area': int(w * h),
            }
        )
    return items


def find_prompt_item(items, image_h, image_w):
    prompt_candidates = []
    for item in items:
        text = item['text']
        x, y, w, h = item['bbox']
        if y > int(image_h * 0.22):
            continue
        chars = parse_prompt_chars(text)
        if PROMPT_PREFIX in text or ('点击' in text and len(chars) >= 2):
            prompt_candidates.append((len(chars), w, -y, item))

    if prompt_candidates:
        prompt_candidates.sort(reverse=True)
        return prompt_candidates[0][3]

    wide_top_items = [
        item
        for item in items
        if (
            item['bbox'][1] <= int(image_h * 0.18)
            and item['bbox'][2] >= int(image_w * 0.25)
            and is_prompt_like_text(item['text'])
        )
    ]
    if wide_top_items:
        return sorted(wide_top_items, key=lambda it: (it['bbox'][1], -it['bbox'][2]))[0]
    return None


def build_prompt_chars(items, image, engine):
    prompt_item = find_prompt_item(items, image.shape[0], image.shape[1])
    if prompt_item is not None:
        chars = parse_prompt_chars(prompt_item['text'])
        if len(chars) >= 2:
            return prompt_item, chars

    top_roi = image[: int(image.shape[0] * 0.14), :]
    top_result = engine(top_roi)
    top_items = ocr_items(top_result)
    prompt_item = find_prompt_item(top_items, top_roi.shape[0], top_roi.shape[1])
    if prompt_item is not None:
        chars = parse_prompt_chars(prompt_item['text'])
        if len(chars) >= 2:
            return prompt_item, chars

    raise RuntimeError('无法从 RapidOCR 结果中解析出提示字符。')


def is_ignored_item(item, prompt_item, image_h, image_w):
    text = item['text']
    if not text:
        return True
    if text in IGNORE_TEXTS:
        return True
    if any(keyword in text for keyword in ('AI', '确定', '安全验证', '生成背景')):
        return True
    if len(extract_chinese_chars(text)) == 0:
        return True
    x, y, w, h = item['bbox']
    if prompt_item is not None:
        # IOU 过滤：与提示文本区域重叠
        if bbox_iou(item['bbox'], prompt_item['bbox']) > 0.05:
            return True
        # Y 区间重叠过滤：与提示文本在同一行的字符均排除
        px, py, pw, ph = prompt_item['bbox']
        item_y2 = y + h
        prompt_y2 = py + ph
        if y < prompt_y2 and item_y2 > py:
            return True
    # 顶部宽文本过滤（覆盖 prompt_item 为 None 的降级情形）
    if y < int(image_h * 0.22) and w > int(image_w * 0.18) and '请' not in text:
        return True
    return False


def build_color_masks(crop):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    dark_mask = (gray < max(190, int(np.percentile(gray, 55)))).astype(np.uint8) * 255
    yellow_mask = (
        (hsv[:, :, 0] >= 8)
        & (hsv[:, :, 0] <= 55)
        & (hsv[:, :, 1] >= 35)
        & (hsv[:, :, 2] >= 60)
    ).astype(np.uint8) * 255
    adaptive_mask = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        21,
        11,
    )

    masks = [dark_mask, yellow_mask, adaptive_mask]
    cleaned = []
    for mask in masks:
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        mask = cv2.medianBlur(mask, 3)
        cleaned.append(mask)
    return cleaned


def choose_best_mask(crop, expected_count):
    masks = build_color_masks(crop)
    best_mask = masks[0]
    best_score = 1e18

    for mask in masks:
        comps = connected_components(mask, min_area=3)
        fg_ratio = float(np.count_nonzero(mask)) / max(mask.size, 1)
        score = abs(len(comps) - expected_count) * 3.0 + abs(fg_ratio - 0.18) * 4.0
        if score < best_score:
            best_score = score
            best_mask = mask

    return best_mask


def split_mask_to_boxes(mask, origin_x, origin_y, expected_count):
    h, w = mask.shape
    horizontal = w >= h
    comps = connected_components(mask, min_area=4)

    if len(comps) >= expected_count:
        comps = sorted(comps, key=lambda c: c['bbox'][0] if horizontal else c['bbox'][1])
        if len(comps) > expected_count:
            comps = sorted(comps, key=lambda c: c['area'], reverse=True)[:expected_count]
            comps = sorted(comps, key=lambda c: c['bbox'][0] if horizontal else c['bbox'][1])

        boxes = []
        for comp in comps:
            x, y, cw, ch = comp['bbox']
            boxes.append((origin_x + x, origin_y + y, cw, ch))
        return boxes

    axis = 0 if horizontal else 1
    projection = mask.sum(axis=axis).astype(np.float32) / 255.0
    projection = smooth_projection(projection, window=5)
    if projection.size == 0:
        return []

    threshold = max(1.0, float(projection.max()) * 0.12)
    active = projection >= threshold
    runs = [run for run in contiguous_runs(active) if (run[1] - run[0]) >= 2]

    boxes = []
    if len(runs) >= expected_count:
        chosen_runs = runs[:expected_count]
        for start, end in chosen_runs:
            if horizontal:
                part = mask[:, start:end]
                bbox = bbox_from_mask(part)
                if bbox is None:
                    boxes.append((origin_x + start, origin_y, max(1, end - start), h))
                else:
                    x, y, pw, ph = bbox
                    boxes.append((origin_x + start + x, origin_y + y, pw, ph))
            else:
                part = mask[start:end, :]
                bbox = bbox_from_mask(part)
                if bbox is None:
                    boxes.append((origin_x, origin_y + start, w, max(1, end - start)))
                else:
                    x, y, pw, ph = bbox
                    boxes.append((origin_x + x, origin_y + start + y, pw, ph))
        return boxes

    if horizontal:
        edges = np.linspace(0, w, expected_count + 1).astype(int)
        for idx in range(expected_count):
            start, end = edges[idx], edges[idx + 1]
            part = mask[:, start:end]
            bbox = bbox_from_mask(part)
            if bbox is None:
                boxes.append((origin_x + start, origin_y, max(1, end - start), h))
            else:
                x, y, pw, ph = bbox
                boxes.append((origin_x + start + x, origin_y + y, pw, ph))
    else:
        edges = np.linspace(0, h, expected_count + 1).astype(int)
        for idx in range(expected_count):
            start, end = edges[idx], edges[idx + 1]
            part = mask[start:end, :]
            bbox = bbox_from_mask(part)
            if bbox is None:
                boxes.append((origin_x, origin_y + start, w, max(1, end - start)))
            else:
                x, y, pw, ph = bbox
                boxes.append((origin_x + x, origin_y + start + y, pw, ph))

    return boxes


def split_boxes_are_reasonable(parent_bbox, boxes, expected_count):
    if len(boxes) != expected_count or expected_count <= 0:
        return False

    px, py, pw, ph = parent_bbox
    parent_area = max(1, int(pw * ph))
    horizontal = pw >= ph
    ordered = sorted(boxes, key=lambda box: box[0] if horizontal else box[1])
    axis_len = max(pw, ph)
    minor_len = max(1, min(pw, ph))
    min_minor = max(10, int(minor_len * 0.15))
    min_area = max(160, int(parent_area * 0.012))
    areas = []
    previous_end = None

    for box in ordered:
        x, y, w, h = box
        if w <= 0 or h <= 0:
            return False
        if x < px - 6 or y < py - 6 or (x + w) > (px + pw + 6) or (y + h) > (py + ph + 6):
            return False

        area = int(w * h)
        areas.append(area)
        if area < min_area:
            return False
        if area > int(parent_area * 0.88):
            return False
        if (h if horizontal else w) < min_minor:
            return False

        start = x if horizontal else y
        end = start + (w if horizontal else h)
        if previous_end is not None and start < previous_end - max(6, int(axis_len * 0.04)):
            return False
        previous_end = end

    if not areas:
        return False
    if min(areas) * 16 < max(areas):
        return False
    return True


def split_bbox_with_yellow_segments(crop, origin_x, origin_y, expected_count, horizontal):
    h, w = crop.shape[:2]
    if expected_count <= 0 or h <= 0 or w <= 0:
        return []

    boxes = []
    axis_len = w if horizontal else h
    edges = np.linspace(0, axis_len, expected_count + 1).astype(int)

    for idx in range(expected_count):
        start, end = int(edges[idx]), int(edges[idx + 1])
        if end <= start:
            end = start + 1

        if horizontal:
            part = crop[:, start:end]
        else:
            part = crop[start:end, :]

        bbox = bbox_from_mask(hsv_yellow_mask(part))
        if bbox is None:
            bbox = bbox_from_mask(choose_best_mask(part, 1))

        if bbox is None:
            if horizontal:
                boxes.append((origin_x + start, origin_y, max(1, end - start), h))
            else:
                boxes.append((origin_x, origin_y + start, w, max(1, end - start)))
            continue

        x, y, bw, bh = bbox
        if horizontal:
            boxes.append((origin_x + start + x, origin_y + y, bw, bh))
        else:
            boxes.append((origin_x + x, origin_y + start + y, bw, bh))

    return boxes


def recognize_prompt_boxes(image, boxes, prompt_chars, engine):
    if not boxes or engine is None:
        return []

    crops = []
    for box in boxes:
        crop, _ = crop_bbox(image, box, pad=8)
        if crop.size == 0:
            crops.append(np.zeros((8, 8, 3), dtype=np.uint8))
            continue
        crops.append(cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))

    result = engine.recognize_txt(crops)
    texts = to_list(getattr(result, 'txts', None))
    scores = to_list(getattr(result, 'scores', None))
    prompt_set = set(prompt_chars or [])
    candidates = []

    for index, box in enumerate(boxes):
        source_text = normalize_text(str(texts[index])) if index < len(texts) else ''
        score = float(scores[index]) if index < len(scores) else 0.0
        chars = extract_chinese_chars(source_text)
        exact_char = next((char for char in chars if char in prompt_set), '')
        candidates.append(
            {
                'bbox': tuple(int(v) for v in box),
                'char': exact_char,
                'text': exact_char,
                'score': score,
                'source_text': source_text,
                'source_index': index,
                'source': 'split_box_recognize_txt',
                'area': int(box[2] * box[3]),
            }
        )

    return candidates


def repair_candidates_by_prompt(candidates, prompt_chars):
    if len(prompt_chars) < 2 or not candidates:
        return candidates

    used_ids = set()
    missing_chars = []
    for prompt_char in prompt_chars:
        options = [
            candidate
            for candidate in candidates
            if id(candidate) not in used_ids and candidate.get('char') == prompt_char
        ]
        if not options:
            missing_chars.append(prompt_char)
            continue
        chosen = sorted(
            options,
            key=lambda item: (float(item.get('score') or 0), int(item.get('area') or 0)),
            reverse=True,
        )[0]
        used_ids.add(id(chosen))

    unknown_candidates = [
        candidate
        for candidate in candidates
        if id(candidate) not in used_ids and not candidate.get('char')
    ]
    if len(missing_chars) == 1 and len(unknown_candidates) == 1:
        candidate = unknown_candidates[0]
        candidate['char'] = missing_chars[0]
        candidate['text'] = missing_chars[0]
        candidate['score'] = max(min(float(candidate.get('score') or 0) * 0.9, 0.85), 0.55)
        candidate['source'] = f"{candidate.get('source') or 'prompt_fill'}_prompt_fill"

    return candidates


def split_ocr_item(image, item, prompt_chars=None, engine=None):
    text_chars = extract_chinese_chars(item['text'])
    if len(text_chars) == 0:
        return []
    if len(text_chars) == 1:
        return [{**item, 'char': text_chars[0]}]

    crop, (x1, y1, x2, y2) = crop_bbox(image, item['bbox'], pad=4)
    mask = choose_best_mask(crop, len(text_chars))
    local_boxes = split_mask_to_boxes(mask, x1, y1, len(text_chars))
    horizontal = item['bbox'][2] >= item['bbox'][3]
    if not split_boxes_are_reasonable(item['bbox'], local_boxes, len(text_chars)):
        local_boxes = split_bbox_with_yellow_segments(crop, x1, y1, len(text_chars), horizontal)
    if not split_boxes_are_reasonable(item['bbox'], local_boxes, len(text_chars)):
        return []

    ordered = sorted(
        local_boxes,
        key=lambda box: box[0] if horizontal else box[1],
    )
    recognized = recognize_prompt_boxes(image, ordered, prompt_chars or [], engine) if prompt_chars and engine else []
    prompt_set = set(prompt_chars or [])

    split_items = []
    for index, (char, box) in enumerate(zip(text_chars, ordered)):
        recognized_item = recognized[index] if index < len(recognized) else None
        resolved_char = ''
        resolved_score = item['score']
        resolved_source = 'split_source_text'
        resolved_source_text = item['text']

        if recognized_item is not None and recognized_item.get('char'):
            resolved_char = recognized_item['char']
            resolved_score = max(float(recognized_item.get('score') or 0), float(item['score']))
            resolved_source = recognized_item.get('source') or resolved_source
            resolved_source_text = recognized_item.get('source_text') or item['text']
        elif char in prompt_set or not prompt_set:
            resolved_char = char
        elif recognized_item is not None:
            resolved_score = float(recognized_item.get('score') or 0)
            resolved_source = recognized_item.get('source') or resolved_source
            resolved_source_text = recognized_item.get('source_text') or item['text']

        split_items.append(
            {
                'bbox': tuple(int(v) for v in box),
                'char': resolved_char,
                'text': resolved_char,
                'score': resolved_score,
                'source_text': resolved_source_text,
                'source_index': item['index'],
                'source': resolved_source,
                'area': int(box[2] * box[3]),
            }
        )
    return split_items


def build_candidate_chars(image, items, prompt_item, image_h, image_w, prompt_chars=None, engine=None):
    candidates = []
    for item in items:
        if is_ignored_item(item, prompt_item, image_h, image_w):
            continue
        candidates.extend(split_ocr_item(image, item, prompt_chars=prompt_chars, engine=engine))
    candidates = [
        cand
        for cand in candidates
        if len(cand.get('char') or '') == 1 or (prompt_chars and not cand.get('char'))
    ]
    candidates = sorted(candidates, key=lambda cand: (cand['bbox'][1], cand['bbox'][0]))
    candidates = repair_candidates_by_prompt(candidates, prompt_chars or [])
    return candidates


def match_prompt_to_candidates(prompt_chars, candidate_chars):
    buckets = {}
    for candidate in candidate_chars:
        buckets.setdefault(candidate['char'], []).append(candidate)

    for char in buckets:
        buckets[char].sort(key=lambda cand: (-cand['score'], -cand['area']))

    used_ids = set()
    click_items = []
    for prompt_char in prompt_chars:
        chosen = None
        for candidate in buckets.get(prompt_char, []):
            if id(candidate) not in used_ids:
                chosen = candidate
                break

        if chosen is None:
            for candidate in candidate_chars:
                if id(candidate) not in used_ids and candidate['char'] == prompt_char:
                    chosen = candidate
                    break

        if chosen is None:
            for candidate in candidate_chars:
                if id(candidate) not in used_ids:
                    chosen = candidate
                    break

        if chosen is None:
            click_items.append(None)
            continue

        used_ids.add(id(chosen))
        click_items.append(chosen)

    return click_items


def build_yellow_component_boxes(image, expected_count):
    if expected_count <= 0:
        return []

    image_h, image_w = image.shape[:2]
    min_w = max(28, int(image_w * 0.04))
    min_h = max(36, int(image_h * 0.075))
    max_w = max(min_w, int(image_w * 0.28))
    max_h = max(min_h, int(image_h * 0.28))
    min_area = max(900, int(image_w * image_h * 0.0025))

    mask = hsv_yellow_mask(image)
    boxes = []
    for comp in connected_components(mask, min_area=80):
        x, y, w, h = comp['bbox']
        bbox_area = w * h
        if w < min_w or h < min_h:
            continue
        if w > max_w or h > max_h:
            continue
        if bbox_area < min_area:
            continue
        boxes.append(
            {
                'bbox': (int(x), int(y), int(w), int(h)),
                'area': int(comp['area']),
                'bbox_area': int(bbox_area),
            }
        )

    if len(boxes) < expected_count:
        return []

    if len(boxes) > expected_count:
        boxes = sorted(boxes, key=lambda item: (item['bbox_area'], item['area']), reverse=True)[:expected_count]

    return [item['bbox'] for item in sorted(boxes, key=lambda item: (item['bbox'][1], item['bbox'][0]))]


def recognize_yellow_boxes(image, boxes, prompt_chars, engine):
    if not boxes:
        return []

    crops = []
    for box in boxes:
        crop, _ = crop_bbox(image, box, pad=8)
        crops.append(cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC))

    result = engine.recognize_txt(crops)
    texts = to_list(getattr(result, 'txts', None))
    scores = to_list(getattr(result, 'scores', None))
    prompt_set = set(prompt_chars)
    candidates = []

    for index, box in enumerate(boxes):
        text = normalize_text(str(texts[index])) if index < len(texts) else ''
        score = float(scores[index]) if index < len(scores) else 0.0
        chars = extract_chinese_chars(text)
        exact_char = next((char for char in chars if char in prompt_set), '')
        candidates.append(
            {
                'bbox': tuple(int(v) for v in box),
                'char': exact_char,
                'text': exact_char,
                'score': score,
                'source_text': text,
                'source_index': index,
                'source': 'yellow_component_rec',
                'area': int(box[2] * box[3]),
            }
        )

    return fill_missing_prompt_chars(candidates, prompt_chars)


def fill_missing_prompt_chars(candidates, prompt_chars):
    used_ids = set()
    resolved = []

    for prompt_char in prompt_chars:
        options = [
            candidate
            for candidate in candidates
            if id(candidate) not in used_ids and candidate.get('char') == prompt_char
        ]
        if not options:
            resolved.append(None)
            continue
        chosen = sorted(options, key=lambda item: (float(item.get('score') or 0), int(item.get('area') or 0)), reverse=True)[0]
        used_ids.add(id(chosen))
        resolved.append(chosen)

    missing_indexes = [index for index, item in enumerate(resolved) if item is None]
    unknown_candidates = [
        candidate
        for candidate in candidates
        if id(candidate) not in used_ids and not candidate.get('char')
    ]
    if len(missing_indexes) == 1 and len(unknown_candidates) == 1:
        missing_char = prompt_chars[missing_indexes[0]]
        candidate = dict(unknown_candidates[0])
        candidate['char'] = missing_char
        candidate['text'] = missing_char
        candidate['score'] = max(min(float(candidate.get('score') or 0) * 0.9, 0.85), 0.55)
        candidate['source'] = 'yellow_component_prompt_fill'
        resolved[missing_indexes[0]] = candidate

    if any(item is None for item in resolved):
        return candidates

    return [dict(item) for item in resolved]


def build_yellow_fallback_candidates(image, prompt_chars, engine):
    boxes = build_yellow_component_boxes(image, len(prompt_chars))
    if len(boxes) != len(prompt_chars):
        return []
    candidates = recognize_yellow_boxes(image, boxes, prompt_chars, engine)
    if len(candidates) != len(prompt_chars):
        return []
    if not all(candidate.get('char') in prompt_chars for candidate in candidates):
        return []
    return candidates


def draw_result(img, prompt_item, candidate_items, click_items):
    vis = img.copy()
    if prompt_item is not None:
        x, y, w, h = prompt_item['bbox']
        cv2.rectangle(vis, (x, y), (x + w, y + h), (255, 0, 0), 2)

    for item in candidate_items:
        x, y, w, h = item['bbox']
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 255), 1)

    for index, item in enumerate(click_items, start=1):
        if item is None:
            continue
        x, y, w, h = item['bbox']
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
        cv2.circle(vis, (x + w // 2, y + h // 2), 14, (0, 255, 0), 2)
        cv2.putText(
            vis,
            str(index),
            (x + w // 2 - 8, y + h // 2 + 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 255, 0),
            2,
        )

    return vis


def run_pipeline_bytes(image_bytes: bytes, prompt_text: str | None = None, include_debug: bool = False):
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError('无法解码图片')

    engine = get_engine()
    ocr_result = engine(image)
    items = ocr_items(ocr_result)

    prompt_item = None
    prompt_chars = parse_prompt_chars(prompt_text) if prompt_text else []

    if len(prompt_chars) < 2:
        try:
            found_prompt_item, found_prompt_chars = build_prompt_chars(items, image, engine)
            prompt_item = found_prompt_item
            prompt_chars = found_prompt_chars
        except RuntimeError:
            raise RuntimeError('未识别到验证码提示文本，当前截图疑似不是验证码弹窗。')

    if prompt_item is not None and not is_prompt_like_text(prompt_item['text']) and len(parse_prompt_chars(prompt_item['text'])) <= 2:
        raise RuntimeError(f'识别到的顶部文本不像验证码提示：{prompt_item["text"]}')

    candidate_chars = build_candidate_chars(
        image,
        items,
        prompt_item,
        image.shape[0],
        image.shape[1],
        prompt_chars=prompt_chars,
        engine=engine,
    )
    click_items = match_prompt_to_candidates(prompt_chars, candidate_chars)
    fallback_method = ''

    if any(item is None for item in click_items) and len(prompt_chars) < 2:
        top_result = engine(image[: int(image.shape[0] * 0.16), :])
        top_items = ocr_items(top_result)
        try:
            extra_prompt_item, extra_prompt_chars = build_prompt_chars(top_items, image, engine)
            if len(extra_prompt_chars) > len(prompt_chars):
                prompt_item = extra_prompt_item
                prompt_chars = extra_prompt_chars
                candidate_chars = build_candidate_chars(
                    image,
                    items,
                    prompt_item,
                    image.shape[0],
                    image.shape[1],
                    prompt_chars=prompt_chars,
                    engine=engine,
                )
                click_items = match_prompt_to_candidates(prompt_chars, candidate_chars)
        except RuntimeError:
            pass

    if len(prompt_chars) >= 2:
        current_matches = sum(1 for item in click_items if item is not None)
        yellow_candidates = build_yellow_fallback_candidates(image, prompt_chars, engine)
        yellow_click_items = match_prompt_to_candidates(prompt_chars, yellow_candidates)
        yellow_matches = sum(1 for item in yellow_click_items if item is not None)
        if yellow_matches == len(prompt_chars) and yellow_matches > current_matches:
            candidate_chars = yellow_candidates
            click_items = yellow_click_items
            fallback_method = 'yellow_component_recognize_txt'

    vis = draw_result(image, prompt_item, candidate_chars, click_items) if include_debug else None

    result = {
        'image_width': int(image.shape[1]),
        'image_height': int(image.shape[0]),
        'prompt_text': prompt_item['text'] if prompt_item is not None else normalize_text(prompt_text),
        'target_chars': prompt_chars,
        'prompt_bbox': prompt_item['bbox'] if prompt_item is not None else None,
        'candidate_boxes': [item['bbox'] for item in candidate_chars],
        'click_boxes': [item['bbox'] if item is not None else None for item in click_items],
        'click_chars': [item['char'] if item is not None else None for item in click_items],
        'click_scores': [float(item['score']) if item is not None else 0.0 for item in click_items],
        'fallback_method': fallback_method,
    }
    return result, vis


def hsv_yellow_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    lower = np.array([10, 60, 110], dtype=np.uint8)
    upper = np.array([48, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mask = cv2.dilate(mask, np.ones((2, 2), np.uint8), iterations=1)
    return mask


def gray_black_mask(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    mask = ((gray < 145).astype(np.uint8) * 255)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    return mask


def analyze_image_bytes(
    image_bytes: bytes,
    bg_offset: dict | None = None,
    prompt_text: str | None = None,
    use_deep_learning: bool | None = None,
    include_debug: bool = False,
) -> dict[str, Any]:
    result, vis = run_pipeline_bytes(image_bytes, prompt_text, include_debug=include_debug)

    points = []
    for idx, box in enumerate(result['click_boxes']):
        if box is None:
            continue
        x, y, w, h = box
        center_x = x + w // 2
        center_y = y + h // 2

        out_x = float(center_x)
        out_y = float(center_y)
        if bg_offset:
            out_x -= float(bg_offset['x'])
            out_y -= float(bg_offset['y'])

        label = result['click_chars'][idx]
        if label is None and idx < len(result['target_chars']):
            label = result['target_chars'][idx]

        points.append(
            {
                'order': idx + 1,
                'x': int(round(out_x)),
                'y': int(round(out_y)),
                'label': label or '',
            }
        )

    matched_scores = [score for score, box in zip(result['click_scores'], result['click_boxes']) if box is not None]
    prompt_len = len(result['target_chars'])
    matched_ratio = (len(points) / prompt_len) if prompt_len else 0.0
    ocr_confidence = (sum(matched_scores) / len(matched_scores)) if matched_scores else 0.0
    confidence = round(float(matched_ratio * ocr_confidence), 4)

    debug_png = b''
    if include_debug:
        success, encoded = cv2.imencode('.png', vis)
        debug_png = encoded.tobytes() if success else b''

    return {
        'width': result['image_width'],
        'height': result['image_height'],
        'points': points,
        'candidate_count': len(result['candidate_boxes']),
        'confidence': confidence,
        'debug_png': debug_png,
        'target_chars': result['target_chars'],
        'prompt_text': result['prompt_text'],
        'prompt_bbox': result['prompt_bbox'],
        'candidate_boxes': result['candidate_boxes'],
        'click_boxes': result['click_boxes'],
        'click_chars': result['click_chars'],
        'fallback_method': result.get('fallback_method') or '',
        'recognized_text': result['prompt_text'],
        'algorithm': 'catpcha_v2',
        'use_deep_learning': bool(use_deep_learning) if use_deep_learning is not None else False,
    }
