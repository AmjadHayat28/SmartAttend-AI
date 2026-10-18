"""Classroom (group-photo) face detection: orientation, multi-scale, tiling and merging.

Pure numpy around an injected detector, so every step is unit-testable without a model:

    detect(img, input_sizes) -> (boxes (N×5: x1, y1, x2, y2, score), kps (N×5×2) | None)

Pipeline (see detect_classroom):
1. Orientation. Group photos forwarded through messaging apps often arrive sideways with no
   EXIF tag (the upload pipeline already applies EXIF when present). A cheap low-resolution
   pass at 0°, 90° and 270° picks the orientation whose faces score clearly best; the image is
   only rotated when that evidence is strong. All boxes are mapped back to ORIGINAL pixels.
2. Full image at the configured scales (the detector letterboxes the whole photo into each
   input size).
3. Optional overlapping tiles at native resolution for photos much larger than the detector
   input, so small/distant faces are not shrunk below what the detector can see. Detections
   touching an interior tile edge are dropped: the overlap guarantees the whole face is in a
   neighbouring tile.
4. Merge: full-image detections first, then tile detections only where no full-image face is
   (IoU / containment). One physical face → one detection; tiles only ADD missed faces.

Face-detection confidence here is independent of identity similarity (matching.py).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np

DetectFn = Callable[[np.ndarray, list[tuple[int, int]]], tuple[np.ndarray, np.ndarray | None]]


@dataclass(frozen=True)
class ClassroomDetectConfig:
    sizes: tuple[tuple[int, int], ...] = ((640, 640), (1024, 1024))
    tiling: bool = True
    tile_size: int = 1024
    tile_overlap: float = 0.25
    tile_min_ratio: float = 1.25  # tile only when the long side exceeds tile_size × this
    auto_orient: bool = True
    orient_size: int = 640
    orient_gain: float = 1.5  # sideways wins if its score sum is this many times upright's…
    orient_margin: float = 0.05  # …or it finds as many faces with a mean score this much higher
    orient_skip_mean: float = 0.80  # upright faces this confident → no sideways passes (saves time)
    nms_iou: float = 0.4
    containment: float = 0.8  # intersection / smaller-box area at which boxes are the same face
    edge_margin: int = 4  # px from an interior tile edge that counts as "cut by the tile"


@dataclass
class ClassroomDetection:
    boxes: np.ndarray  # (N, 5) x1, y1, x2, y2, score — ORIGINAL image pixels
    kps: np.ndarray | None  # (N, 5, 2) landmarks in ORIGINAL pixels
    rotation: int = 0  # degrees clockwise applied before detection (0, 90, 270)
    tiles: int = 0
    raw_detections: int = 0  # before merging
    detection_ms: float = 0.0
    passes: list[str] = field(default_factory=list)
    # Where the detection time went (ms): "orient" check, "full" image passes, "tiles".
    stage_ms: dict[str, float] = field(default_factory=dict)

    @property
    def merged_duplicates(self) -> int:
        return max(0, self.raw_detections - len(self.boxes))


# ── Geometry ──────────────────────────────────────────────────────────────


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU between box sets a (N×4+) and b (M×4+), x1y1x2y2."""
    ax1, ay1, ax2, ay2 = (a[:, i][:, None] for i in range(4))
    bx1, by1, bx2, by2 = (b[:, i][None, :] for i in range(4))
    iw = np.clip(np.minimum(ax2, bx2) - np.maximum(ax1, bx1), 0, None)
    ih = np.clip(np.minimum(ay2, by2) - np.maximum(ay1, by1), 0, None)
    inter = iw * ih
    area_a = (ax2 - ax1) * (ay2 - ay1)
    area_b = (bx2 - bx1) * (by2 - by1)
    union = area_a + area_b - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


