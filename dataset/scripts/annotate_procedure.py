"""CLI: label a recorded session with canonical procedure step ground truth.

The object labels in ``dataset/annotations/`` say what is in each frame; this
adds the missing second label - which procedure step the frame belongs to -
derived from ``experiment/experiment.json`` so it cannot drift from the sequence
the app enforces.

    python dataset\\scripts\\annotate_procedure.py --session dataset\\raw\\box_experiment\\session_20260829_235407_o3s3
    python dataset\\scripts\\annotate_procedure.py --root dataset --all

The label is **visibility-derived**: it records that the objects a step needs
were in frame. It is NOT proof that the action happened (a PICK cannot be told
from a pass-by in a single frame). ``procedure_tool`` documents the limits; read
them before training on this.

Exits 2 on anything unusable (missing manifest, no classes, nothing labelled).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DATASET_DIR = Path(__file__).resolve().parents[1]
if str(DATASET_DIR) not in sys.path:
    sys.path.insert(0, str(DATASET_DIR))

from procedure_tool import (  # noqa: E402
    NO_STEP,
    label_session,
    load_procedure,
    read_manifest,
)


def find_sessions(root: Path) -> list[Path]:
    """Every recorded session directory (a dir holding ``manifest.csv``)."""
    out: list[Path] = []
    for kind in ("raw", "activity"):
        base = root / kind
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("manifest.csv")):
            out.append(path.parent)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--session", type=Path, help="one session directory")
    target.add_argument("--root", type=Path, default=None, help="dataset root, with --all")
    target.add_argument("--all", action="store_true", help="label every session under --root")
    parser.add_argument(
        "--labels",
        type=Path,
        default=None,
        help="YOLO label folder for this session (default: dataset/annotations/<label>/<session>)",
    )
    parser.add_argument("--out", type=Path, default=None, help="output CSV path")
    args = parser.parse_args(argv)

    steps = load_procedure()
    if args.all:
        if args.root is None:
            parser.error("--all requires --root")
        sessions = find_sessions(args.root)
        if not sessions:
            print(f"no sessions with a manifest.csv under {args.root}", file=sys.stderr)
            return 2
    else:
        if args.root is not None and not args.all:
            parser.error("--root is only used together with --all")
        sessions = [args.session]
        for session in sessions:
            if session is None or not (session / "manifest.csv").is_file():
                print(f"not a session directory (no manifest.csv): {session}", file=sys.stderr)
                return 2

    labelled_total = 0
    for session in sessions:
        label_dir = args.labels
        if label_dir is None:
            label_dir = DATASET_DIR / "annotations" / session.parent.name / session.name
        path, rows = label_session(session, steps, args.out, label_dir)
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["activity"]] = counts.get(row["activity"], 0) + 1
        labelled = sum(1 for row in rows if row["activity"] != NO_STEP)
        labelled_total += labelled
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        print(f"{session.name}: {labelled}/{len(rows)} frames labelled -> {path}")
        print(f"  {summary}")

    if labelled_total == 0:
        print(
            "no frame matched a step: is there per-frame class information? "
            "(manifest 'classes' column or YOLO labels under --labels)",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
