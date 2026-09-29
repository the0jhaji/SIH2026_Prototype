"""Validate the human-confirmed annotations before anything is trained on them.

    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\validate_annotations.py
    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\validate_annotations.py --strict

Checks, in order of how badly they would poison training:

1. class ids inside the locked vocabulary, and no excluded action/state class
2. normalized geometry in range, w/h > 0, nothing outside the image
3. the class actually appears somewhere, per session & overall (a class with
   zero boxes cannot be learned, and here that is expected, not a bug)
4. session/frame integrity: every label maps to a real recorded frame
5. proposals never leak into the label tree, and every reviewed frame is
   either annotated or explicitly marked empty/background

Exits 2 when there is an error, so a bad dataset cannot be silently exported.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (str(REPO_ROOT), str(HERE)):
    if p not in sys.path:
        sys.path.insert(0, p)

from experiment_tool import (  # noqa: E402
    LABELS_DIR,
    MANUAL_ONLY,
    STAGING,
    annotation_state,
    build_index,
    dataset_report,
    iter_frames,
    label_path,
    label_rows,
    load_vocabulary,
    save_report,
    save_index,
    unreviewed_label_frames,
)


def validate(split: str = STAGING) -> tuple[list[str], list[str], dict]:
    vocab = load_vocabulary()
    index = build_index()
    save_index(index)
    errors: list[str] = []
    warnings: list[str] = []
    real = {(f.session_id, f.frame_id) for _, f in iter_frames(index)}

    for session, frame in iter_frames(index):
        # Identified by session + frame id, never the bare filename: every
        # session has its own frame_000074.txt.
        key = f"{frame.session_id} frame {frame.frame_id}"
        lp = label_path(frame.session_id, frame.frame_id, split)
        state = annotation_state(frame.session_id, frame.frame_id, split)
        entry_exists = state["has_metadata"]
        if not lp.is_file():
            if entry_exists and state["reviewed"]:
                errors.append(f"{key}: reviewed but no label file ({lp.name})")
            continue
        if (frame.session_id, frame.frame_id) not in real:
            errors.append(f"{key}: label has no matching recorded frame")
        if not entry_exists:
            errors.append(f"{key}: label exists but there is no annotation record for it")
        elif not state["reviewed"]:
            errors.append(
                f"{key}: label exists but the frame was never marked reviewed "
                f"({lp.name}) - tick 'reviewed' in the UI, or run "
                f"review_frames.py --mark-reviewed {frame.session_id}"
            )
        width, height = state["image_size"]
        if not width or not height:
            errors.append(f"{key}: no image size recorded; cannot verify geometry")
            continue
        for n, line in enumerate(lp.read_text(encoding="utf-8").splitlines(), 1):
            parts = line.split()
            if len(parts) != 5:
                errors.append(f"{key}:{n}: expected 5 fields, got {len(parts)}")
                continue
            try:
                cid = int(parts[0])
                cx, cy, w, h = (float(v) for v in parts[1:])
            except ValueError:
                errors.append(f"{key}:{n}: non-numeric field")
                continue
            if not vocab.valid_id(cid):
                errors.append(f"{key}:{n}: class id {cid} outside 0..{vocab.n - 1}")
                continue
            if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
                errors.append(f"{key}:{n}: centre {cx},{cy} outside 0..1")
            if not (0.0 < w <= 1.0 and 0.0 < h <= 1.0):
                errors.append(f"{key}:{n}: size {w},{h} outside (0,1]")
            if (cx - w / 2) < -1e-6 or (cy - h / 2) < -1e-6 or (cx + w / 2) > 1 + 1e-6 or (cy + h / 2) > 1 + 1e-6:
                errors.append(f"{key}:{n}: box escapes the image")

    for row in label_rows(index, split):
        if not (LABELS_DIR.parent / row["label_file"]).is_file():
            errors.append(f"{row['key']}: listed in the index but missing on disk")

    # Proposal leakage: the label tree must not contain generator metadata.
    for lp in LABELS_DIR.rglob("*.txt"):
        if "proposal" in lp.read_text(encoding="utf-8").lower():
            errors.append(f"{lp}: proposal text found in the label tree")

    report = dataset_report(index, split)
    rows = label_rows(index, split)

    for name, n in report["objects_per_class"].items():
        if n == 0:
            msg = f"class {name!r} has 0 confirmed boxes"
            # Expected while the human works through the queue; fatal only with --strict.
            warnings.append(msg + " (a model cannot learn a class it never sees)")
    for name in MANUAL_ONLY:
        if report["objects_per_class"][name] == 0 and rows:
            warnings.append(f"manual class {name!r} still unannotated in every reviewed frame")
    if report["annotated_frames"] and all(
        report["objects_per_class"][c] == 0 for c in vocab.classes
    ):
        errors.append("frames were marked reviewed but not one object was confirmed")
    if not rows:
        warnings.append("no reviewed frames yet: 0 training rows, which is correct at this stage")

    for cls, n in report["proposed_objects"].items():
        if n:
            warnings.append(f"{n} unreviewed {cls} proposals are waiting for a human decision")

    stranded = unreviewed_label_frames(index, split)
    if stranded:
        warnings.append(
            f"{len(stranded)} frame(s) have saved labels but no review decision, so they "
            "are excluded from training: "
            + ", ".join(s["key"] for s in stranded[:8])
            + (" ..." if len(stranded) > 8 else "")
        )
    return errors, warnings, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", default=STAGING)
    ap.add_argument("--strict", action="store_true", help="treat a missing class as an error")
    ap.add_argument("--json", action="store_true", help="print the report only")
    args = ap.parse_args(argv)

    errors, warnings, report = validate(args.split)
    if args.strict:
        errors += [w for w in warnings if "0 confirmed boxes" in w]
        warnings = [w for w in warnings if "0 confirmed boxes" not in w]
    save_report(report)
    if args.json:
        print(report)
        return 2 if errors else 0

    print(f"vocabulary: {', '.join(report['vocabulary'])}")
    print(f"sessions {report['sessions']} | source frames {report['source_frames']}")
    print(f"reviewed frames {report['annotated_frames']} (empty/background {report['empty_label_frames']})")
    print("confirmed objects per class:")
    for name, n in report["objects_per_class"].items():
        bar = "#" * min(40, n)
        print(f"  {name:<22} {n:>5}  {bar}")
    print("proposals awaiting a human (not labels):")
    for name, n in report["proposed_objects"].items():
        print(f"  {name:<22} {n:>5}")

    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  ! {w}")
    if errors:
        print(f"\n{len(errors)} ERROR(s):", file=sys.stderr)
        for e in errors:
            print(f"  x {e}", file=sys.stderr)
        return 2
    print("\nno errors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
