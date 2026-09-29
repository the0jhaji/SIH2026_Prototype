"""Inspect and repair the review flag without redrawing a single box.

    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\review_frames.py --list
    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\review_frames.py --mark-reviewed
    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\review_frames.py --mark-reviewed --session session_20260829_233703_6weu
    .\\.venv\\Scripts\\python.exe experiment\\yolo_training\\review_frames.py --unmark 74 --session session_20260829_233703_6weu

Why this exists: the annotation UI used to re-derive the "reviewed" checkbox from
the server on every frame load, so a session of real, finished labels could be
stored with ``reviewed=false`` and then rejected by the validator. The boxes were
always saved correctly — only the decision was lost. This tool repairs that
decision from what is already on disk.

It never invents an annotation: ``--mark-reviewed`` only promotes frames that
**already have a label file**, and it never rewrites the YOLO text, so no box
coordinates can change. ``--list`` is read-only and is the safe first command.
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

import experiment_tool as et  # noqa: E402


def _summarize(index: dict, split: str) -> tuple[list[dict], list[dict]]:
    labeled, unreviewed = [], []
    for session, frame in et.iter_frames(index):
        state = et.annotation_state(frame.session_id, frame.frame_id, split)
        if state["has_label_file"] or state["has_metadata"]:
            labeled.append(state)
            if not state["reviewed"]:
                unreviewed.append(state)
    return labeled, unreviewed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="show label/review state (read-only)")
    ap.add_argument("--mark-reviewed", action="store_true",
                    help="promote every labeled-but-unreviewed frame")
    ap.add_argument("--unmark", type=int, action="append", default=None, metavar="FRAME_ID",
                    help="clear the review flag for these frame ids")
    ap.add_argument("--session", default=None, help="limit to one session id")
    ap.add_argument("--split", default=et.STAGING)
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args(argv)

    if not (args.list or args.mark_reviewed or args.unmark):
        ap.error("choose --list, --mark-reviewed or --unmark")

    et.ensure_layout()
    index = et.build_index()
    et.save_index(index)
    labeled, unreviewed = _summarize(index, args.split)

    if args.list:
        print(f"labeled frames: {len(labeled)} | reviewed: {len(labeled) - len(unreviewed)} "
              f"| awaiting review: {len(unreviewed)}\n")
        for s in labeled:
            if args.session and s["session_id"] != args.session:
                continue
            flag = "REVIEWED " if s["reviewed"] else "PENDING  "
            print(f"  {flag} {s['key']}  boxes={s['n_boxes']:<2} empty={str(s['empty']):<5}")
        return 0

    if args.mark_reviewed:
        targets = [s for s in unreviewed if not args.session or s["session_id"] == args.session]
        if not targets:
            print("nothing to promote: every labeled frame is already reviewed.")
            return 0
        print(f"{len(targets)} labeled frame(s) would be marked reviewed:")
        for s in targets[:20]:
            print(f"  {s['key']}  boxes={s['n_boxes']}")
        if len(targets) > 20:
            print(f"  ... and {len(targets) - 20} more")
        if not args.yes:
            reply = input("proceed? [y/N] ").strip().lower()
            if reply != "y":
                print("aborted; nothing changed.")
                return 1
        promoted = et.backfill_reviewed(index, args.split, args.session)
        print(f"\nmarked {len(promoted)} frame(s) reviewed. YOLO label files were not modified.")
        return 0

    for fid in args.unmark or []:
        state = et.set_reviewed(args.session, int(fid), False, args.split)
        print(f"cleared review flag for {state['key']} (boxes kept: {state['n_boxes']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
