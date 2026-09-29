"""Draw the confirmed labels back onto the frames, so they can be checked by eye.

    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\visualize_annotations.py
    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\visualize_annotations.py --sheet session_20260830_004243_wr66

Writes a per-frame JPEG and one contact sheet per session under
``dataset/experiment_detection/qa/``. This is the last human gate before training:
a label file can be perfectly valid and still describe the wrong thing, so look
at the pictures. A class the model must learn but that is not visible in the
frame should simply not be annotated there.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (str(REPO_ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from experiment_tool import (  # noqa: E402
    QA_DIR,
    STAGING,
    build_index,
    build_selection,
    iter_frames,
    label_rows,
    load_metadata,
    load_vocabulary,
    save_index,
)

COLORS = [
    (255, 200, 90),
    (90, 180, 255),
    (60, 70, 245),
    (60, 220, 235),
    (140, 90, 240),
    (90, 150, 245),
]

SHEET_COLS = 4
CELL_W, CELL_H = 400, 250
BANNER = 34


def overlay(img: np.ndarray, entry: dict, vocab) -> np.ndarray:
    out = img.copy()
    h, w = out.shape[:2]
    for ann in entry.get("annotations", []):
        color = COLORS[ann["class_id"] % len(COLORS)]
        x, y, bw, bh = (int(v) for v in ann["bbox"])
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(w, x + bw), min(h, y + bh)
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)
        label = ann["class"]
        tw = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0]
        cv2.rectangle(out, (x1, max(0, y1 - 18)), (x1 + tw + 8, y1), color, -1)
        cv2.putText(out, label, (x1 + 4, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (20, 20, 20), 1, cv2.LINE_AA)
    return out


def sheet(tiles: list[tuple[np.ndarray, int, str]], out_path: Path, title: str) -> Path | None:
    if not tiles:
        return None
    rows = (len(tiles) + SHEET_COLS - 1) // SHEET_COLS
    canvas = np.full((BANNER + rows * CELL_H, SHEET_COLS * CELL_W, 3), 22, dtype=np.uint8)
    cv2.putText(canvas, title[:120], (8, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
    for i, (img, frame_id, note) in enumerate(tiles):
        r, c = divmod(i, SHEET_COLS)
        y0, x0 = BANNER + r * CELL_H, c * CELL_W
        tile = cv2.resize(img, (CELL_W - 4, CELL_H - 26))
        canvas[y0 + 24 : y0 + 24 + tile.shape[0], x0 + 2 : x0 + 2 + tile.shape[1]] = tile
        cv2.putText(canvas, f"#{frame_id} {note}"[:44], (x0 + 6, y0 + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 230, 255), 1, cv2.LINE_AA)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", action="append", default=None)
    ap.add_argument("--split", default=STAGING)
    ap.add_argument("--per-frame", action="store_true", help="also write one JPEG per frame")
    ap.add_argument("--no-sheet", action="store_true")
    args = ap.parse_args(argv)

    vocab = load_vocabulary()
    index = build_index()
    save_index(index)
    rows = label_rows(index, args.split)
    if not rows:
        print("no reviewed frames yet: nothing to draw. (That is expected before annotation.)")
        return 0

    wanted = set(args.session or [])
    by_session: dict[str, list[dict]] = {}
    for row in rows:
        if wanted and row["session_id"] not in wanted:
            continue
        by_session.setdefault(row["session_id"], []).append(row)

    QA_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    for session_id, session_rows in by_session.items():
        tiles = []
        for row in sorted(session_rows, key=lambda r: r["frame_id"]):
            img = cv2.imread(str(REPO_ROOT / row["source"]))
            if img is None:
                continue
            entry = load_metadata(session_id)["frames"][str(row["frame_id"])]
            drawn = overlay(img, entry, vocab)
            if args.per_frame:
                p = QA_DIR / session_id / f"frame_{row['frame_id']:06d}.jpg"
                p.parent.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(p), drawn, [cv2.IMWRITE_JPEG_QUALITY, 90])
            note = "empty/background" if row["empty"] else (row["activity"] or f"{row['n_boxes']} boxes")
            tiles.append((drawn, row["frame_id"], note))
            total += 1
        if not args.no_sheet:
            out = sheet(tiles, QA_DIR / f"{session_id}.jpg", f"{session_id} — {len(tiles)} reviewed frames")
            print(f"{(out or QA_DIR / session_id).as_posix()}")
    print(f"\n{total} reviewed frames drawn")
    print("Check these by eye: valid geometry is not the same as a correct label.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
