"""Headless smoke: apply record_dataset.draw_overlay and verify the HUD pixels
are genuinely present on the frame (title, status chip, saved/fps text contrast).

No window, no camera saving. Optional `--camera N` adds a real-webcam pass.
"""

import sys
from pathlib import Path

CWD = Path(__file__).resolve().parents[1]  # repo root (skips dataset/)
for path in (str(CWD / "backend"), str(CWD / "dataset"), str(CWD / "dataset" / "scripts")):
    sys.path.insert(0, path)

import numpy as np

import record_dataset as rec  # top-level module (mirrors `python ...record_dataset.py`)
from camera.capture import MockCamera
from dataset_tool import DatasetConfig

FAILS = []


def check(name, cond):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILS.append(name)


def verify(frame_clean, *, recording):
    frame = frame_clean.copy()
    rec.draw_overlay(
        frame,
        fps=29.5,
        recording=recording,
        saved=12,
        elapsed=3.2 if recording else 0.0,
        interval=1.0,
        mock=False,
    )

    assert frame.dtype == np.uint8, "overlay corrupted dtype"
    check(f"frame changed", int(frame.sum()) != int(frame_clean.sum()))

    h, w = frame.shape[:2]
    band_h = max(134, int(h * 0.22))

    # Translucent band must dim the top strip. A near-black scene has nothing
    # left to dim, so only enforce it when the feed is visibly bright.
    clean_band = frame_clean[2 : band_h - 2, 2 : w - 2].mean()
    band = frame[2 : band_h - 2, 2 : w - 2].mean()
    if clean_band >= 60:
        check(f"translucent band dims the feed ({band:.0f} < {clean_band:.0f})", band < clean_band * 0.85)
    else:
        check("translucent band (feed too dark to measure dimming)", True)

    band_max = int(frame[:band_h].max())
    check("bright text present on band", band_max > 180)

    # Red status text/dot vs amber paused: look for strongly reddish pixels
    # inside the band (r-b > 150). Red border pixels are outside the ROI.
    region = frame[44 : band_h - 2, 4 : w - 4]
    r, b = region[..., 2].astype(int), region[..., 0].astype(int)
    redness = float((r - b > 150).mean())
    if recording:
        check(f"recording status is clearly red (redness={redness})", redness > 0.001)
    else:
        check(f"paused status is not red (redness={redness})", redness < 0.0005)

    if recording:
        border = frame[2:6, 2 : w - 2]
        check("recording red border on frame edge",
              border[..., 2].mean() > 120 and border[..., 0].mean() < 120)
    return frame


def main():
    print("== overlay on synthetic mock frames ==")
    cam = MockCamera(DatasetConfig(output_dir=Path("."), mock=True).to_camera_settings())
    for recording in (False, True):
        verify(cam.read(), recording=recording)

    if "--camera" in sys.argv:
        index = int(sys.argv[sys.argv.index("--camera") + 1])
        print(f"== overlay on real webcam {index} ==")
        from camera.capture import OpenCVCamera

        real = OpenCVCamera(DatasetConfig(camera_index=index).to_camera_settings())
        if not real.open():
            print("  [FAIL] could not open webcam — cannot smoke-test")
            FAILS.append("webcam open")
            return 1
        frame = real.read()
        real.release()
        if frame is None:
            print("  [FAIL] webcam returned no frame")
            FAILS.append("webcam frame")
            return 1
        verify(frame, recording=True)

    print("== done ==")
    if FAILS:
        print(f"FAILURES: {FAILS}")
        return 1
    print("all overlay checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())