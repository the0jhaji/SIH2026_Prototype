"""Pure dataset-tool logic: configuration, session layout, metadata, manifest.

OpenCV lives only in ``record_dataset.py`` - this module stays unit-testable
without a camera, window, or device. All paths are resolved locally under the
dataset root; nothing is ever uploaded.

Named ``dataset_tool`` (not ``scripts.*``) to avoid colliding with the
``backend/scripts`` package used for backend diagnostics.
"""

from __future__ import annotations

import csv
import json
import random
import string
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent
REPO_ROOT = DATASET_DIR.parent
BACKEND_DIR = REPO_ROOT / "backend"

#: Dataset subdirectories kept in sync by :func:`ensure_layout`.
SUBDIRS = ("raw", "frames", "annotations")


def slugify(label: str) -> str:
    """Turn an arbitrary label into a safe directory name (``PICK RED`` -> ``pick_red``)."""
    cleaned = "".join(c if c.isalnum() else "_" for c in label.strip().lower())
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned or "misc"


@dataclass(frozen=True)
class DatasetConfig:
    """Recorder configuration. Defaults mirror the production backend camera
    (``backend/camera/capture.py:CameraSettings``)."""

    camera_index: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    interval: float = 1.0  # seconds between saved frames while recording
    label: str = "misc"
    mock: bool = False
    output_dir: Path = DATASET_DIR

    def __post_init__(self) -> None:
        if self.camera_index < 0:
            raise ValueError(f"camera_index must be >= 0, got {self.camera_index}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"invalid resolution {self.width}x{self.height}")
        if self.fps <= 0:
            raise ValueError(f"fps must be > 0, got {self.fps}")
        if self.interval <= 0:
            raise ValueError(f"interval must be > 0, got {self.interval}")
        if not slugify(self.label):
            raise ValueError(f"label must contain a usable character, got {self.label!r}")

    @property
    def session_label(self) -> str:
        return slugify(self.label)

    def to_camera_settings(self):
        """Build the shared camera settings object without importing cv2 here."""
        from camera.capture import CameraSettings

        return CameraSettings(
            camera_index=self.camera_index,
            width=self.width,
            height=self.height,
            fps=self.fps,
            mock=self.mock,
        )


@dataclass(frozen=True)
class Session:
    """A recording session: unique directory on disk plus metadata identity."""

    session_id: str
    root: Path  # <output_dir>/raw/<label>/session_<ts>_<rand>
    label: str
    created_at_iso: str


def ensure_layout(output_dir: Path) -> Path:
    """Create the dataset skeleton (``raw/``, ``frames/``, ``annotations/``)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in SUBDIRS:
        (output_dir / name).mkdir(parents=True, exist_ok=True)
    return output_dir


def create_session(config: DatasetConfig) -> Session:
    """Allocate a unique session directory (and initial metadata)."""
    ensure_layout(config.output_dir)
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    created_iso = now.isoformat(timespec="seconds")
    label_dir = config.output_dir / "raw" / config.session_label
    label_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(10):
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
        session_id = f"{stamp}_{suffix}"
        root = label_dir / f"session_{session_id}"
        try:
            root.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError("could not allocate a unique session directory")
    session = Session(
        session_id=session_id,
        root=root,
        label=config.session_label,
        created_at_iso=created_iso,
    )
    write_metadata(session, config)
    return session


def frame_filename(index: int) -> str:
    return f"frame_{index:06d}.jpg"


def write_metadata(
    session: Session,
    config: DatasetConfig,
    *,
    ended_at: str | None = None,
    frames_saved: int = 0,
) -> Path:
    """Write (or refresh) ``metadata.json`` describing the session."""
    payload = {
        "schema": "bas-dataset-session/1",
        "session_id": session.session_id,
        "label": session.label,
        "created_at": session.created_at_iso,
        "ended_at": ended_at,
        "camera": {
            "index": config.camera_index,
            "width": config.width,
            "height": config.height,
            "fps": config.fps,
            "mock": config.mock,
        },
        "recorder": {
            "interval_seconds": config.interval,
            "frames_saved": frames_saved,
        },
        "storage": "local-only; never uploaded",
    }
    path = session.root / "metadata.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


MANIFEST_FIELDS = ["index", "timestamp_iso", "timestamp_ms"]


def add_manifest_row(session: Session, index: int, timestamp_iso: str, timestamp_ms: int) -> Path:
    """Append one saved frame to ``manifest.csv`` (with a header on first write)."""
    path = session.root / "manifest.csv"
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(MANIFEST_FIELDS)
        writer.writerow([index, timestamp_iso, timestamp_ms])
    return path