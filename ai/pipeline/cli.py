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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

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