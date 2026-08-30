"""Pure logic for the ACTIVITY dataset (Phase 5B).

Activity names come from the canonical ``experiment/experiment.json`` — the
vocabulary lives only there, never duplicated here or in the recorder CLI.
Each recording session lands at
``<output>/activity/<ACTIVITY>/session_<ts>_<rand>/`` and contains JPEG
frames, ``metadata.json`` and ``manifest.csv``.

This module is intentionally camera- and cv2-free (imports happen inside the
methods that need them), mirroring ``dataset_tool.py`` for the object dataset.
"""

from __future__ import annotations

import csv
import json
import random
import string
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from dataset_tool import slugify

DATASET_DIR = Path(__file__).resolve().parent
EXPERIMENT_JSON = DATASET_DIR.parent / "experiment" / "experiment.json"

MANIFEST_FIELDS = ["index", "timestamp_iso", "timestamp_ms", "filename"]
META_SCHEMA = "bas-activity-session/1"


def load_activities() -> list[str]:
    """Canonical activity names from experiment/experiment.json (order kept)."""
    payload = json.loads(EXPERIMENT_JSON.read_text(encoding="utf-8"))
    names = list(dict.fromkeys(str(a).strip() for a in payload.get("activities", []) if str(a).strip()))
    if not names:
        raise ValueError(f"{EXPERIMENT_JSON} defines no activities")
    return names


def is_valid_activity(name: str) -> bool:
    return name in load_activities()


@dataclass(frozen=True)
class ActivityConfig:
    activity: str
    camera_index: int = 0
    width: int = 1280
    height: int = 720
    fps: int = 30
    interval: float = 0.5
    mock: bool = False
    output_dir: Path = DATASET_DIR

    def __post_init__(self) -> None:
        if not is_valid_activity(self.activity):
            raise ValueError(
                f"invalid activity {self.activity!r}; valid activities: {', '.join(load_activities())}"
            )
        if self.camera_index < 0:
            raise ValueError("camera_index must be >= 0")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("width and height must be positive")
        if self.fps <= 0:
            raise ValueError("fps must be positive")
        if self.interval <= 0:
            raise ValueError("interval must be positive")

    def to_camera_settings(self):
        from camera.capture import CameraSettings

        return CameraSettings(
            camera_index=self.camera_index,
            width=self.width,
            height=self.height,
            fps=self.fps,
            mock=self.mock,
        )

    @property
    def source(self) -> str:
        return "mock" if self.mock else "webcam"

    @property
    def activity_dir(self) -> Path:
        # The activity path component mirrors dataset/raw: the activity name
        # itself (data, kept verbatim) — no extra slugification layer.
        return self.output_dir / "activity" / slugify(self.activity).upper().replace("-", "_")


@dataclass(frozen=True)
class ActivitySession:
    session_id: str
    root: Path
    activity: str
    started_at_iso: str


def activity_frame_filename(index: int) -> str:
    return f"frame_{index:06d}.jpg"


def create_activity_session(config: ActivityConfig) -> ActivitySession:
    activity_dir = config.activity_dir
    activity_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    started_iso = now.isoformat(timespec="seconds")
    for _ in range(10):
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
        session_id = f"{stamp}_{suffix}"
        root = activity_dir / f"session_{session_id}"
        try:
            root.mkdir()
            break
        except FileExistsError:
            continue
    else:
        raise RuntimeError("could not allocate a unique activity session directory")
    session = ActivitySession(
        session_id=session_id,
        root=root,
        activity=config.activity,
        started_at_iso=started_iso,
    )
    write_activity_metadata(session, config)
    return session


def write_activity_metadata(
    session: ActivitySession,
    config: ActivityConfig,
    *,
    ended_at: str | None = None,
    frame_count: int = 0,
) -> Path:
    payload = {
        "schema": META_SCHEMA,
        "activity": session.activity,
        "session_id": session.session_id,
        "started_at": session.started_at_iso,
        "ended_at": ended_at,
        "camera": {
            "index": config.camera_index,
            "width": config.width,
            "height": config.height,
            "fps": config.fps,
            "mock": config.mock,
        },
        "frame_count": frame_count,
        "interval": config.interval,
        "source": config.source,
        "storage": "local-only; never uploaded",
    }
    path = session.root / "metadata.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def add_activity_manifest_row(
    session: ActivitySession,
    index: int,
    timestamp_iso: str,
    timestamp_ms: int,
    filename: str,
) -> Path:
    path = session.root / "manifest.csv"
    new_file = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(MANIFEST_FIELDS)
        writer.writerow([index, timestamp_iso, timestamp_ms, filename])
    return path