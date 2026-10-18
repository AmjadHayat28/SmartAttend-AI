"""Group-photo detection pipeline (face_recognition/classroom.py) with a deterministic fake detector.

The fake "detector" finds bright squares (faces) in an image and, like a real detector, cannot
see a face smaller than MIN_PX after the image is shrunk into its input size. A square taller
than wide is an upright face (score 0.9); wider than tall is sideways (score 0.6).
"""

import cv2
import numpy as np
import pytest

from backend.app.face_recognition.classroom import (
    ClassroomDetectConfig,
    choose_rotation,
    detect_classroom,
    iou_matrix,
    merge_boxes,
    rotate_image,
    tile_grid,
    unrotate_boxes,
    unrotate_points,
)

MIN_PX = 12


def fake_detect(img, sizes):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    contours, _ = cv2.findContours((gray > 200).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = img.shape[:2]
    scale = max(min(s[0] / w, s[1] / h, 1.0) for s in sizes)  # best (largest) scale among the inputs
    boxes, kps = [], []
    for c in contours:
        x, y, bw, bh = cv2.boundingRect(c)
        if min(bw, bh) * scale < MIN_PX:
            continue
        score = 0.9 if bh >= bw else 0.6
        boxes.append([x, y, x + bw, y + bh, score])
        kps.append([[x + bw * 0.3, y + bh * 0.4], [x + bw * 0.7, y + bh * 0.4], [x + bw * 0.5, y + bh * 0.6],
                    [x + bw * 0.35, y + bh * 0.8], [x + bw * 0.65, y + bh * 0.8]])
    if not boxes:
        return np.zeros((0, 5), np.float32), np.zeros((0, 5, 2), np.float32)
    return np.array(boxes, np.float32), np.array(kps, np.float32)


def canvas(w, h, faces):
    img = np.zeros((h, w, 3), np.uint8)
    for x, y, fw, fh in faces:
        img[y:y + fh, x:x + fw] = 255
    return img


def matched(boxes, faces, tol=3):
    """Every expected face has exactly one box within `tol` px on each edge."""
    for x, y, fw, fh in faces:
        hits = [b for b in boxes if abs(b[0] - x) <= tol and abs(b[1] - y) <= tol
                and abs(b[2] - (x + fw)) <= tol and abs(b[3] - (y + fh)) <= tol]
        if len(hits) != 1:
            return False
    return True


NO_TILES = ClassroomDetectConfig(sizes=((640, 640),), tiling=False, auto_orient=False)
TILES = ClassroomDetectConfig(sizes=((640, 640),), tiling=True, tile_size=640, tile_overlap=0.25, auto_orient=False)


# ── Geometry ──────────────────────────────────────────────────────────────


def test_merge_keeps_the_best_of_overlapping_and_contained_boxes():
    boxes = np.array([
        [100, 100, 150, 160, 0.8],   # face A
        [102, 101, 151, 161, 0.9],   # face A again (other scale) → keep this one
        [110, 115, 140, 150, 0.7],   # partial box inside A (tile cut) → dropped
        [300, 100, 350, 160, 0.85],  # face B
    ], np.float32)
    keep = merge_boxes(boxes, iou=0.4, containment=0.8)
    assert sorted(keep) == [1, 3]


def test_full_image_detection_wins_over_a_higher_scoring_tile_detection():
    """Tiles only add faces the full-image pass missed; they never replace one it found."""
    boxes = np.array([[100, 100, 200, 220, 0.80],   # full-image pass
                      [101, 99, 201, 221, 0.95]],   # same face in a tile, higher score
                     np.float32)
    assert merge_boxes(boxes, priority=np.array([0, 1])) == [0]
    assert merge_boxes(boxes) == [1]  # without priorities: plain highest score


def test_iou_matrix_basics():
    a = np.array([[0, 0, 10, 10]], np.float32)
    b = np.array([[0, 0, 10, 10], [5, 0, 15, 10], [20, 20, 30, 30]], np.float32)
    assert np.allclose(iou_matrix(a, b), [[1.0, 50 / 150, 0.0]])


@pytest.mark.parametrize("w,h,tile", [(2560, 1440, 1024), (1500, 1000, 640), (500, 400, 640), (1024, 1024, 1024)])
def test_tile_grid_covers_the_image_with_overlap(w, h, tile):
    grid = tile_grid(w, h, tile, 0.25)
    covered = np.zeros((h, w), bool)
    for x1, y1, x2, y2 in grid:
        assert 0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h
        assert (x2 - x1) == min(tile, w) and (y2 - y1) == min(tile, h)  # full-size tiles
        covered[y1:y2, x1:x2] = True
    assert covered.all()


@pytest.mark.parametrize("degrees", [90, 180, 270])
def test_rotation_maps_points_back_exactly(degrees):
    w, h = 300, 200
    pts = np.array([[0, 0], [299, 0], [0, 199], [123, 45]], np.float32)
    img = np.zeros((h, w), np.uint8)
    for x, y in pts.astype(int):
        img[y, x] = 255
    rotated = rotate_image(img, degrees)
    ys, xs = np.nonzero(rotated)
    back = unrotate_points(np.stack([xs, ys], axis=-1).astype(np.float32), degrees, w, h)
    assert {tuple(p) for p in back.astype(int)} == {tuple(p) for p in pts.astype(int)}


# ── Pipeline ──────────────────────────────────────────────────────────────


def test_full_image_detection_finds_large_faces_once():
    faces = [(100, 100, 60, 80), (400, 120, 70, 90), (700, 90, 64, 84)]
    det = detect_classroom(fake_detect, canvas(1000, 600, faces), NO_TILES)
    assert len(det.boxes) == 3 and matched(det.boxes, faces)
    assert det.rotation == 0 and det.tiles == 0


def test_tiles_find_small_faces_the_full_pass_misses_and_map_back():
    # 2560-wide photo shrunk to 640 → scale 0.25: a 30 px face becomes 7.5 px (< 12) and is missed.
    small = [(300, 300, 30, 36), (1500, 900, 32, 38), (2400, 1300, 30, 36)]
    large = [(1000, 200, 120, 150)]
    img = canvas(2560, 1440, small + large)
    full_only = detect_classroom(fake_detect, img, NO_TILES)
    assert matched(full_only.boxes, large) and len(full_only.boxes) == 1
    tiled = detect_classroom(fake_detect, img, TILES)
    assert tiled.tiles > 1
    assert len(tiled.boxes) == 4 and matched(tiled.boxes, small + large)  # one box per face, original pixels
    assert tiled.merged_duplicates == tiled.raw_detections - 4 > 0  # the large face was seen in several passes


def test_face_cut_by_a_tile_edge_is_not_duplicated():
    # A small face straddling the boundary between the first two tiles (x = 480 for 640 tiles, 25% overlap).
    face = [(470, 600, 30, 36)]
    det = detect_classroom(fake_detect, canvas(2560, 1440, face), TILES)
    assert len(det.boxes) == 1 and matched(det.boxes, face)


def test_upright_photo_is_not_rotated():
    faces = [(100, 100, 60, 80), (400, 120, 70, 90)]
    assert choose_rotation(fake_detect, canvas(1000, 600, faces), ClassroomDetectConfig()) == 0


def test_sideways_photo_is_rotated_and_boxes_map_to_the_original_pixels():
    # Sideways faces (wider than tall) in a portrait image, as from a phone held on its side.
    faces = [(200, 300, 90, 70), (220, 700, 100, 76)]
    img = canvas(600, 1100, faces)
    cfg = ClassroomDetectConfig(sizes=((640, 640),), tiling=False, auto_orient=True)
    det = detect_classroom(fake_detect, img, cfg)
    assert det.rotation in (90, 270)
    assert len(det.boxes) == 2 and matched(det.boxes, faces)
    assert np.allclose(det.boxes[:, 4], 0.9)  # detected upright after rotation
    # Landmarks are inside their face box in ORIGINAL coordinates (used for alignment).
    for box, kps in zip(det.boxes, det.kps):
        assert (kps[:, 0] >= box[0] - 1).all() and (kps[:, 0] <= box[2] + 1).all()
        assert (kps[:, 1] >= box[1] - 1).all() and (kps[:, 1] <= box[3] + 1).all()


def test_unrotate_boxes_round_trip():
    boxes = np.array([[10, 20, 50, 80, 0.9]], np.float32)
    w, h = 200, 100
    img = np.zeros((h, w), np.uint8)
    img[20:80, 10:50] = 255
    for degrees in (90, 270):
        ys, xs = np.nonzero(rotate_image(img, degrees))
        rotated_box = np.array([[xs.min(), ys.min(), xs.max() + 1, ys.max() + 1, 0.9]], np.float32)
        back = unrotate_boxes(rotated_box, degrees, w, h)
        assert np.allclose(back[0, :4], boxes[0, :4], atol=1.5), degrees


def test_coordinates_stay_inside_the_image():
    faces = [(0, 0, 40, 50), (960, 550, 40, 50)]  # touching the corners
    det = detect_classroom(fake_detect, canvas(1000, 600, faces), NO_TILES)
    assert (det.boxes[:, 0] >= 0).all() and (det.boxes[:, 2] <= 1000).all()
    assert (det.boxes[:, 1] >= 0).all() and (det.boxes[:, 3] <= 600).all()
