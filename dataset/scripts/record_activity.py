"""BAS activity dataset recorder (Phase 5B).

Shows a live preview with the same proven HUD style as ``record_dataset.py``,
tracks exactly one activity at a time, and saves JPEG frames at a fixed
interval into ``dataset/activity/<ACTIVITY>/session_<ts>_<rand>/``. The valid
activity names are loaded from ``experiment/experiment.json`` — the recorder
never hardcodes the vocabulary. Nothing leaves the machine.

Usage (from the repo root, with the backend venv):

    .\\venv\\Scripts\\python.exe dataset\\scripts\\record_activity.py --activity PICK_RED --interval 0.1
    .\\venv\\Scripts\\python.exe dataset\\scripts\\record_activity.py --activity APPROACH --mock   # synthetic feed, no webcam

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

from activity_tool import (  # noqa: E402
    ActivityConfig,
    ActivitySession,
    add_activity_manifest_row,
    activity_frame_filename,
    create_activity_session,
    load_activities,
    write_activity_metadata,
)
from record_dataset import KEY_ESC, KEY_SPACE, _shade, _text  # noqa: E402

WINDOW = "BAS Activity Dataset Recorder"
ACTIVITY_COLOR = (70, 200, 255)  # bright amber - make the activity unmissable


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="record_activity",
        description="Local BAS ACTIVITY dataset recorder: live preview + interval frame capture.",
    )
    parser.add_argument(
        "--activity",
        required=True,
        choices=load_activities(),
        help="activity to record (canonical vocabulary from experiment/experiment.json)",
    )
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="seconds between saved frames while recording",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DATASET_DIR,
        help="dataset root (sessions land under activity/<ACTIVITY>/)",
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
    activity: str,
    fps: float,
    recording: bool,
    saved: int,
    elapsed: float,
    interval: float,
    mock: bool,
) -> None:
    """Paint the activity HUD onto the preview frame (mutates)."""
    import math

    import cv2

    h, w = frame.shape[:2]
    scale = max(1.0, (w / 1280 + h / 720) / 2.0)
    margin = 10
    band_h = max(150, int(h * 0.24))

    _shade(frame, 0, 0, w, band_h, (9, 11, 17), alpha=0.66)
    cv2.rectangle(frame, (0, band_h - 2), (w - 1, band_h), (90, 100, 122), 2)

    # Row 1: title on the left, FPS + SAVED right-aligned.
    title = "BAS ACTIVITY DATASET RECORDER" + ("  [MOCK]" if mock else "")
    _text(frame, title, (margin, int(26 * scale)), 0.8 * scale, (240, 242, 248), 2)

    saved_txt = f"SAVED: {saved}"
    fps_txt = f"FPS: {fps:4.1f}"
    (saved_w, _), _ = cv2.getTextSize(saved_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, 2)
    (fps_w, _), _ = cv2.getTextSize(fps_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, 2)
    _text(frame, fps_txt, (0, int(30 * scale)), 0.6 * scale, (222, 226, 236), 2,
          align_right=w - margin - saved_w - 56)
    _text(frame, saved_txt, (0, int(30 * scale)), 0.6 * scale, (240, 242, 248), 2,
          align_right=w - margin)

    # Row 2: the activity name, big and bright.
    activity_txt = f"ACTIVITY: {activity}"
    _text(frame, activity_txt, (margin, int(60 * scale)), 0.95 * scale, ACTIVITY_COLOR, 2)

    # Row 3: control hints.
    _text(frame, "SPACE: START / STOP RECORDING", (margin, int(92 * scale)), 0.55 * scale,
          (198, 204, 216), 2)
    _text(frame, "Q / ESC: QUIT", (0, int(92 * scale)), 0.55 * scale, (198, 204, 216), 2,
          align_right=w - margin)

    # Row 4: obvious recording status (pulsing dot + colored text) and timing.
    row4_y = int(122 * scale)
    text_y = row4_y - 12
    if recording:
        pulse = 7 + int(abs(math.sin(time.monotonic() * 6.0)) * 4)
        cv2.circle(frame, (margin + 6, row4_y), pulse, (60, 60, 255), -1)
        cv2.circle(frame, (margin + 6, row4_y), pulse, (255, 255, 255), 2)
        status_txt, status_color = "STATUS: RECORDING", (70, 120, 255)
    else:
        cv2.circle(frame, (margin + 6, row4_y), 6, (110, 120, 140), -1)
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

    # Same bright red border around the whole frame while recording.
    if recording:
        cv2.rectangle(frame, (3, 3), (w - 4, h - 4), (40, 90, 255), 4)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    import cv2
    from camera.capture import MockCamera, OpenCVCamera

    config = ActivityConfig(
        activity=args.activity,
        camera_index=args.camera_index,
        width=args.width,
        height=args.height,
        fps=args.fps,
        interval=args.interval,
        mock=args.mock,
        output_dir=args.output,
    )
    session: ActivitySession = create_activity_session(config)
    reader = MockCamera(config.to_camera_settings()) if config.mock else OpenCVCamera(config.to_camera_settings())

    print("BAS activity dataset recorder")
    print(f"  activity: {config.activity}")
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
                filename = activity_frame_filename(index)
                ok = cv2.imwrite(
                    str(session.root / filename),
                    frame,
                    [cv2.IMWRITE_JPEG_QUALITY, 95],
                )
                if ok:
                    ts_ms = int(now * 1000)
                    iso = datetime.now().astimezone().isoformat(timespec="seconds")
                    add_activity_manifest_row(session, index, iso, ts_ms, filename)
                    saved += 1
                    last_save = now
                else:
                    print(f"WARNING: failed to save frame {index}", file=sys.stderr)

            elapsed = now - recording_since if recording else 0.0
            draw_overlay(
                frame,
                activity=config.activity,
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
                    print(f"[rec] recording {config.activity} into {session.root}")
                else:
                    print(f"[rec] paused — {saved} frames saved so far")
            elif key in (KEY_ESC, ord("q"), ord("Q")):
                break
    finally:
        reader.release()
        cv2.destroyAllWindows()
        ended_iso = datetime.now().astimezone().isoformat(timespec="seconds")
        write_activity_metadata(session, config, ended_at=ended_iso, frame_count=saved)
        print(f"Session closed: {session.root} — {saved} frame(s) saved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())