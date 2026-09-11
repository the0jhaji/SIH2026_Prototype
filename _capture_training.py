"""Capture training data from the live camera for custom YOLO model.

Grabs frames via HTTP snapshot endpoint, auto-labels red_box/yellow_box
using HSV color detection, saves in YOLO format for training.
"""
import cv2
import numpy as np
import urllib.request
import time
import os
from pathlib import Path

SNAPSHOT_URL = "http://127.0.0.1:8000/api/camera/snapshot"
CAPTURE_DIR = Path("dataset/experiment_train")
NUM_FRAMES = 200
SAVE_EVERY = 2

# HSV ranges for auto-labeling
RED_MASKS = [
    (np.array([0, 100, 60], dtype=np.uint8), np.array([10, 255, 255], dtype=np.uint8)),
    (np.array([170, 100, 60], dtype=np.uint8), np.array([180, 255, 255], dtype=np.uint8)),
]
YELLOW_MASK = (np.array([15, 100, 60], dtype=np.uint8), np.array([35, 255, 255], dtype=np.uint8))
KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
MIN_BOX_AREA = 800


def find_colored_boxes(hsv, width, height):
    """Find red and yellow box candidates via HSV color."""
    boxes = []
    area = width * height

    red_mask = sum(cv2.inRange(hsv, lo, hi) for lo, hi in RED_MASKS)
    red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, KERNEL)
    for cnt in cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        if cv2.contourArea(cnt) < MIN_BOX_AREA:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 20 or h < 20:
            continue
        boxes.append(("red_box", x, y, x + w, y + h))

    yellow_mask = cv2.inRange(hsv, *YELLOW_MASK)
    yellow_mask = cv2.morphologyEx(yellow_mask, cv2.MORPH_CLOSE, KERNEL)
    for cnt in cv2.findContours(yellow_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        if cv2.contourArea(cnt) < MIN_BOX_AREA:
            continue
        x, y, w, h = cv2.boundingRect(cnt)
        if w < 20 or h < 20:
            continue
        boxes.append(("yellow_box", x, y, x + w, y + h))

    return boxes


def save_yolo_label(label_path, boxes, width, height):
    """Save YOLO format: class_id cx cy w h (normalized)."""
    class_map = {"red_box": 0, "yellow_box": 1}
    lines = []
    for cls, x1, y1, x2, y2 in boxes:
        if cls not in class_map:
            continue
        cx = ((x1 + x2) / 2) / width
        cy = ((y1 + y2) / 2) / height
        w = (x2 - x1) / width
        h = (y2 - y1) / height
        cx = max(0, min(1, cx))
        cy = max(0, min(1, cy))
        w = max(0, min(1, w))
        h = max(0, min(1, h))
        lines.append(f"{class_map[cls]} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    label_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    print("=== EXPERIMENT TRAINING DATA CAPTURE ===")
    print(f"Target: {NUM_FRAMES} frames, saving every {SAVE_EVERY}th")

    train_dir = CAPTURE_DIR / "train" / "images"
    train_labels = CAPTURE_DIR / "train" / "labels"
    val_dir = CAPTURE_DIR / "val" / "images"
    val_labels = CAPTURE_DIR / "val" / "labels"
    for d in [train_dir, train_labels, val_dir, val_labels]:
        d.mkdir(parents=True, exist_ok=True)

    captured = 0
    total_boxes = 0
    start = time.time()

    for i in range(NUM_FRAMES * 3):  # over-iterate since some frames lack boxes
        if captured >= NUM_FRAMES:
            break
        try:
            with urllib.request.urlopen(SNAPSHOT_URL, timeout=3) as resp:
                if resp.status != 200:
                    time.sleep(0.2)
                    continue
                frame_bytes = resp.read()
        except Exception:
            time.sleep(0.2)
            continue
        arr = np.frombuffer(frame_bytes, dtype=np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            continue

        if i % SAVE_EVERY != 0:
            continue

        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        boxes = find_colored_boxes(hsv, w, h)

        if not boxes:
            continue

        idx = captured
        is_val = (captured % 10 == 0)  # 10% validation
        prefix = "val" if is_val else "train"
        img_path = (CAPTURE_DIR / prefix / "images" / f"frame_{idx:05d}.jpg")
        lbl_path = (CAPTURE_DIR / prefix / "labels" / f"frame_{idx:05d}.txt")

        cv2.imwrite(str(img_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
        save_yolo_label(lbl_path, boxes, w, h)

        captured += 1
        total_boxes += len(boxes)

        if captured % 25 == 0:
            elapsed = time.time() - start
            print(f"  captured {captured}/{NUM_FRAMES} frames, {total_boxes} boxes, {elapsed:.1f}s")

        time.sleep(0.15)

    elapsed = time.time() - start
    print(f"\nDone: {captured} frames, {total_boxes} boxes in {elapsed:.1f}s")
    print(f"  Train: {len(list((CAPTURE_DIR / 'train' / 'images').glob('*.jpg')))} images")
    print(f"  Val:   {len(list((CAPTURE_DIR / 'val' / 'images').glob('*.jpg')))} images")

    # Write data.yaml
    data_yaml = f"""# Custom experiment model - auto-labeled from live camera
path: {CAPTURE_DIR.resolve()}
train: train/images
val: val/images
nc: 2
names:
  0: red_box
  1: yellow_box
"""
    (CAPTURE_DIR / "data.yaml").write_text(data_yaml, encoding="utf-8")
    print(f"  data.yaml written")


if __name__ == "__main__":
    main()
