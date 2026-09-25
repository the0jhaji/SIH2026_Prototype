"""Dedicated [DETECT][...] observability emitter for the detection pipeline.

Pure stdlib so both the backend venv and the ``ai/`` venv can use it without
coupling to FastAPI. Writes timestamped DEBUG lines to ``logs/detection_debug.log``
and echoes INFO+ to the console. Observability only — nothing here changes how
any detector or downstream module behaves.

Tracing is OFF by default at the *runtime* seam (``DetectionService`` clears the
gate from config) because the YOLO decode hook logs one line per candidate above a
logging floor: on a real scene that is ~40-100 flushed writes per frame, two models
per frame in ``dual`` mode, which measured 28ms/frame on its own and grew the log
to 55MB. The gate is a single bool so the disabled path costs one branch, and
callers that gate a whole hot loop (the decode candidate sweep) pay nothing at all.
Tests and one-off tracing keep the default-on behaviour.

The module-level counters let per-stage logs accumulated in the YOLO decode
layer (raw boxes seen, accepted, confidence-rejected, unknown) be surfaced as
the per-second [DETECT][SUMMARY] line by the DetectionService, which consumes
them with ``take_counters()`` (single writer: the detection thread).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

_LOGGER_NAME = "astraai.detect_debug"
_LOG = logging.getLogger(_LOGGER_NAME)
_LOCK = threading.Lock()
_COUNTERS = {
    "raw": 0,
    "accepted": 0,
    "rejected_confidence": 0,
    "unknown": 0,
}
_setup_done = False
#: Runtime gate. True keeps the historical always-on tracing behaviour (tests,
#: one-off debugging); the backend DetectionService clears it from config so
#: normal operation pays one branch per call and writes no log at all.
_enabled = True


def enabled() -> bool:
    """Single-bool gate for hot tracing paths. Cheap enough for per-candidate use."""
    return _enabled


def set_enabled(value: bool) -> None:
    """Turn tracing on/off at runtime. Idempotent; no handlers are removed."""
    global _enabled
    _enabled = bool(value)


class _FileFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        import time

        con = self.converter(record.created)
        if datefmt:
            base = time.strftime(datefmt, con)
            return f"{base}.{int(record.msecs):03d}"
        return super().formatTime(record, datefmt)


def _root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def ensure_setup(root: Path | None = None, log_file: Path | None = None) -> Path:
    """Idempotently attach the file + console handlers. Returns the file path."""
    global _setup_done
    if _LOG.handlers and _setup_done:
        return log_file or (_root() / "logs" / "detection_debug.log")
    with _LOCK:
        if _LOG.handlers and _setup_done:
            return log_file or (_root() / "logs" / "detection_debug.log")
        root = Path(root) if root is not None else _root()
        target = Path(log_file) if log_file is not None else (root / "logs" / "detection_debug.log")
        (root / "logs").mkdir(parents=True, exist_ok=True)
        _LOG.setLevel(logging.DEBUG)
        _LOG.propagate = False
        try:
            fh = logging.FileHandler(str(target), encoding="utf-8")
        except OSError:
            # Another live process already holds the file (detection debug log is
            # observability — never crash a worker/test over it). Fall back to a
            # pid-suffixed file so tracing keeps working.
            import os

            target = target.with_name(f"detection_debug.{os.getpid()}.log")
            fh = logging.FileHandler(str(target), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(_FileFormatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"))
        _LOG.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(logging.Formatter("%(message)s"))
        _LOG.addHandler(ch)
        _setup_done = True
        return target


def dbg(tag: str, msg: str) -> None:
    """File-only DEBUG line (not echoed to console)."""
    if not _enabled:
        return
    ensure_setup()
    _LOG.debug("[DETECT][%s] %s", tag, msg)


def dbg_info(tag: str, msg: str) -> None:
    """Info line: file + console."""
    if not _enabled:
        return
    ensure_setup()
    _LOG.info("[DETECT][%s] %s", tag, msg)


def dbg_warn(tag: str, msg: str) -> None:
    if not _enabled:
        return
    ensure_setup()
    _LOG.warning("[DETECT][%s] %s", tag, msg)


def dbg_error(tag: str, msg: str) -> None:
    if not _enabled:
        return
    ensure_setup()
    _LOG.error("[DETECT][%s] %s", tag, msg)


def bump(key: str, n: int = 1) -> None:
    with _LOCK:
        _COUNTERS[key] = _COUNTERS.get(key, 0) + n


def take_counters() -> dict:
    """Snapshot + reset the per-stage counters (for the 1s SUMMARY line)."""
    with _LOCK:
        snap = dict(_COUNTERS)
        for k in _COUNTERS:
            _COUNTERS[k] = 0
    return snap