def _containment(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """intersection / area of the smaller box."""
    ax1, ay1, ax2, ay2 = (a[:, i][:, None] for i in range(4))
    bx1, by1, bx2, by2 = (b[:, i][None, :] for i in range(4))
    iw = np.clip(np.minimum(ax2, bx2) - np.maximum(ax1, bx1), 0, None)
    ih = np.clip(np.minimum(ay2, by2) - np.maximum(ay1, by1), 0, None)
    smaller = np.minimum((ax2 - ax1) * (ay2 - ay1), (bx2 - bx1) * (by2 - by1))
    return np.where(smaller > 0, iw * ih / np.maximum(smaller, 1e-9), 0.0)


def merge_boxes(boxes: np.ndarray, iou: float = 0.4, containment: float = 0.8,
                priority: np.ndarray | None = None) -> list[int]:
    """Indices to keep: lowest `priority` first (full-image passes before tiles), then highest
    score; drop boxes overlapping a kept one (IoU ≥ iou) or mostly contained in / containing it
    (≥ containment). Tiles therefore only ADD faces the full-image pass missed: measured on a
    real photo, a native-resolution tile detection of a large face out-scored the full-image one
    but had worse landmarks (identity score 0.636 → 0.283)."""
    if len(boxes) == 0:
        return []
    prio = np.zeros(len(boxes)) if priority is None else np.asarray(priority, dtype=float)
    order = np.lexsort((-boxes[:, 4], prio))
    keep: list[int] = []
    for i in order:
        if keep:
            kept = boxes[keep]
            box = boxes[i:i + 1]
            if (iou_matrix(box, kept) >= iou).any() or (_containment(box, kept) >= containment).any():
                continue
        keep.append(int(i))
    return keep


def tile_grid(width: int, height: int, tile: int, overlap: float) -> list[tuple[int, int, int, int]]:
    """Overlapping tiles (x1, y1, x2, y2) covering the image; edge tiles are shifted inward so
    every tile is full size when the image allows it."""
    def starts(length: int) -> list[int]:
        if length <= tile:
            return [0]
        step = max(1, int(tile * (1 - overlap)))
        n = math.ceil((length - tile) / step) + 1
        return sorted({min(i * step, length - tile) for i in range(n)})

    return [(x, y, min(x + tile, width), min(y + tile, height)) for y in starts(height) for x in starts(width)]


def rotate_image(img: np.ndarray, degrees: int) -> np.ndarray:
    if degrees == 90:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if degrees == 270:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    if degrees == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    return img


def unrotate_points(pts: np.ndarray, degrees: int, orig_w: int, orig_h: int) -> np.ndarray:
    """Map (…, 2) points from the image rotated clockwise by `degrees` back to the original."""
    x, y = pts[..., 0], pts[..., 1]
    if degrees == 90:  # original (x, y) → rotated (H-1-y, x)
        out = np.stack([y, orig_h - 1 - x], axis=-1)
    elif degrees == 270:  # original (x, y) → rotated (y, W-1-x)
        out = np.stack([orig_w - 1 - y, x], axis=-1)
    elif degrees == 180:
        out = np.stack([orig_w - 1 - x, orig_h - 1 - y], axis=-1)
    else:
        out = pts.copy()
    return out.astype(np.float32)


def unrotate_boxes(boxes: np.ndarray, degrees: int, orig_w: int, orig_h: int) -> np.ndarray:
    if degrees == 0 or len(boxes) == 0:
        return boxes
    corners = np.stack([boxes[:, [0, 1]], boxes[:, [2, 1]], boxes[:, [0, 3]], boxes[:, [2, 3]]], axis=1)
    back = unrotate_points(corners, degrees, orig_w, orig_h)
    out = boxes.copy()
    out[:, 0], out[:, 1] = back[..., 0].min(1), back[..., 1].min(1)
    out[:, 2], out[:, 3] = back[..., 0].max(1), back[..., 1].max(1)
    return out


# ── Pipeline ──────────────────────────────────────────────────────────────


def choose_rotation(detect: DetectFn, img: np.ndarray, cfg: ClassroomDetectConfig,
                    rotate: Callable[[int], np.ndarray] | None = None) -> int:
    """0 unless a sideways orientation clearly yields better faces.

    Measured on real photos: for upright group photos the sideways passes find far fewer faces
    (0–1 vs 5–6) at lower scores; for a sideways selfie they find the same faces with a clearly
    higher mean score (0.84 vs 0.735). Rotate when the sideways pass has ≥ orient_gain × the
    upright score sum, or at least as many faces with a mean score ≥ orient_margin higher.
    `rotate(degrees)` supplies the rotated image (detect_classroom passes a cached one).
    """
    rotate = rotate or (lambda degrees: rotate_image(img, degrees))
    size = [(cfg.orient_size, cfg.orient_size)]
    boxes, _ = detect(img, size)
    upright = boxes[:, 4].astype(float) if len(boxes) else np.zeros(0)
    if len(upright) and upright.mean() >= cfg.orient_skip_mean:
        return 0  # clearly upright faces (measured 0.85–0.87 on upright photos): skip the sideways passes
    found = {0: upright}
    for degrees in (90, 270):
        boxes, _ = detect(rotate(degrees), size)
        found[degrees] = boxes[:, 4].astype(float) if len(boxes) else np.zeros(0)
    best, best_key = 0, None
    for degrees in (90, 270):
        s = found[degrees]
        if not len(s):
            continue
        clearly_more = s.sum() >= cfg.orient_gain * max(upright.sum(), 1e-6)
        same_faces_better = len(upright) > 0 and len(s) >= len(upright) and s.mean() >= upright.mean() + cfg.orient_margin
        if clearly_more or same_faces_better:
            key = (len(s), s.mean())
            if best_key is None or key > best_key:
                best, best_key = degrees, key
    return best


def _cut_by_tile(boxes: np.ndarray, tile: tuple[int, int, int, int], width: int, height: int, margin: int) -> np.ndarray:
    """True for boxes (tile coordinates) touching a tile edge that is not an image edge."""
    x1, y1, x2, y2 = tile
    tw, th = x2 - x1, y2 - y1
    cut = np.zeros(len(boxes), dtype=bool)
    if x1 > 0:
        cut |= boxes[:, 0] <= margin
    if y1 > 0:
        cut |= boxes[:, 1] <= margin
    if x2 < width:
        cut |= boxes[:, 2] >= tw - margin
    if y2 < height:
        cut |= boxes[:, 3] >= th - margin
    return cut


def detect_classroom(detect: DetectFn, image: np.ndarray, cfg: ClassroomDetectConfig) -> ClassroomDetection:
    started = time.perf_counter()
    orig_h, orig_w = image.shape[:2]
    # One array per orientation: the full-image pass then sees the very same array the orientation
    # check used, so a detector that memoises identical work (InsightFaceEngine) can reuse it.
    rotated: dict[int, np.ndarray] = {0: image}

    def rotate(degrees: int) -> np.ndarray:
        if degrees not in rotated:
            rotated[degrees] = rotate_image(image, degrees)
        return rotated[degrees]

    rotation = choose_rotation(detect, image, cfg, rotate) if cfg.auto_orient else 0
    oriented = time.perf_counter()
    img = rotate(rotation)
    h, w = img.shape[:2]
    passes = [f"rotate {rotation}°"] if rotation else []

    all_boxes, all_kps, all_prio = [], [], []
    boxes, kps = detect(img, list(cfg.sizes))
    full_done = time.perf_counter()
    passes.append("full " + "/".join(str(s[0]) for s in cfg.sizes))
    all_boxes.append(boxes)
    all_kps.append(kps if kps is not None else np.zeros((len(boxes), 5, 2), np.float32))
    all_prio.append(np.zeros(len(boxes)))

    tiles = 0
    if cfg.tiling and max(h, w) > cfg.tile_size * cfg.tile_min_ratio:
        grid = tile_grid(w, h, cfg.tile_size, cfg.tile_overlap)
        tiles = len(grid)
        passes.append(f"{tiles} tiles of {cfg.tile_size}")
        for x1, y1, x2, y2 in grid:
            tb, tk = detect(img[y1:y2, x1:x2], [(cfg.tile_size, cfg.tile_size)])
            if len(tb) == 0:
                continue
            keep = ~_cut_by_tile(tb, (x1, y1, x2, y2), w, h, cfg.edge_margin)
            tb = tb[keep].copy()
            tb[:, [0, 2]] += x1
            tb[:, [1, 3]] += y1
            if tk is not None:
                tk = tk[keep].copy()
                tk[..., 0] += x1
                tk[..., 1] += y1
            else:
                tk = np.zeros((len(tb), 5, 2), np.float32)
            all_boxes.append(tb)
            all_kps.append(tk)
            all_prio.append(np.ones(len(tb)))
    tiles_done = time.perf_counter()

    boxes = np.concatenate(all_boxes, axis=0) if all_boxes else np.zeros((0, 5), np.float32)
    kps = np.concatenate(all_kps, axis=0) if all_kps else np.zeros((0, 5, 2), np.float32)
    raw = len(boxes)
    keep = merge_boxes(boxes, cfg.nms_iou, cfg.containment, np.concatenate(all_prio))
    boxes, kps = boxes[keep], kps[keep]
    if rotation:
        boxes = unrotate_boxes(boxes, rotation, orig_w, orig_h)
        kps = unrotate_points(kps, rotation, orig_w, orig_h)
    boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, orig_w)
    boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, orig_h)
    stage_ms = {"orient": (oriented - started) * 1000, "full": (full_done - oriented) * 1000,
                "tiles": (tiles_done - full_done) * 1000}
    return ClassroomDetection(boxes=boxes, kps=kps, rotation=rotation, tiles=tiles, raw_detections=raw,
                              detection_ms=(time.perf_counter() - started) * 1000, passes=passes,
                              stage_ms={k: round(v, 1) for k, v in stage_ms.items()})
