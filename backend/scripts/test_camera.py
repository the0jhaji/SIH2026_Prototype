r"""Hardware diagnostic — open the configured camera, grab one frame, save it.

This is NOT part of the pytest suite (tests must stay hardware-free). Run it
manually with the backend venv:

    cd backend
    .\.venv\Scripts\python.exe -m scripts.test_camera

Uses the exact settings the application loads (app.config via
camera_settings_from_config) and the existing backend/camera implementation.

Exit code:
    0  camera opened, a frame was captured and saved to data/debug/camera_test.jpg
    1  camera could not be opened
    2  frame capture failed
    3  frame saved but written file is missing/empty
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2

from app import config
from app.main import camera_settings_from_config
from camera import OpenCVCamera


def main() -> int:
    settings = camera_settings_from_config()
    print(f"Config from {config.__name__}: CAMERA_INDEX={config.CAMERA_INDEX} "
          f"(env CAMERA_INDEX), CAMERA_WIDTH={config.CAMERA_WIDTH}, "
          f"CAMERA_HEIGHT={config.CAMERA_HEIGHT}, CAMERA_FPS={config.CAMERA_FPS}, "
          f"CAMERA_MOCK={config.CAMERA_MOCK}")
    print(f"Effective settings: camera_index={settings.camera_index}, "
          f"width={settings.width}, height={settings.height}, fps={settings.fps}, "
          f"mock={settings.mock}, jpeg_quality={settings.jpeg_quality}")
    if settings.mock:
        print("NOTE: CAMERA_MOCK is enabled, so the app streams the mock feed. "
              "This script tests the REAL camera device regardless.")

    camera = OpenCVCamera(settings)
    try:
        opened = camera.open()
        print(f"Open camera device {settings.camera_index}: "
              f"{'yes - camera opened successfully' if opened else 'no - could not open camera'}")
        if not opened:
            return 1

        frame = camera.read()
        captured = frame is not None
        print(f"Capture frame: {'yes - frame captured' if captured else 'no - no frame returned'}")
        if frame is None:
            return 2

        height, width = frame.shape[:2]
        print(f"Frame resolution: {width}x{height}")

        out_dir = config.DATA_DIR / "debug"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "camera_test.jpg"
        ok = cv2.imwrite(str(out_path), frame)
        if not ok or not out_path.exists() or out_path.stat().st_size == 0:
            print(f"Save frame to {out_path}: FAILED")
            return 3
        print(f"Save frame to {out_path}: ok ({out_path.stat().st_size} bytes)")
        return 0
    finally:
        camera.release()
        print("Camera released cleanly")


if __name__ == "__main__":
    sys.exit(main())