"""Generate PRE-LABEL PROPOSALS for human verification.

    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\prelabel.py --index
    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\prelabel.py --session session_20260829_235407_o3s3
    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\prelabel.py --sampled-only

A PROPOSAL IS NOT GROUND TRUTH. This writes only to
``dataset/experiment_detection/proposals/``; the confirmed-label tree
(``labels/``) and the annotation metadata are never touched here. The
annotator sees every proposal and must ACCEPT, EDIT, DELETE or RECLASSIFY it,
and the frame only becomes a training row once a human marks it reviewed.

Allowed generators (section 5), and nothing else:

- ``person``      from the existing COCO detector
- ``red_box``     from a saturated-red HSV heuristic
- ``yellow_box``  from a saturated-yellow HSV heuristic

``main_experiment_box``, ``red_target_area`` and ``yellow_target_area`` are
deliberately NOT generated (section 6): no reliable visual heuristic is known
for them, so a guess would be a fabricated box. They start out unannotated and
get drawn by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (str(REPO_ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

import experiment_tool as et  # noqa: E402
from experiment_tool import (  # noqa: E402
    PROPOSABLE,
    SAMPLING_DIR,
    build_index,
    discover_sessions,
    ensure_layout,
    iter_frames,
    load_vocabulary,
    save_index,
    save_proposals,
)

#: A colour heuristic is a *candidate* generator, so keep it permissive but not
#: absurd: tiny blobs are noise, and a box covering most of the frame is the
#: wall or a shirt, not a prop.
MIN_BLOB_AREA = 0.0015
MAX_BLOB_AREA = 0.35
BLOB_MERGE_IOU = 0.45

#: COCO 'person' proposals. The audit measured 99/98 frames, so it is the one
#: generator that is genuinely useful; it still needs confirming because a
#: chair or a reflection can be proposed as a person.
PERSON_CONF = 0.30

RED_LO, RED_HI = (0, 110, 70), (10, 255, 255)
RED_HI2 = (170, 110, 70), (180, 255, 255)
YEL_LO, YEL_HI = (18, 110, 70), (35, 255, 255)

KERNEL = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))


def _iou(a: list[int], b: list[int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    if not inter:
        return 0.0
    ua = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - inter
    return inter / ua if ua > 0 else 0.0


def _merge(boxes: list[list[int]]) -> list[list[int]]:
    """Union-merge overlapping blobs.

    The audit measured the raw heuristic centroid jumping 697px between frames,
    because a single object was split into several blobs (or several skin
    regions were found). Merging overlapping candidates makes each proposal one
    candidate object instead of a fragment, which is what a human can judge.
    """
    out: list[list[int]] = []
    for box in sorted(boxes, key=lambda b: -(b[2] - b[0]) * (b[3] - b[1])):
        for i, kept in enumerate(out):
            if _iou(box, kept) >= BLOB_MERGE_IOU:
                out[i] = [
                    min(box[0], kept[0]),
                    min(box[1], kept[1]),
                    max(box[2], kept[2]),
                    max(box[3], kept[3]),
                ]
                break
        else:
            out.append(list(box))
    return out


def _colour_candidates(hsv, lo, hi, frame_area: int) -> list[list[int]]:
    mask = cv2.inRange(hsv, lo, hi)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, KERNEL)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, KERNEL)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        if cv2.contourArea(c) < MIN_BLOB_AREA * frame_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if w <= 2 or h <= 2:
            continue
        if (w * h) > MAX_BLOB_AREA * frame_area:
            continue
        boxes.append([x, y, x + w, y + h])
    return _merge(boxes)


def _load_person_detector(model_path: str):
    from ai.detection.yolo_detector import YoloDetector

    det = YoloDetector(model_path=model_path, conf_threshold=PERSON_CONF)
    det.load()
    return det


def proposals_for_frame(frame_obj, person_det) -> list[dict]:
    """Candidate boxes for one frame. Empty is a valid, honest answer."""
    img = cv2.imread(str(REPO_ROOT / frame_obj.source))
    if img is None:
        return []
    height, width = img.shape[:2]
    area = width * height
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    out: list[dict] = []

    if person_det is not None:
        for d in person_det.detect(img):
            if d.class_name != "person":
                continue
            out.append(
                {
                    "class": "person",
                    "bbox": [d.x1, d.y1, d.x2 - d.x1, d.y2 - d.y1],
                    "generator": "coco_person",
                    "confidence": round(float(d.confidence), 3),
                }
            )

    for name, lo, hi, gen in (
        ("red_box", RED_LO, RED_HI, "hue_red"),
        ("red_box", RED_HI2[0], RED_HI2[1], "hue_red"),
        ("yellow_box", YEL_LO, YEL_HI, "hue_yellow"),
    ):
        for x1, y1, x2, y2 in _colour_candidates(hsv, lo, hi, area):
            out.append(
                {
                    "class": name,
                    "bbox": [x1, y1, x2 - x1, y2 - y1],
                    "generator": gen,
                    "confidence": 0.5,
                }
            )

    # Same class from two hue windows is one object, not two.
    final: list[dict] = []
    for cand in out:
        box = cand["bbox"]
        if any(c["class"] == cand["class"] and _iou(box, c["bbox"]) > 0.3 for c in final):
            continue
        final.append(cand)
    return final


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--index", action="store_true", help="(re)build index.json for all sessions")
    ap.add_argument("--session", action="append", default=None, help="limit to this session id")
    ap.add_argument("--sampled-only", action="store_true", help="only frames in sampling/*.json")
    ap.add_argument("--limit", type=int, default=0, help="max frames per session (0 = all)")
    ap.add_argument("--model", default="detection/yolov8n.onnx", help="COCO model for person")
    ap.add_argument("--no-person", action="store_true", help="colour heuristics only")
    args = ap.parse_args(argv)

    ensure_layout()
    vocab = load_vocabulary()
    bad = [c for c in PROPOSABLE if vocab.id_of(c) is None]
    if bad:
        print(f"vocabulary is missing proposal classes: {bad}", file=sys.stderr)
        return 2

    index = build_index()
    save_index(index)
    print(f"indexed {index['totals']['sessions']} sessions / {index['totals']['frames']} frames")

    wanted = set(args.session or [])
    sampled: set[tuple[str, int]] = set()
    if args.sampled_only:
        for p in SAMPLING_DIR.glob("*.json"):
            data = json.loads(p.read_text(encoding="utf-8"))
            session_id = data.get("session_id") or p.stem
            for fid in data.get("frame_ids", []):
                sampled.add((session_id, int(fid)))
        if not sampled:
            print("no sampling/*.json found; run sample_frames.py first", file=sys.stderr)
            return 2
        print(f"sampled frame filter: {len(sampled)} frames")

    person_det = None
    if not args.no_person:
        try:
            person_det = _load_person_detector(args.model)
            print(f"person proposals from {args.model}")
        except Exception as exc:  # a missing model must not invent boxes
            print(f"person proposals disabled ({exc}); colour heuristics only", file=sys.stderr)

    totals = {c: 0 for c in PROPOSABLE}
    frames_with = 0
    processed = 0
    per_session: dict[str, int] = {}
    for session, frame in iter_frames(index):
        if wanted and frame.session_id not in wanted:
            continue
        if sampled and (frame.session_id, frame.frame_id) not in sampled:
            continue
        done = per_session.get(frame.session_id, 0)
        if args.limit and done >= args.limit:
            continue
        per_session[frame.session_id] = done + 1
        props = proposals_for_frame(frame, person_det)
        if props:
            save_proposals(frame.session_id, frame.frame_id, props)
            frames_with += 1
            for p in props:
                totals[p["class"]] = totals.get(p["class"], 0) + 1
        processed += 1

    print(f"\nproposals written for {frames_with}/{processed} frames")
    for cls, n in sorted(totals.items()):
        print(f"  {cls:<16} {n} candidate boxes")
    print("  manual only: " + ", ".join(c for c in vocab.classes if c not in PROPOSABLE))
    print("\nThese are CANDIDATES, not labels. Open the annotator to accept/edit/delete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
