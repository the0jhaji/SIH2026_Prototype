"""Pure logic for deriving procedure step ground truth from a recorded session.

Why this exists: the object annotations in ``dataset/annotations/`` say *what is
in the frame*; nothing in the dataset says *which procedure step the frame
belongs to*. Training or evaluating an activity model needs that second label,
and it must come from the canonical experiment rather than from a hand-copied
list, or the labels silently drift from the sequence the app actually enforces.

Honest scope - read this before trusting the output:

* The label is derived from **object visibility** (the canonical
  ``expectedObjects`` contract), because a single recorded frame cannot prove
  that an object *moved* or *came to rest inside the target area*. So a label
  here means "the objects this step needs were visible", NOT "this action was
  performed". It is a weak, visibility-derived label.
* ``expectedEvents`` (the ``interaction`` source's motion/placement contract)
  is deliberately **not** used, because reconstructing motion needs the frame
  sequence and a tracker run, not this module. Do not read these labels as
  proof that a PICK or PLACE happened.
* A frame that satisfies several steps is labelled with the **earliest**
  unfinished one, so the label is stable and never skips ahead.
* Frames where nothing matches are labelled ``-`` (no step), never guessed.

No camera, no OpenCV, no production imports: this reads a manifest and the
canonical JSON, nothing else.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parent
EXPERIMENT_JSON = DATASET_DIR.parent / "experiment" / "experiment.json"

#: Column order of the emitted CSV. Kept explicit so the file is diffable.
PROCEDURE_FIELDS = ["index", "filename", "classes", "step_id", "step_order", "activity"]
SCHEMA = "bas-procedure-labels/1"

#: Sentinel for a frame that satisfies no step.
NO_STEP = "-"


@dataclass(frozen=True)
class ProcedureStep:
    """One canonical step reduced to what this module needs."""

    id: str
    order: int
    activity: str
    required: tuple[str, ...]

    @property
    def label(self) -> str:
        return self.activity


def load_procedure(path: str | Path | None = None) -> list[ProcedureStep]:
    """Read the canonical experiment and project it onto visibility needs.

    Steps with an empty ``expectedObjects`` list (legacy definitions) are kept
    with no requirements, which makes them match any frame; the caller decides
    whether that is useful.
    """
    p = Path(path) if path else EXPERIMENT_JSON
    data = json.loads(p.read_text(encoding="utf-8"))
    steps: list[ProcedureStep] = []
    for index, step in enumerate(data["steps"], start=1):
        steps.append(
            ProcedureStep(
                id=str(step["id"]),
                order=int(step.get("order") or index),
                activity=str(step["activity"]),
                required=tuple(step.get("expectedObjects") or ()),
            )
        )
    return steps


def step_for_classes(
    steps: list[ProcedureStep], classes: set[str], start_order: int = 1
) -> ProcedureStep | None:
    """Earliest step at/after ``start_order`` whose objects are all present.

    A step with no declared objects never matches: a step that requires nothing
    cannot be evidenced, and claiming otherwise would invent a label.
    """
    for step in steps:
        if step.order < start_order:
            continue
        if step.required and set(step.required).issubset(classes):
            return step
    return None


def read_manifest(session_dir: str | Path) -> list[dict]:
    """Read a session ``manifest.csv`` (written by the recorders).

    Recorders do not all emit the same columns: the object recorder writes only
    timing, the activity recorder adds ``filename``. Missing columns are simply
    absent from the row, so callers must not assume they exist.
    """
    path = Path(session_dir) / "manifest.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def classes_from_labels(
    label_dir: str | Path, classes: list[str], filename: str | None = None
) -> set[str]:
    """Class names present in a YOLO label file, reusing the annotator parser.

    This is the real source of per-frame class information: the object recorder
    never wrote a ``classes`` column, and the box-detection labels already exist
    under ``dataset/annotations/``. Label parsing lives in
    ``annotation/annotator.py`` and is deliberately not re-implemented here.
    """
    from annotation.annotator import parse_label, validate_label

    directory = Path(label_dir)
    if not directory.is_dir():
        return set()
    files = [directory / filename] if filename else sorted(directory.glob("*.txt"))
    present: set[str] = set()
    for file in files:
        if not file.is_file():
            continue
        boxes, errors = validate_label(file.read_text(encoding="utf-8"), classes)
        if errors:
            # A malformed label must not silently become a step label.
            continue
        for box in boxes or parse_label(file.read_text(encoding="utf-8")):
            if 0 <= box.class_id < len(classes):
                present.add(classes[box.class_id])
    return present


def label_files_for(rows: list[dict], session_dir: str | Path) -> list[str]:
    """Best-effort frame filename per manifest row, for label lookup."""
    session = Path(session_dir)
    images = sorted(
        [p.name for p in session.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}]
    )
    out: list[str] = []
    for index, row in enumerate(rows):
        name = row.get("filename") or (images[index] if index < len(images) else "")
        out.append(name)
    return out


def parse_classes(value: str | None) -> set[str]:
    """Parse the manifest's class column.

    Recorders join classes with ``;``. Unknown separators are treated as a
    single token rather than guessed at, so a malformed manifest produces an
    empty set (an unlabelled frame) instead of a wrong label.
    """
    if not value:
        return set()
    return {token.strip() for token in value.split(";") if token.strip()}


def label_rows(
    rows: list[dict],
    steps: list[ProcedureStep],
    start_order: int = 1,
    classes_by_frame: list[set[str]] | None = None,
) -> list[dict]:
    """Label each manifest row with the step its visible objects support.

    ``classes_by_frame`` supplies per-frame classes (from YOLO labels); it wins
    over the manifest's ``classes`` column when present. ``start_order`` advances
    past a step once a later frame matches it, so the label never moves
    backwards through the procedure.
    """
    out: list[dict] = []
    order = start_order
    for index, row in enumerate(rows):
        if classes_by_frame is not None:
            classes = set(classes_by_frame[index]) if index < len(classes_by_frame) else set()
        else:
            classes = parse_classes(row.get("classes"))
        step = step_for_classes(steps, classes, order)
        if step is not None:
            order = step.order + 1
        out.append(
            {
                "index": row.get("index", index),
                "filename": row.get("filename", ""),
                "classes": ";".join(sorted(classes)),
                "step_id": step.id if step else NO_STEP,
                "step_order": step.order if step else NO_STEP,
                "activity": step.activity if step else NO_STEP,
            }
        )
    return out


def write_labels(session_dir: str | Path, rows: list[dict], out_path: str | Path | None = None) -> Path:
    """Write the labelled rows as CSV, returning the path written."""
    session = Path(session_dir)
    target = Path(out_path) if out_path else session / "procedure_labels.csv"
    with target.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PROCEDURE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return target


def label_session(
    session_dir: str | Path,
    steps: list[ProcedureStep] | None = None,
    out_path: str | Path | None = None,
    label_dir: str | Path | None = None,
) -> tuple[Path, list[dict]]:
    """Label one recorded session; returns ``(path, rows)``.

    ``label_dir`` points at this session's YOLO label folder; when given, the
    per-frame classes come from those labels instead of the manifest.
    """
    session = Path(session_dir)
    rows = read_manifest(session)
    classes_by_frame = None
    if label_dir is not None:
        from annotation.annotator import load_classes

        classes = load_classes()
        filenames = label_files_for(rows, session)
        classes_by_frame = [
            classes_from_labels(Path(label_dir), classes, name) for name in filenames
        ]
    labelled = label_rows(rows, steps or load_procedure(), classes_by_frame=classes_by_frame)
    return write_labels(session, labelled, out_path), labelled
