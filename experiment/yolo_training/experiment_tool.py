"""Shared, pure logic for the experiment-specific detection dataset.

Everything here is camera-free and image-free: it is the vocabulary, the
session index, the annotation store, frame sampling and the dataset report.
`annotate.py` (FastAPI UI), `prelabel.py`, `validate_annotations.py` and
`visualize_annotations.py` all build on this, and the tests use it directly.

Design rules that this module exists to enforce:

- **A proposal is not ground truth.** Proposals live in their own tree
  (`proposals/`) and are only ever *displayed* to the annotator. A box becomes a
  label when a human accepts, edits or draws it and the frame is marked
  reviewed. `label_rows` will not emit unreviewed proposals.
- **Session identity is preserved end to end** (`session_id`, `frame_id`,
  `source`). Splitting by session later is only correct if the provenance
  survives annotation, so it is written next to every label.
- **The vocabulary is data** (`classes.json`), never a literal in code.
- **Geometric classes are never auto-proposed.** Only `person` (COCO) and
  `red_box`/`yellow_box` (saturated-hue) have generators; `main_experiment_box`
  and the two target areas are manual until a reliable heuristic exists.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

# --------------------------------------------------------------------- layout

#: ``experiment/yolo_training/`` -> repo root -> ``dataset/experiment_detection``
REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset" / "experiment_detection"

CLASSES_FILE = DATASET_DIR / "classes.json"
IMAGES_DIR = DATASET_DIR / "images"
LABELS_DIR = DATASET_DIR / "labels"
METADATA_DIR = DATASET_DIR / "metadata"
PROPOSALS_DIR = DATASET_DIR / "proposals"
SAMPLING_DIR = DATASET_DIR / "sampling"
QA_DIR = DATASET_DIR / "qa"
INDEX_FILE = DATASET_DIR / "index.json"
REPORT_FILE = DATASET_DIR / "dataset_report.json"

#: The three splits. Created empty on purpose: PHASE 3 must not split, because
#: one recording cannot support an honest train/val/test split.
SPLITS = ("train", "val", "test")

#: Where the confirmed labels live until a session-aware split exists.
STAGING = "staging"

#: Where frames are *selected* for review. Originals are never modified or
#: deleted; this is a pointer list, not a copy of the pixels.
SELECTION_FILE = DATASET_DIR / "selection.json"

REPO_ROOT = REPO_ROOT
#: Recorded sources. `activity` sessions already carry a procedure label in the
#: directory name, which is why they are worth keeping separate (section 9).
SOURCE_GLOBS = (
    "dataset/raw/*/*",
    "dataset/activity/*/*",
)

#: Activity vocabulary, mirroring the canonical experiment. Kept as a guard only:
#: the real value is read from each activity session's own directory name.
ACTIVITY_NAMES = (
    "APPROACH",
    "OPEN_BOX",
    "PICK_RED",
    "PLACE_RED",
    "PICK_YELLOW",
    "PLACE_YELLOW",
)

_FRAME_RE = re.compile(r"(\d+)(?=\.[A-Za-z]+$)")


# ------------------------------------------------------------------- classes
@dataclass(frozen=True)
class Vocabulary:
    """The locked class list plus the proposal policy per class."""

    classes: tuple[str, ...]
    notes: dict[str, str] = field(default_factory=dict)

    def index(self, name: str) -> int:
        try:
            return self.classes.index(name)
        except ValueError:
            raise ValueError(f"unknown class {name!r}; known: {', '.join(self.classes)}") from None

    def id_of(self, name: str) -> Optional[int]:
        return self.classes.index(name) if name in self.classes else None

    def name_of(self, class_id: int) -> str:
        if not 0 <= class_id < len(self.classes):
            raise ValueError(f"class id {class_id} outside 0..{len(self.classes) - 1}")
        return self.classes[class_id]

    def valid_id(self, class_id: int) -> bool:
        return isinstance(class_id, int) and 0 <= class_id < len(self.classes)

    @property
    def n(self) -> int:
        return len(self.classes)


def load_vocabulary(path: str | Path | None = None) -> Vocabulary:
    p = Path(path) if path else CLASSES_FILE
    data = json.loads(p.read_text(encoding="utf-8"))
    classes = tuple(str(c).strip() for c in data.get("classes", []) if str(c).strip())
    if not classes:
        raise ValueError(f"{p}: no classes configured")
    if len(set(classes)) != len(classes):
        raise ValueError(f"{p}: duplicate class names")
    return Vocabulary(classes, data.get("class_notes", {}))


#: Classes that may be auto-proposed. Deliberately short (section 6): the
#: geometric scene classes need a human until a reliable heuristic exists.
PROPOSABLE = ("person", "red_box", "yellow_box")

#: Classes that must be annotated by hand.
MANUAL_ONLY = ("main_experiment_box", "red_target_area", "yellow_target_area")


# ------------------------------------------------------------------ indexing
@dataclass(frozen=True)
class Frame:
    """One recorded frame, with the provenance that splitting depends on."""

    session_id: str
    frame_id: int
    filename: str
    source: str
    activity: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.session_id}/{self.filename}"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "frame_id": self.frame_id,
            "filename": self.filename,
            "source": self.source,
            "activity": self.activity,
        }


@dataclass(frozen=True)
class Session:
    """A recording session: one contiguous take, the unit of any later split."""

    session_id: str
    kind: str
    label: str
    activity: Optional[str]
    path: str
    frames: tuple[Frame, ...]

    @property
    def n_frames(self) -> int:
        return len(self.frames)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "kind": self.kind,
            "label": self.label,
            "activity": self.activity,
            "path": self.path,
            "n_frames": self.n_frames,
            "frames": [f.to_dict() for f in self.frames],
        }


def _frame_id(filename: str) -> Optional[int]:
    m = _FRAME_RE.search(filename)
    return int(m.group(1)) if m else None


def discover_sessions(repo_root: str | Path = REPO_ROOT) -> list[Session]:
    """Every recorded session under ``dataset/raw`` and ``dataset/activity``.

    ``dataset/experiment_train`` is excluded on purpose: the audit showed its
    labels are auto-generated, 100% one class, and do not match any recording.
    It is not annotation ground truth and must never become training data.
    """
    root = Path(repo_root)
    sessions: list[Session] = []
    for pattern in SOURCE_GLOBS:
        for manifest in sorted(root.glob(f"{pattern}/manifest.csv")):
            directory = manifest.parent
            kind = directory.parent.parent.name  # raw | activity
            label = directory.parent.name
            activity = label if kind == "activity" else None
            if activity is not None and activity not in ACTIVITY_NAMES:
                activity = None
            images = sorted(
                p for p in directory.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
            )
            frames = []
            seen_ids: dict[int, str] = {}
            for p in images:
                fid = _frame_id(p.name)
                if fid is None:
                    continue
                # Two files parsing to the same number would share one metadata
                # key and one label file, so the second would silently destroy
                # the first human's work. Refuse the collision loudly.
                if fid in seen_ids:
                    raise ValueError(
                        f"{directory}: frame id {fid} is claimed by both "
                        f"{seen_ids[fid]} and {p.name}; frame ids must be unique "
                        "within a session or annotations would collide"
                    )
                seen_ids[fid] = p.name
                frames.append(
                    Frame(
                        session_id=directory.name,
                        frame_id=fid,
                        filename=p.name,
                        source=str(p.relative_to(root)).replace("\\", "/"),
                        activity=activity,
                    )
                )
            if not frames:
                continue
            sessions.append(
                Session(
                    session_id=directory.name,
                    kind=kind,
                    label=label,
                    activity=activity,
                    path=str(directory.relative_to(root)).replace("\\", "/"),
                    frames=tuple(frames),
                )
            )
    return sessions


def build_index(repo_root: str | Path = REPO_ROOT) -> dict:
    """The frame catalogue. Written to ``index.json``; never contains labels."""
    sessions = discover_sessions(repo_root)
    return {
        "schema": "astra-experiment-index/1",
        "repo_root": str(Path(repo_root)),
        "vocabulary": list(load_vocabulary().classes),
        "proposable": list(PROPOSABLE),
        "manual_only": list(MANUAL_ONLY),
        "sessions": [s.to_dict() for s in sessions],
        "totals": {
            "sessions": len(sessions),
            "frames": sum(s.n_frames for s in sessions),
            "activity_sessions": sum(1 for s in sessions if s.activity),
        },
    }


def save_index(index: dict, path: str | Path | None = None) -> Path:
    p = Path(path) if path else INDEX_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(index, indent=2), encoding="utf-8")
    return p


def load_index(path: str | Path | None = None) -> dict:
    p = Path(path) if path else INDEX_FILE
    if not p.is_file():
        raise FileNotFoundError(
            f"{p} not found. Run `prelabel.py --index` (or `annotate.py --reindex`) first."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def iter_frames(index: dict) -> Iterable[tuple[dict, Frame]]:
    for session in index.get("sessions", []):
        for raw in session.get("frames", []):
            yield session, Frame(
                session_id=raw["session_id"],
                frame_id=raw["frame_id"],
                filename=raw["filename"],
                source=raw["source"],
                activity=raw.get("activity"),
            )


# ----------------------------------------------------------------- proposals
def proposals_path(session_id: str, frame_id: int, root: str | Path | None = None) -> Path:
    return Path(root if root else PROPOSALS_DIR) / session_id / f"frame_{frame_id:06d}.json"


def save_proposals(
    session_id: str,
    frame_id: int,
    boxes: list[dict],
    path: str | Path | None = None,
) -> Path:
    """Store candidate boxes. **Not** a label file, and never read as one."""
    p = proposals_path(session_id, frame_id, path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "schema": "astra-experiment-proposal/1",
                "session_id": session_id,
                "frame_id": frame_id,
                "status": "unreviewed",
                "proposals": boxes,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return p


def load_proposals(
    session_id: str, frame_id: int, path: str | Path | None = None
) -> list[dict]:
    p = proposals_path(session_id, frame_id, path)
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("proposals", [])


# ------------------------------------------------------- confirmed annotations
def label_path(session_id: str, frame_id: int, split: str = STAGING) -> Path:
    return LABELS_DIR / split / session_id / f"frame_{frame_id:06d}.txt"


def metadata_path(session_id: str) -> Path:
    return METADATA_DIR / f"{session_id}.json"


def save_annotations(
    session_id: str,
    frame_id: int,
    boxes: list[dict],
    *,
    source: str,
    activity: Optional[str] = None,
    reviewed: bool = True,
    split: str = STAGING,
    image_size: Optional[tuple[int, int]] = None,
) -> dict:
    """Write the human-confirmed labels for one frame.

    ``boxes`` are ``{"class": name, "bbox": [x1, y1, w, h]}`` in **pixel**
    coordinates; they are normalized here so the on-disk YOLO text can never
    disagree with the pixels the annotator actually drew.
    """
    vocab = load_vocabulary()
    meta = load_metadata(session_id)
    frame_meta = meta.setdefault("frames", {})
    width, height = image_size or frame_meta.get(str(frame_id), {}).get("image_size", [0, 0])
    if not width or not height:
        raise ValueError(f"image size required to normalize frame {session_id}/{frame_id}")

    lines: list[str] = []
    entries: list[dict] = []
    for box in boxes:
        class_id = vocab.id_of(box["class"])
        if class_id is None:
            raise ValueError(f"unknown class {box['class']!r}")
        x, y, w, h = (float(v) for v in box["bbox"])
        x, y = max(0.0, x), max(0.0, y)
        w = max(1.0, min(w, width - x))
        h = max(1.0, min(h, height - y))
        cx, cy = (x + w / 2) / width, (y + h / 2) / height
        lines.append(f"{class_id} {cx:.6f} {cy:.6f} {w / width:.6f} {h / height:.6f}")
        entries.append(
            {
                "class": box["class"],
                "class_id": class_id,
                "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                "yolo": [round(cx, 6), round(cy, 6), round(w / width, 6), round(h / height, 6)],
            }
        )

    p = label_path(session_id, frame_id, split)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    frame_meta[str(frame_id)] = {
        "frame_id": frame_id,
        "frame_key": frame_key(session_id, frame_id),
        "source": source,
        "activity": activity,
        "reviewed": bool(reviewed),
        "empty": not entries,
        "image_size": [int(width), int(height)],
        "annotations": entries,
    }
    meta.update(
        {
            "schema": "astra-experiment-annotation/1",
            "session_id": session_id,
            "activity": activity,
            "n_frames_annotated": len(frame_meta),
        }
    )
    _write_metadata(session_id, meta)
    return annotation_state(session_id, frame_id, split)


def load_metadata(session_id: str) -> dict:
    p = metadata_path(session_id)
    if not p.is_file():
        return {"schema": "astra-experiment-annotation/1", "session_id": session_id, "frames": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def _write_metadata(session_id: str, meta: dict) -> Path:
    """Atomic, retrying write.

    The reviewed flag is the only thing standing between a human's work and the
    training set, so a crash mid-write must not leave a half-written metadata
    file that silently drops every reviewed frame in the session.

    ``os.replace`` can transiently fail on Windows (WinError 5) when an indexer
    or another handle touches the file, so it is retried before falling back to
    a direct write. A failed save is worse than a slightly less atomic one.
    """
    p = metadata_path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    meta["n_frames_annotated"] = len(meta.get("frames", {}))
    payload = json.dumps(meta, indent=2)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    for attempt in range(5):
        try:
            tmp.replace(p)
            return p
        except PermissionError:
            if attempt == 4:
                break
            time.sleep(0.1 * (attempt + 1))
    # last resort: overwrite in place, then drop the temp file
    p.write_text(payload, encoding="utf-8")
    tmp.unlink(missing_ok=True)
    return p


def frame_key(session_id: str, frame_id: int) -> str:
    """Stable identity for one annotated frame.

    Keyed on session **and** frame id, never on the filename alone: every
    session has its own ``frame_000074.txt``, so a filename-keyed flag would
    collide as soon as a second session annotates the same index.
    """
    return f"{session_id}/{int(frame_id):06d}"


def annotation_state(session_id: str, frame_id: int, split: str = STAGING) -> dict:
    """The one source of truth for a frame's annotation + review state.

    The UI and the validator both read this, so "is this frame reviewed" can
    never mean two different things depending on who is asking.
    """
    entry = load_metadata(session_id).get("frames", {}).get(str(int(frame_id)), {})
    lp = label_path(session_id, frame_id, split)
    return {
        "session_id": session_id,
        "frame_id": int(frame_id),
        "key": frame_key(session_id, frame_id),
        "has_label_file": lp.is_file(),
        "has_metadata": bool(entry),
        "reviewed": bool(entry.get("reviewed", False)),
        "empty": bool(entry.get("empty", False)),
        "n_boxes": len(entry.get("annotations", [])),
        "annotations": entry.get("annotations", []),
        "image_size": entry.get("image_size", [0, 0]),
        "activity": entry.get("activity"),
    }


def set_reviewed(session_id: str, frame_id: int, reviewed: bool, split: str = STAGING) -> dict:
    """Persist the human's review decision for exactly one frame.

    Separate from :func:`save_annotations` on purpose. Ticking the box is a
    decision about the frame, not about its boxes, so it must be storable on
    its own — including for a frame whose labels were written by an earlier
    tool version and must not be redrawn.
    """
    meta = load_metadata(session_id)
    frames = meta.setdefault("frames", {})
    entry = frames.setdefault(
        str(int(frame_id)),
        {"frame_id": int(frame_id), "annotations": [], "empty": True, "image_size": [0, 0]},
    )
    entry["reviewed"] = bool(reviewed)
    entry["frame_key"] = frame_key(session_id, frame_id)
    entry.setdefault("reviewed_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if not reviewed:
        entry.pop("reviewed_at", None)
    meta.setdefault("schema", "astra-experiment-annotation/1")
    meta["session_id"] = session_id
    _write_metadata(session_id, meta)
    return annotation_state(session_id, frame_id, split)


def unreviewed_label_frames(index: dict, split: str = STAGING) -> list[dict]:
    """Frames that have a label file but were never marked reviewed.

    This is the state an inconsistent save can leave behind: the boxes are on
    disk, the decision was not recorded. It is reported, never silently fixed.
    """
    out = []
    for session, frame in iter_frames(index):
        state = annotation_state(frame.session_id, frame.frame_id, split)
        if state["has_label_file"] and not state["reviewed"]:
            out.append(state)
    return out


def backfill_reviewed(index: dict, split: str = STAGING, session_filter: str | None = None) -> list[dict]:
    """Promote already-written labels to reviewed, without touching the boxes.

    Recovery path for labels a human drew but whose review flag was lost (for
    example when the UI reset the checkbox on every navigation). Only frames
    that **already have a label file on disk** are promoted, so this can never
    invent an annotation; the stored boxes are left byte-for-byte untouched.
    """
    promoted = []
    for state in unreviewed_label_frames(index, split):
        if session_filter and state["session_id"] != session_filter:
            continue
        set_reviewed(state["session_id"], state["frame_id"], True, split)
        promoted.append(state)
    return promoted


def label_rows(index: dict, split: str = STAGING) -> list[dict]:
    """Only frames a human has marked reviewed become training rows.

    This is the guard against proposals silently becoming ground truth: an
    unreviewed frame contributes nothing, whatever proposals exist for it.
    """
    rows = []
    for session, frame in iter_frames(index):
        state = annotation_state(frame.session_id, frame.frame_id, split)
        if not state["reviewed"]:
            continue
        lp = label_path(frame.session_id, frame.frame_id, split)
        rows.append(
            {
                "session_id": frame.session_id,
                "frame_id": frame.frame_id,
                "key": state["key"],
                "filename": frame.filename,
                "source": frame.source,
                # the session directory is authoritative; the value recorded at
                # save time is the fallback, so provenance survives either path
                "activity": frame.activity or state["activity"],
                "label_file": str(lp.relative_to(LABELS_DIR.parent)).replace("\\", "/"),
                "n_boxes": state["n_boxes"],
                "empty": state["empty"],
                "image_size": state["image_size"],
            }
        )
    return rows


# ------------------------------------------------------------- frame sampling
def sample_frames(
    session: dict,
    *,
    head: int = 4,
    tail: int = 4,
    uniform: int = 6,
    budget: int = 0,
) -> list[int]:
    """Representative frame ids for one session, in ascending order.

    Beginning / middle / end plus an even spread, so a human can see coverage
    before opening anything. ``budget`` caps the count; 0 means no cap. This is
    a *review order*, never a label: every sampled frame still needs a human.
    """
    ids = [int(f["frame_id"]) for f in session.get("frames", [])]
    if not ids:
        return []
    picks: set[int] = set(ids[:head]) | set(ids[-tail:]) if tail else set(ids[:head])
    if uniform > 0:
        step = max(1, (len(ids) - 1) // max(1, uniform - 1))
        picks.update(ids[::step][:uniform])
        picks.add(ids[(len(ids) - 1) // 2])
    out = sorted(picks)
    if budget and len(out) > budget:
        keep = {out[0], out[-1]}
        middle = [i for i in out if i not in keep]
        stride = max(1, len(middle) // max(1, budget - 2))
        keep.update(middle[::stride][: budget - 2])
        out = sorted(keep)
    return out


def critical_frames(index: dict) -> dict[str, list[int]]:
    """Activity sessions map straight to their action, so all frames matter.

    These are the frames a later temporal model needs (hand approaching, contact,
    carry, release), which is why they are oversampled rather than sampled.
    """
    out: dict[str, list[int]] = {}
    for session in index.get("sessions", []):
        if not session.get("activity"):
            continue
        out.setdefault(session["activity"], []).extend(
            int(f["frame_id"]) for f in session.get("frames", [])
        )
    return {k: sorted(set(v)) for k, v in sorted(out.items())}


def build_selection(index: dict, budget: int = 24) -> dict:
    sampled = {}
    for session in index.get("sessions", []):
        ids = sample_frames(session, budget=budget)
        if ids:
            sampled[session["session_id"]] = {
                "activity": session.get("activity"),
                "label": session.get("label"),
                "frame_ids": ids,
                "n_frames": session.get("n_frames", len(ids)),
            }
    selection = {
        "schema": "astra-experiment-selection/1",
        "budget_per_session": budget,
        "sessions": sampled,
        "critical_by_activity": critical_frames(index),
        "totals": {
            "sessions_sampled": len(sampled),
            "frames_selected": sum(len(v["frame_ids"]) for v in sampled.values()),
        },
    }
    p = SELECTION_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    return selection


# ------------------------------------------------------------------ reporting
def dataset_report(index: dict, split: str = STAGING) -> dict:
    """Counts only what is on disk. Never estimates or infers a number."""
    vocab = load_vocabulary()
    rows = label_rows(index, split)
    per_class = {c: 0 for c in vocab.classes}
    sessions_per_class: dict[str, set] = {c: set() for c in vocab.classes}
    per_session: dict[str, dict] = {}
    for row in rows:
        meta = load_metadata(row["session_id"])["frames"][str(row["frame_id"])]
        bucket = per_session.setdefault(
            row["session_id"],
            {"activity": row["activity"], "frames": 0, "empty": 0, "classes": {}},
        )
        bucket["frames"] += 1
        bucket["empty"] += 1 if row["empty"] else 0
        for ann in meta.get("annotations", []):
            per_class[ann["class"]] = per_class.get(ann["class"], 0) + 1
            sessions_per_class[ann["class"]].add(row["session_id"])
            bucket["classes"][ann["class"]] = bucket["classes"].get(ann["class"], 0) + 1

    proposal_counts = {c: 0 for c in PROPOSABLE}
    proposal_files = 0
    for session, frame in iter_frames(index):
        props = load_proposals(frame.session_id, frame.frame_id)
        if props:
            proposal_files += 1
            for p in props:
                if p.get("class") in proposal_counts:
                    proposal_counts[p["class"]] += 1

    activity_sessions: dict[str, int] = {}
    for session in index.get("sessions", []):
        if session.get("activity"):
            activity_sessions[session["activity"]] = activity_sessions.get(session["activity"], 0) + 1

    return {
        "schema": "astra-experiment-report/1",
        "sessions": index.get("totals", {}).get("sessions", 0),
        "source_frames": index.get("totals", {}).get("frames", 0),
        "annotated_frames": len(rows),
        "empty_label_frames": sum(1 for r in rows if r["empty"]),
        "objects_per_class": per_class,
        "sessions_per_class": {k: len(v) for k, v in sessions_per_class.items()},
        "proposed_objects": proposal_counts,
        "frames_with_proposals": proposal_files,
        "frames_awaiting_human": index.get("totals", {}).get("frames", 0) - len(rows),
        "activity_sessions": activity_sessions,
        "per_session": per_session,
        "vocabulary": list(vocab.classes),
        "proposable": list(PROPOSABLE),
        "manual_only": list(MANUAL_ONLY),
    }


def save_report(report: dict, path: str | Path | None = None) -> Path:
    p = Path(path) if path else REPORT_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return p


def ensure_layout(root: str | Path | None = None) -> None:
    """Create the tree. Split dirs stay empty: PHASE 3 does not split."""
    for sub in (IMAGES_DIR, LABELS_DIR, METADATA_DIR, PROPOSALS_DIR, SAMPLING_DIR, QA_DIR):
        sub.mkdir(parents=True, exist_ok=True)
    for split in SPLITS:
        (IMAGES_DIR / split).mkdir(parents=True, exist_ok=True)
        (LABELS_DIR / split).mkdir(parents=True, exist_ok=True)
    (LABELS_DIR / STAGING).mkdir(parents=True, exist_ok=True)
