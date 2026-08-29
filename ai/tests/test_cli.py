"""End-to-end CLI test: headless mock run prints structured JSON lines."""

import json
import subprocess
import sys
from pathlib import Path

AI_ROOT = Path(__file__).resolve().parent.parent


def test_cli_mock_headless_prints_detections() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipeline.cli",
            "--detector",
            "mock",
            "--source",
            "null",
            "--max-frames",
            "2",
            "--headless",
            "--no-annotate",
            "--print-detections",
        ],
        cwd=AI_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["frame"] == 0
    assert "timestamp" in first
    classes = {d["class_name"] for d in first["detections"]}
    assert classes == {"person", "experiment_box", "red_box", "yellow_box", "target_area"}
    for d in first["detections"]:
        assert set(d) == {"class_name", "confidence", "bounding_box", "timestamp"}
        assert len(d["bounding_box"]) == 4


def test_cli_yolo_without_weights_fails_helpfully() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipeline.cli",
            "--detector",
            "yolo",
            "--source",
            "null",
            "--max-frames",
            "1",
            "--headless",
        ],
        cwd=AI_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 2
    assert "models/yolo" in proc.stdout or "models/yolo" in proc.stderr