"""Local browser-based annotation server for the BAS dataset (Phase 4B).

Runs a small stdlib-only HTTP server (no FastAPI, no Flask, no new deps). It
serves the annotator UI and a tiny JSON API over ``dataset/raw`` +
``dataset/annotations``. Everything stays on this machine.

Run from the repo root (backend venv reuses the same Python):

    .venv\\Scripts\\python.exe dataset\\annotation\\app.py
    # then open http://127.0.0.1:8700

Roughly 2x simpler and fully independent of the production BAS app.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, unquote, urlparse

try:  # direct run: python dataset/annotation/app.py
    from annotator import (  # noqa: F401
        YoloBox,
        class_color,
        image_relpaths,
        is_annotated,
        label_rel,
        load_classes,
        parse_label,
        rel_to_path,
        serialize_label,
        validate_boxes_for_save,
    )
except ImportError:  # imported as annotation.app
    from annotation.annotator import (  # noqa: F401
        YoloBox,
        class_color,
        image_relpaths,
        is_annotated,
        label_rel,
        load_classes,
        parse_label,
        rel_to_path,
        serialize_label,
        validate_boxes_for_save,
    )

ANNOTATION_DIR = Path(__file__).resolve().parent
DATASET_DIR = ANNOTATION_DIR.parent
TEMPLATES_DIR = ANNOTATION_DIR / "templates"
STATIC_DIR = ANNOTATION_DIR / "static"

RAW_DIR = DATASET_DIR / "raw"
ANN_DIR = DATASET_DIR / "annotations"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


class AnnotatorHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "BASAnnotator/1.0"

    # ------------------------------------------------------------ helpers
    def _reply(self, code: int, payload: bytes, ctype: str, *, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _json(self, code: int, payload) -> None:
        self._reply(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _error(self, code: int, message: str) -> None:
        self._json(code, {"ok": False, "error": message})

    def _image_rel(self, query: dict[str, list[str]]) -> str | None:
        raw = (query.get("path") or [""])[0]
        rel = unquote(raw).strip()
        try:
            path = rel_to_path(RAW_DIR, rel)
        except ValueError:
            return None
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            return None
        return rel

    def _read_body(self, limit: int = 1_000_000) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > limit:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    # --------------------------------------------------------------- routes
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            index = TEMPLATES_DIR / "index.html"
            if index.is_file():
                self._reply(200, index.read_bytes(), MIME[".html"])
            else:
                self._error(500, "templates/index.html missing")
            return
        if path.startswith("/static/"):
            rel = Path(*PurePosixPath(path[len("/static/") :]).parts)
            target = (STATIC_DIR / rel).resolve()
            if not target.is_relative_to(STATIC_DIR.resolve()) or not target.is_file():
                self._error(404, "not found")
                return
            self._reply(200, target.read_bytes(), MIME.get(target.suffix.lower(), "application/octet-stream"))
            return
        if path == "/api/config":
            classes = load_classes()
            self._json(200, {"classes": classes, "colors": [class_color(i) for i in range(len(classes))]})
            return
        if path == "/api/images":
            images = [
                {"path": rel, "annotated": is_annotated(RAW_DIR, ANN_DIR, rel)}
                for rel in image_relpaths(RAW_DIR)
            ]
            total = len(images)
            annotated = sum(1 for img in images if img["annotated"])
            self._json(
                200,
                {
                    "images": images,
                    "stats": {
                        "total": total,
                        "annotated": annotated,
                        "percent": round(100 * annotated / total) if total else 0,
                    },
                },
            )
            return
        if path == "/api/image":
            rel = self._image_rel(query)
            if rel is None:
                self._error(404, "image not found")
                return
            path = rel_to_path(RAW_DIR, rel)
            self._reply(200, path.read_bytes(), MIME.get(path.suffix.lower(), "application/octet-stream"))
            return
        if path == "/api/annotation":
            rel = self._image_rel(query)
            if rel is None:
                self._error(404, "image not found")
                return
            label_path = rel_to_path(ANN_DIR, label_rel(rel))
            boxes = []
            if label_path.is_file():
                boxes = [box.to_dict() for box in parse_label(label_path.read_text(encoding="utf-8"))]
            self._json(200, {"path": rel, "boxes": boxes})
            return
        self._error(404, f"unknown route {path}")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/annotation":
            self._error(404, f"unknown route {parsed.path}")
            return
        body = self._read_body()
        if not body or "path" not in body or "boxes" not in body:
            self._error(400, "expected JSON body with {path, boxes}")
            return
        rel = str(body["path"]).strip()
        try:
            rel_to_path(RAW_DIR, rel)
        except ValueError:
            self._error(400, "unsafe image path")
            return
        if rel not in image_relpaths(RAW_DIR):
            self._error(404, f"image not found in raw/ : {rel}")
            return

        classes = load_classes()
        errors = validate_boxes_for_save(body["boxes"], classes)
        if errors:
            self._error(400, "; ".join(errors))
            return

        boxes = [YoloBox(int(b["class_id"]), float(b["cx"]), float(b["cy"]), float(b["w"]), float(b["h"])) for b in body["boxes"]]
        label_path = rel_to_path(ANN_DIR, label_rel(rel))
        label_path.parent.mkdir(parents=True, exist_ok=True)
        label_path.write_text(serialize_label(boxes), encoding="utf-8")
        self._json(200, {"ok": True, "saved": len(boxes)})

    # ------------------------------------------------------------- logging
    def log_message(self, format, *args) -> None:
        return  # keep the console quiet (the banner printed by main() suffices)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local BAS dataset annotation server")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8700, help="port (default 8700)")
    parser.add_argument(
        "--root", default=str(DATASET_DIR), help="dataset root (contains raw/ and annotations/)"
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser")
    args = parser.parse_args(argv)

    global RAW_DIR, ANN_DIR
    DATA_ROOT = Path(args.root).resolve()
    RAW_DIR = DATA_ROOT / "raw"
    ANN_DIR = DATA_ROOT / "annotations"
    for d in (RAW_DIR, ANN_DIR):
        d.mkdir(parents=True, exist_ok=True)

    httpd = ThreadingHTTPServer((args.host, args.port), AnnotatorHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"BAS annotation tool running at {url}")
    print(f"  images:      {RAW_DIR}")
    print(f"  annotations: {ANN_DIR}")
    print("  stop with Ctrl+C; 'Q' closes the browser tab (Esc also works)")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()