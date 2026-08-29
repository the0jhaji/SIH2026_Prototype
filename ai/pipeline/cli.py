"""Preview CLI for the perception pipeline.

Runs independently of FastAPI (requirement 9) — the whole ai kit can be
exercised, previewed, and unit-tested without a web server:

    python -m pipeline.cli --detector mock               # live preview window
    python -m pipeline.cli --detector mock --source null  # no camera needed
    python -m pipeline.cli --detector yolo                # needs models/yolo/*.onnx
"""

from __future__ import annotations

import argparse
import json
import threading

import cv2

from .annotate import draw_detections
from .interaction import InteractionTracker, MockScene
from .mock import MockDetector
from .pipeline import CameraPipeline
from .webcam import NullSource, WebcamSource
from .yolo import YoloDetector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BAS-AI perception pipeline preview")
    parser.add_argument("--detector", choices=["mock", "yolo"], default="mock")
    parser.add_argument("--model", default="yolov8n.onnx", help="YOLO ONNX filename in models/yolo/ (or absolute)")
    parser.add_argument("--source", choices=["webcam", "null"], default="webcam")
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--headless", action="store_true", help="no preview window")
    parser.add_argument("--no-annotate", action="store_true")
    parser.add_argument("--print-detections", action="store_true", help="emit JSON lines to stdout")
    parser.add_argument("--use-cuda", action="store_true")
    parser.add_argument(
        "--interaction",
        action="store_true",
        help="drive the hand/object interaction demo (no camera, no model)",
    )
    return parser


def _run_interaction(args: argparse.Namespace) -> int:
    import time

    from .interaction.demo import MockScene

    scene = MockScene()
    tracker = InteractionTracker()
    stop = threading.Event()
    frame_size = (args.width, args.height)
    frames = args.max_frames or 140
    for frame_idx in range(frames):
        if stop.is_set():
            break
        detections, hands = scene.step(frame_size)
        ts = int((frame_idx + 1) * 33)
        events = tracker.update(detections, hands, frame_size, ts)
        if args.print_detections:
            payload = {
                "frame": frame_idx,
                "timestamp": ts,
                "detections": [d.to_dict() for d in detections],
                "events": [e.to_dict() for e in events],
            }
            print(json.dumps(payload), flush=True)
        if not args.headless:
            canvas = draw_detections(_blank(args.width, args.height), detections)
            for hand in hands:
                for i in (4, 8, 12, 16, 20):
                    lm = hand.landmarks[i]
                    cv2.circle(
                        canvas,
                        (int(lm.x * args.width), int(lm.y * args.height)),
                        4,
                        (0, 255, 255),
                        -1,
                    )
            cv2.imshow("BAS-AI interaction preview", canvas)
            if cv2.waitKey(1) & 0xFF == 27:
                stop.set()
    cv2.destroyAllWindows()
    return 0


def _blank(width: int, height: int):
    import numpy as np

    return np.full((height, width, 3), 16, dtype=np.uint8)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.interaction:
        return _run_interaction(args)

    if args.source == "null":
        source: cv2.VideoCapture | object = NullSource(args.width, args.height)
    else:
        source = WebcamSource(args.camera, width=args.width, height=args.height)

    if args.detector == "mock":
        detector = MockDetector()
    else:
        detector = YoloDetector(
            model_path=args.model,
            use_cuda=args.use_cuda,
        )

    stop = threading.Event()

    def on_frame(df) -> None:
        if args.print_detections:
            print(
                json.dumps(
                    {
                        "frame": df.frame_index,
                        "timestamp": df.timestamp,
                        "detections": [d.to_dict() for d in df.detections],
                    }
                ),
                flush=True,
            )
        if not args.headless and df.annotated is not None:
            cv2.imshow(f"BAS-AI perception preview ({detector.name})", df.annotated)
            if cv2.waitKey(1) & 0xFF == 27:  # ESC
                stop.set()

    pipeline = CameraPipeline(source, detector, annotate=not args.no_annotate)
    try:
        pipeline.run(on_frame, stop_event=stop, max_frames=args.max_frames)
    except (RuntimeError, FileNotFoundError) as err:
        print(f"pipeline error: {err}")
        return 2
    finally:
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())