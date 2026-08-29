"""BAS dataset recorder (Phase 4A).

Opens the **same camera configuration** the production backend uses
(``backend/camera/capture.py``), shows a live preview with an FPS readout and
on-screen instructions, and saves JPEG frames into a unique session at a
configurable interval. Nothing leaves the machine.

Usage (from the repo root, with the backend venv):

    .\\venv\\Scripts\\python.exe dataset\\scripts\\record_dataset.py --label PICK_RED_BOX
    .\\venv\\Scripts\\python.exe dataset\\scripts\\record_dataset.py --width 1280 --height 720 --fps 30 --interval 1.0
    .\\venv\\Scripts\\python.exe dataset\\scripts\\record_dataset.py --mock   # synthetic feed, no webcam

Keys inside the preview window:
    SPACE   start / stop recording
    Q / ESC quit (closes the session cleanly and writes metadata)
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = DATASET_DIR.parent / "backend"
for _path in (str(DATASET_DIR), str(BACKEND_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from dataset_tool import (  # noqa: E402
    DatasetConfig,
    add_manifest_row,
    create_session,
    frame_filename,
    write_metadata,
)

KEY_SPACE = 32
KEY_ESC = 27
WINDOW = "BAS Dataset Recorder"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="record_dataset",
        description="Local BAS dataset recorder: live preview + interval frame capture.",
    )
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="seconds between saved frames while recording",
    )
    parser.add_argument(
        "--label",
        type=str,
        default="misc",
        help="activity/object label; slugified into the session path",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DATASET_DIR,
        help="dataset root (sessions land under raw/<label>/)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="use the synthetic mock camera (no webcam needed)",
    )
    return parser.parse_args(argv)


def draw_overlay(
    frame,
    *,
    fps: float,
    recording: bool,
    saved: int,
    elapsed: float,
    interval: float,
    mock: bool,
) -> None:
    """Paint the status strip + control hints onto the preview frame (mutates)."""
    import cv2

    h, w = frame.shape[:2]
    cv2.rectangle(frame, (8, 8), (w - 8, 92), (8, 10, 16), -1)
    cv2.rectangle(frame, (8, 8), (w - 8, 92), (45, 48, 60), 1)

    mode_color = (80, 235, 255) if recording else (140, 170, 200)
    state = f"REC {elapsed:05.1f}s" if recording else "READY"
    cv2.putText(
        frame,
        f"● {state}   FPS {fps:4.1f}   SAVED {saved}   EVERY {interval:g}s"
        + ("   [MOCK]" if mock else ""),
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        mode_color,
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        "[SPACE] start / stop recording   [Q] / [ESC] quit",
        (20, 72),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (190, 195, 205),
        1,
        cv2.LINE_AA,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    import cv2
    from camera.capture import MockCamera, OpenCVCamera

    config = DatasetConfig(
        camera_index=args.camera_index,
        width=args.width,
        height=args.height,
        fps=args.fps,
        interval=args.interval,
        label=args.label,
        mock=args.mock,
        output_dir=args.output,
    )
    session = create_session(config)
    reader = MockCamera(config.to_camera_settings()) if config.mock else OpenCVCamera(config.to_camera_settings())

    print("BAS dataset recorder")
    print(f"  session : {session.root}")
    print(
        f"  camera  : index={config.camera_index} {config.width}x{config.height} @ {config.fps}fps"
        + (" (mock)" if config.mock else "")
    )
    print(f"  save    : one JPEG every {config.interval:g}s")
    print("  keys    : SPACE start/stop recording · Q/ESC quit")

    if not reader.open():
        print(
            f"ERROR: could not open camera device {config.camera_index}. "
            "Check it is plugged in and not claimed by another app.",
            file=sys.stderr,
        )
        return 1

    recording = False
    recording_since = 0.0
    last_save = 0.0
    saved = 0
    started_at = time.monotonic()
    loop_count = 0

    try:
        while True:
            frame = reader.read()
            if frame is None:
                print("ERROR: camera feed interrupted; stopping.", file=sys.stderr)
                break
            now = time.monotonic()
            loop_count += 1
            fps = loop_count / max(now - started_at, 1e-6)

            if recording and (now - last_save) >= config.interval:
                index = saved + 1
                ok = cv2.imwrite(
                    str(session.root / frame_filename(index)),
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 95],
                )
                if ok:
                    ts_ms = int(now * 1000)
                    iso = datetime.now().astimezone().isoformat(timespec="seconds")
                    add_manifest_row(session, index, iso, ts_ms)
                    saved += 1
                    last_save = now
                else:
                    print(f"WARNING: failed to save frame {index}", file=sys.stderr)

            elapsed = now - recording_since if recording else 0.0
            draw_overlay(
                frame,
                fps=fps,
                recording=recording,
                saved=saved,
                elapsed=elapsed,
                interval=config.interval,
                mock=config.mock,
            )
            cv2.imshow(WINDOW, frame)

            key = cv2.waitKey(1) & 0xFF
            if key == KEY_SPACE:
                recording = not recording
                if recording:
                    recording_since = now
                    last_save = now
                    print(f"[rec] recording into {session.root}")
                else:
                    print(f"[rec] paused — {saved} frames saved so far")
            elif key in (KEY_ESC, ord("q"), ord("Q")):
                break
    finally:
        reader.release()
        cv2.destroyAllWindows()
        ended_iso = datetime.now().astimezone().isoformat(timespec="seconds")
        write_metadata(session, config, ended_at=ended_iso, frames_saved=saved)
        print(f"Session closed: {session.root} — {saved} frame(s) saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())