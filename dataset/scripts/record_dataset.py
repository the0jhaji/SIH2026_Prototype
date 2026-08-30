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
import math
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


def _shade(frame, x1: int, y1: int, x2: int, y2: int, color, alpha: float) -> None:
    """Filled, semi-transparent rectangle so text stays readable on any scene."""
    import cv2

    layer = frame.copy()
    cv2.rectangle(layer, (x1, y1), (x2, y2), color, -1)
    cv2.addWeighted(layer, alpha, frame, 1.0 - alpha, 0.0, dst=frame)


def _text(
    frame,
    text: str,
    org,
    scale: float,
    color,
    thickness: int = 1,
    *,
    align_right: int | None = None,
) -> None:
    """Crisp, opaque text on the frame; ``align_right`` right-aligns to x."""
    import cv2

    font = cv2.FONT_HERSHEY_SIMPLEX
    if align_right is not None:
        (tw, _th), _baseline = cv2.getTextSize(text, font, scale, thickness)
        org = (align_right - tw, org[1])
    cv2.putText(frame, text, org, font, scale, color, thickness, cv2.LINE_AA)


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
    """Paint a high-visibility status HUD onto the preview frame (mutates)."""
    import cv2
    import time

    h, w = frame.shape[:2]
    scale = max(1.0, (w / 1280 + h / 720) / 2.0)
    margin = 10
    band_h = max(134, int(h * 0.22))

    # Semi-transparent dark band + thin divider so the text stays readable
    # regardless of what the camera is pointed at.
    _shade(frame, 0, 0, w, band_h, (9, 11, 17), alpha=0.66)
    cv2.rectangle(frame, (0, band_h - 2), (w - 1, band_h), (90, 100, 122), 2)

    # Row 1: title on the left, FPS + SAVED right-aligned.
    title = "BAS DATASET RECORDER" + ("  [MOCK]" if mock else "")
    _text(frame, title, (margin, int(26 * scale)), 0.8 * scale, (240, 242, 248), 2)

    saved_txt = f"SAVED: {saved}"
    fps_txt = f"FPS: {fps:4.1f}"
    (saved_w, _), _ = cv2.getTextSize(saved_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, 2)
    (fps_w, _), _ = cv2.getTextSize(fps_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, 2)
    _text(frame, fps_txt, (0, int(30 * scale)), 0.6 * scale, (222, 226, 236), 2,
          align_right=w - margin - saved_w - 56)
    _text(frame, saved_txt, (0, int(30 * scale)), 0.6 * scale, (240, 242, 248), 2,
          align_right=w - margin)

    # Row 2: control hints.
    _text(frame, "SPACE: START / STOP RECORDING", (margin, int(54 * scale)), 0.55 * scale,
          (198, 204, 216), 2)
    _text(frame, "Q / ESC: QUIT", (0, int(54 * scale)), 0.55 * scale, (198, 204, 216), 2,
          align_right=w - margin)

    # Row 3: obvious recording status (pulsing dot + colored text) and timing.
    row3_y = int(82 * scale)
    text_y = row3_y - 12
    if recording:
        pulse = 7 + int(abs(math.sin(time.monotonic() * 6.0)) * 4)
        cv2.circle(frame, (margin + 6, row3_y), pulse, (60, 60, 255), -1)
        cv2.circle(frame, (margin + 6, row3_y), pulse, (255, 255, 255), 2)
        status_txt, status_color = "STATUS: RECORDING", (70, 120, 255)
    else:
        cv2.circle(frame, (margin + 6, row3_y), 6, (110, 120, 140), -1)
        status_txt, status_color = "STATUS: PAUSED", (120, 200, 255)
    _text(frame, status_txt, (margin + 20, text_y), 0.62 * scale, status_color, 2)

    interval_txt = f"INTERVAL: {interval:g}s"
    elapsed_txt = f"ELAPSED {elapsed:5.1f}s" if recording else "ELAPSED --"
    (int_w, _), _ = cv2.getTextSize(interval_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.55 * scale, 2)
    (el_w, _), _ = cv2.getTextSize(elapsed_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.55 * scale, 2)
    _text(frame, interval_txt, (0, text_y), 0.55 * scale, (198, 204, 216), 2,
          align_right=w - margin - el_w - 56)
    _text(frame, elapsed_txt, (0, text_y), 0.55 * scale, (198, 204, 216), 2,
          align_right=w - margin)

    # A bright red border around the whole frame while recording makes the
    # state obvious even from across the room.
    if recording:
        cv2.rectangle(frame, (3, 3), (w - 4, h - 4), (40, 90, 255), 4)


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