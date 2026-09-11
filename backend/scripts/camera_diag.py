r"""Hardware diagnostic for the after-fix camera pipeline.

NOT part of the pytest suite (tests stay hardware-free). Run manually with the
backend venv:

    cd backend
    .\.venv\Scripts\python.exe -m scripts.camera_diag

Probes (index x backend) and reports, per candidate:
    index, backend, isOpened(), first frame shape, frame dtype, successful
    reads, failed reads, the exact exception text, and the frame-validation
    verdict (see camera.capture.validate_frame). Every read is time-bounded so
    a hung driver cannot stall the tool. Output goes to the console and to
    data/debug/camera_diag.json.

Exit code 0 when at least one candidate produced a VALID frame, 1 otherwise
(this is a diagnostic — it never claims success without real pixels).
"""

from __future__ import annotations

import json
import sys
import threading
import time as _time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from app import config
from camera.capture import cv_backend, validate_frame

#: Backends in the same preference order the manager uses for ``auto``.
BACKENDS = ("msmf", "dshow", "any")
PER_CANDIDATE_DEADLINE_S = 6.0
MAX_READS = 8


def _probe(index: int, backend: str, deadline_s: float) -> dict:
    entry: dict = {
        "index": index,
        "backend": backend,
        "opened": False,
        "shape": None,
        "dtype": None,
        "reads_ok": 0,
        "reads_failed": 0,
        "valid": False,
        "reason": "",
        "last_error": None,
        "duration_s": 0.0,
    }
    sym = cv_backend(backend)
    if sym is None:
        entry["reason"] = f"no OpenCV backend constant for {backend!r}"
        return entry
    started = _time.monotonic()
    cap = cv2.VideoCapture(index, sym)
    if not cap.isOpened():
        cap.release()
        entry["reason"] = "isOpened() returned False"
        entry["duration_s"] = round(_time.monotonic() - started, 3)
        return entry
    entry["opened"] = True

    results: dict[str, object] = {}

    def worker() -> None:
        last_error: str | None = None
        while _time.monotonic() - started < deadline_s:
            try:
                ok, frame = cap.read()
            except cv2.error as exc:
                entry["reads_failed"] += 1
                last_error = f"{type(exc).__name__}: {exc}"
                break
            if not ok or frame is None:
                entry["reads_failed"] += 1
                last_error = "read() returned (False, None)"
                continue
            entry["reads_ok"] += 1
            if "shape" not in results and frame is not None:
                results["shape"] = list(frame.shape)
                results["dtype"] = str(frame.dtype)
            valid, reason = validate_frame(frame, reject_black=True)
            if valid:
                results["valid"] = True
                results["reason"] = "ok"
                return
            last_error = (
                f"read() returned a {reason} frame "
                f"(mean={float(frame.mean()):.3f}, std={float(frame.std()):.3f})"
            )
        results["reason"] = "no valid frame within budget"
        results["last_error"] = last_error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=deadline_s + 1.0)
    cap.release()

    alive = thread.is_alive()
    entry["shape"] = results.get("shape")
    entry["dtype"] = results.get("dtype")
    entry["valid"] = bool(results.get("valid"))
    entry["reason"] = str(results.get("reason") or "")
    entry["last_error"] = results.get("last_error")
    entry["duration_s"] = round(_time.monotonic() - started, 3)
    if alive:
        entry["last_error"] = "read() hung; probe abandoned after deadline"
    return entry


def main() -> int:
    indices = sorted({int(config.CAMERA_INDEX), 0, 1})
    versions = [cv2.__version__]
    report = {
        "tool": "scripts.camera_diag",
        "opencv_version": versions[0],
        "settings": {
            "camera_index": config.CAMERA_INDEX,
            "width": config.CAMERA_WIDTH,
            "height": config.CAMERA_HEIGHT,
            "fps": config.CAMERA_FPS,
            "backend": config.CAMERA_BACKEND,
            "reject_black": config.CAMERA_REJECT_BLACK,
        },
        "candidates": [],
    }
    for index in indices:
        for backend in BACKENDS:
            entry = _probe(index, backend, PER_CANDIDATE_DEADLINE_S)
            report["candidates"].append(entry)
            print(
                f"idx={entry['index']} backend={entry['backend']:<6} "
                f"opened={str(entry['opened']):<5} reads={entry['reads_ok']}ok/"
                f"{entry['reads_failed']}failed valid={str(entry['valid']):<5} "
                f"shape={entry['shape']} dtype={entry['dtype']} "
                f"reason={entry['reason']} err={entry['last_error']}"
            )

    any_valid = any(c["valid"] for c in report["candidates"])
    out_dir = config.DATA_DIR / "debug"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "camera_diag.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport written to {out_path}")
    print(f"Verdict: {'at least one backend serves valid pixels' if any_valid else 'NO usable camera feed'}")
    return 0 if any_valid else 1


if __name__ == "__main__":
    sys.exit(main())