"""Frame sampling + a contact sheet, so a human can check coverage first.

    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\sample_frames.py
    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\sample_frames.py --budget 32

Section 10/11: do not annotate every frame blind. Sample representative frames
per session (beginning / middle / end, plus an even spread), and oversample the
frames around the interaction moments that matter for later action recognition.

Sampling picks *what to look at*. It never creates a label: sampled frames are
unreviewed until a human says otherwise, and ``experiment_tool.label_rows``
ignores them until then.
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
    SAMPLING_DIR,
    build_index,
    build_selection,
    discover_sessions,
    ensure_layout,
    save_index,
)

#: Contact sheet layout.
SHEET_COLS = 5
SHEET_CELL_W = 320
SHEET_CELL_H = 200
SHEET_BANNER = 34

#: Motion percentile above which a frame counts as an "interaction" frame.
INTERACTION_PERCENTILE = 88.0


def frame_motion(paths: list[Path]) -> np.ndarray:
    """Mean absolute frame difference per frame (index 0 has no predecessor)."""
    out = np.zeros(len(paths), dtype=np.float32)
    prev = None
    for i, p in enumerate(paths):
        img = cv2.imread(str(p))
        if img is None:
            continue
        gray = cv2.cvtColor(cv2.resize(img, (320, 180)), cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        if prev is not None:
            out[i] = float(np.abs(gray.astype(np.int16) - prev.astype(np.int16)).mean())
        prev = gray
    return out


def pick_interaction_frames(
    session: dict, motion: np.ndarray, extra: int = 4
) -> list[int]:
    """Highest-motion frames in a session: reaching, carrying, releasing."""
    ids = [int(f["frame_id"]) for f in session.get("frames", [])]
    if not ids or motion.size == 0 or extra <= 0:
        return []
    threshold = float(np.percentile(motion, INTERACTION_PERCENTILE))
    hot = [
        ids[i]
        for i in range(min(len(ids), motion.size))
        if motion[i] >= threshold and motion[i] > 0
    ]
    if not hot:
        return []
    step = max(1, len(hot) // extra)
    return sorted(set(hot[::step][:extra]))


def contact_sheet(
    frames: list[tuple[Path, int, str]], out_path: Path, title: str
) -> Path | None:
    """Grid of sampled frames with their ids drawn on, so coverage is checkable
    by eye before annotating anything."""
    if not frames:
        return None
    rows = (len(frames) + SHEET_COLS - 1) // SHEET_COLS
    sheet = np.full(
        (SHEET_BANNER + rows * SHEET_CELL_H, SHEET_COLS * SHEET_CELL_W, 3),
        24,
        dtype=np.uint8,
    )
    cv2.putText(
        sheet,
        title[:110],
        (8, 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (235, 235, 235),
        1,
        cv2.LINE_AA,
    )
    for idx, (path, frame_id, activity) in enumerate(frames):
        img = cv2.imread(str(path))
        if img is None:
            continue
        r, c = divmod(idx, SHEET_COLS)
        y0 = SHEET_BANNER + r * SHEET_CELL_H
        x0 = c * SHEET_CELL_W
        tile = cv2.resize(img, (SHEET_CELL_W - 4, SHEET_CELL_H - 26))
        sheet[y0 + 24 : y0 + 24 + tile.shape[0], x0 + 2 : x0 + 2 + tile.shape[1]] = tile
        tag = f"#{frame_id}" + (f" {activity[:9]}" if activity else "")
        cv2.putText(
            sheet, tag, (x0 + 6, y0 + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (120, 230, 255), 1, cv2.LINE_AA
        )
        cv2.rectangle(sheet, (x0 + 1, y0 + 24), (x0 + SHEET_CELL_W - 3, y0 + SHEET_CELL_H - 2), (70, 70, 70), 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--budget", type=int, default=24, help="sampled frames per session")
    ap.add_argument("--interaction", type=int, default=4, help="extra high-motion frames")
    ap.add_argument("--no-sheet", action="store_true")
    args = ap.parse_args(argv)

    ensure_layout()
    index = build_index()
    save_index(index)
    print(f"indexed {index['totals']['sessions']} sessions / {index['totals']['frames']} frames\n")

    SAMPLING_DIR.mkdir(parents=True, exist_ok=True)
    grand = 0
    for session in discover_sessions():
        as_dict = session.to_dict()
        paths = [REPO_ROOT / f["source"] for f in as_dict["frames"]]
        motion = frame_motion(paths)
        hot = pick_interaction_frames(as_dict, motion, args.interaction)
        base = build_selection({"sessions": [as_dict]}, budget=args.budget)
        ids = sorted(set(base["sessions"][session.session_id]["frame_ids"]) | set(hot))
        activity = session.activity or ""
        (SAMPLING_DIR / f"{session.session_id}.json").write_text(
            json.dumps(
                {
                    "schema": "astra-experiment-sampling/1",
                    "session_id": session.session_id,
                    "activity": session.activity,
                    "label": session.label,
                    "n_frames": session.n_frames,
                    "frame_ids": ids,
                    "interaction_frame_ids": hot,
                    "motion": {
                        "mean": round(float(motion.mean()), 3),
                        "max": round(float(motion.max()), 3),
                        "p90": round(float(np.percentile(motion, 90)), 3),
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if not args.no_sheet:
            by_id = {int(f["frame_id"]): f["source"] for f in as_dict["frames"]}
            contact_sheet(
                [(REPO_ROOT / by_id[i], i, activity) for i in ids if i in by_id],
                REPO_ROOT / "dataset" / "experiment_detection" / "sampling" / f"{session.session_id}.jpg",
                f"{session.session_id}  activity={activity or '-'}  "
                f"{len(ids)}/{session.n_frames} sampled",
            )
        grand += len(ids)
        extra = f" (+{len(hot)} interaction)" if hot else ""
        print(f"{session.session_id:<34} {activity or '-':<14} {len(ids):>3}/{session.n_frames:<4} sampled{extra}")

    full = build_selection(index, budget=args.budget)
    print(f"\ntotal sampled frames: {grand}")
    print(f"index written: dataset/experiment_detection/index.json")
    print(f"selection: {full['totals']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
