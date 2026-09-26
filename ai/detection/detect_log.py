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

On top of that text log this module owns the *structured* diagnostic layer used
by the whole pipeline (camera -> frame -> yolo -> known -> unknown -> tracker ->
openclip -> attendance -> hazard -> alert/voice):

* :func:`event` appends a small dict to a bounded in-memory ring buffer. The
  buffer is what ``/api/detection/trace`` serves, so structured events cost
  **zero file I/O and zero JSON serialization** on the detection thread.
* :func:`stage` records a duration for one pipeline stage.
* :func:`stats` returns the compact block embedded in
  ``/api/detection/status``.

The two layers are one module with **two gates on purpose**, because their costs
are nothing alike:

* ``set_enabled`` / ``DETECT_LOG_ENABLED`` -> the legacy text log above. Cheap
  when off, ruinous when on (per-candidate lines in the YOLO decode hook).
* ``set_level`` / ``DETECT_TRACE_LEVEL`` -> the structured buffer and stage
  timings. In-memory only, change-triggered, and safe to leave on.

Merging them would mean that asking for ``yolo_ms`` also buys ~28ms/frame of
file writes, so they stay separately settable while sharing this emitter.
Every entry point returns on the first branch when its layer is off. Callers are
expected to invoke :func:`event` on *state changes* or a sampled cadence, never
per frame: this is a diagnostic layer and must never become part of the critical
detection path.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
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
#: Gate for the legacy verbose text log (per-candidate / per-frame file lines).
#: Defaults on so tests and one-off tracing keep working, exactly as before this
#: module grew a structured layer; ``DetectionService`` clears it from config.
_text_enabled = True
#: Gate for the structured ring buffer + stage timings.
_enabled = True

#: Verbosity ladder. Maps onto the stdlib levels the text emitter already uses,
#: so a level raises or lowers BOTH the text log and the structured buffer
#: instead of introducing a second, competing switch.
TRACE_OFF = "OFF"
TRACE_ERROR = "ERROR"
TRACE_WARN = "WARN"
TRACE_INFO = "INFO"
TRACE_DEBUG = "DEBUG"
TRACE_TRACE = "TRACE"

#: Higher number = more verbose. ``set_level`` clamps anything unknown to INFO.
TRACE_LEVELS: dict[str, int] = {
    TRACE_OFF: 0,
    TRACE_ERROR: 1,
    TRACE_WARN: 2,
    TRACE_INFO: 3,
    TRACE_DEBUG: 4,
    TRACE_TRACE: 5,
}
_DEFAULT_LEVEL = TRACE_DEBUG
_level = TRACE_LEVELS[_DEFAULT_LEVEL]

#: Structured event ring buffer. Bounded by construction: a long unattended run
#: cannot grow it without limit, and ``deque(maxlen=...)`` drops the oldest event
#: in O(1) so the cost per append is the same at 10 or 10_000 events.
TRACE_BUFFER_MAX = 500
TRACE_BUFFER_DEFAULT = 200
_EVENTS: deque[dict] = deque(maxlen=TRACE_BUFFER_DEFAULT)
_buffer_capacity = TRACE_BUFFER_DEFAULT

#: Latest duration per stage, plus a rolling count of events per second. Both are
#: fixed-size: no growth, no scanning, safe to read from an HTTP handler while the
#: detection thread writes.
_STAGES: dict[str, float] = {}
_events_total = 0
_events_window_started = time.perf_counter()
_events_window_count = 0
_events_per_second = 0.0
#: Number of times tracing itself raised. Must stay 0; anything else means the
#: diagnostic layer is silently broken, which is worse than having no trace.
_errors = 0
#: Counts how often each stage was recorded, so a stage that stopped running is
#: visible instead of silently reporting a stale duration forever.
_stage_counts: dict[str, int] = {}


def enabled() -> bool:
    """Is the legacy verbose text log writing?

    Unchanged pre-existing contract: ``ai/pipeline/yolo.py`` and
    ``test_model_config.py`` use this to skip the per-candidate decode sweep, so
    it must keep meaning "text logging", not "structured tracing". Use
    :func:`trace_enabled` for the ring buffer.
    """
    return _text_enabled


def trace_enabled() -> bool:
    """Is the structured ring buffer collecting? Cheap enough for hot paths."""
    return _enabled


def set_enabled(value: bool) -> None:
    """Gate the legacy verbose text log (unchanged pre-existing meaning).

    This is the switch documented above as expensive: it re-enables the
    per-candidate / per-frame lines in ``logs/detection_debug.log``. It is kept
    separate from the structured level on purpose — see :func:`set_level`.
    """
    global _text_enabled
    _text_enabled = bool(value)


def text_enabled() -> bool:
    """Is the legacy per-frame text log writing? Surfaced in :func:`stats`."""
    return _text_enabled


def set_trace_enabled(value: bool) -> None:
    """Gate structured collection without touching the text log or the level."""
    global _enabled
    _enabled = bool(value)


# --------------------------------------------------------------------- level


def set_level(level: str) -> None:
    """Set the structured-trace verbosity floor. ``OFF`` disables collection.

    Accepts the standard ladder case-insensitively; an unknown value falls back
    to INFO rather than raising, because a typo in an env var must not take the
    detector down.

    Deliberately does **not** re-enable the legacy text log. Coupling the two
    would mean asking for stage timings also switches on the per-candidate
    per-frame writes measured at ~28ms/frame (see the module docstring), which is
    exactly the cost structured tracing is supposed to avoid.
    """
    global _level, _enabled
    name = str(level or "").strip().upper()
    value = TRACE_LEVELS.get(name)
    if value is None:
        value = TRACE_LEVELS[TRACE_INFO]
    _level = value
    _enabled = value > TRACE_LEVELS[TRACE_OFF]


def get_level() -> str:
    """Current verbosity floor as an upper-case name."""
    for name, value in TRACE_LEVELS.items():
        if value == _level:
            return name
    return _DEFAULT_LEVEL


def level_enabled(level: str) -> bool:
    """Is an event at ``level`` verbose enough to be collected?"""
    if not _enabled:
        return False
    want = TRACE_LEVELS.get(str(level).strip().upper(), TRACE_LEVELS[TRACE_INFO])
    return want <= _level


# ------------------------------------------------------------------- buffer


def set_buffer_size(max_events: int) -> None:
    """Resize the ring buffer, keeping the most recent events.

    Rebuilds the deque so a smaller cap immediately drops the oldest history
    instead of letting the buffer stay oversized for the rest of the process.
    The cap is clamped to :data:`TRACE_BUFFER_MAX` — a typo in an env var must
    not turn a bounded diagnostic buffer into an unbounded memory leak.
    """
    global _EVENTS, _buffer_capacity
    try:
        requested = int(max_events)
    except (TypeError, ValueError):
        requested = TRACE_BUFFER_DEFAULT
    cap = max(0, min(requested, TRACE_BUFFER_MAX))
    with _LOCK:
        kept = list(_EVENTS)[-cap:] if cap else []
        _EVENTS = deque(kept, maxlen=cap)
        _buffer_capacity = cap


def clear() -> None:
    """Drop all buffered events and reset the per-second rate window."""
    global _events_total, _events_window_count, _events_window_started, _events_per_second
    with _LOCK:
        _EVENTS.clear()
        _events_total = 0
        _events_window_count = 0
        _events_window_started = time.perf_counter()
        _events_per_second = 0.0


def _rotate_event_window(now: float) -> None:
    """Roll the events/sec counter. Caller holds _LOCK."""
    global _events_window_started, _events_window_count, _events_per_second
    window = now - _events_window_started
    if window >= 1.0:
        _events_per_second = _events_window_count / window
        _events_window_count = 0
        _events_window_started = now


def _jsonable(value, _depth: int = 0):
    """Coerce a field to something FastAPI can serialise without a custom encoder.

    Nested boxes/collections stay structured instead of becoming ``"[0, 1, 2]"``:
    a trace is read by a human and by the panel, and a stringified bbox is
    useless to both. Depth is capped because a pathological object graph must
    never be able to make a trace call expensive.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if _depth >= 3:
        return repr(value)[:200]
    if isinstance(value, dict):
        return {str(k): _jsonable(v, _depth + 1) for k, v in list(value.items())[:32]}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v, _depth + 1) for v in list(value)[:32]]
    return str(value)[:200]


def event(event_type: str, *, level: str = TRACE_INFO, log: bool = True, **fields) -> bool:
    """Record one structured pipeline event into the bounded buffer.

    Returns True when the event was collected. Call this on state changes and
    sampled diagnostics — never once per frame per object.

    ``log=True`` additionally writes one compact human-readable line to the
    existing text log, but only for INFO and above, so the log file stays small
    while still carrying the significant transitions. The per-frame ``dbg``
    lines are unchanged.

    This function never raises. Tracing is a diagnostic layer: a failure here
    must not propagate into the detection thread, the attendance monitor or the
    hazard engine. Failures are counted and surfaced in :func:`stats` as
    ``errors`` so a broken tracer is *visible* rather than silently absent.
    """
    global _events_total, _events_window_count, _errors
    try:
        if not _enabled:
            return False
        want = TRACE_LEVELS.get(str(level).strip().upper(), TRACE_LEVELS[TRACE_INFO])
        if want > _level or _buffer_capacity <= 0:
            return False

        record = {
            "timestamp": int(time.time() * 1000),
            "event": str(event_type),
        }
        for key, value in fields.items():
            record[key] = _jsonable(value)

        now = time.perf_counter()
        with _LOCK:
            _EVENTS.append(record)
            _events_total += 1
            _events_window_count += 1
            _rotate_event_window(now)

        if log:
            # Only for the events that matter to a human reading the file. The
            # string is built here, never on the discard path: joining the record
            # for an event that will not be logged costs more than the append.
            detail = " ".join(
                f"{k}={v}" for k, v in record.items() if k not in ("timestamp", "event")
            )
            if want <= TRACE_LEVELS[TRACE_INFO]:
                dbg_info(event_type, detail)
            else:
                dbg(event_type, detail)
        return True
    except Exception:  # noqa: BLE001 - a tracer must never break its caller
        with _LOCK:
            _errors += 1
        return False


def stage(name: str, duration_ms: float) -> None:
    """Record the duration of one pipeline stage.

    ``duration_ms`` is produced by the caller from ``time.perf_counter()``, which
    costs ~50ns per call, so measuring is cheaper than the inference it wraps and
    is always safe to leave in place. Never raises, for the same reason as
    :func:`event`.
    """
    if not _enabled:
        return
    global _errors
    try:
        with _LOCK:
            _STAGES[name] = float(duration_ms)
            _stage_counts[name] = _stage_counts.get(name, 0) + 1
    except Exception:  # noqa: BLE001 - a tracer must never break its caller
        with _LOCK:
            _errors += 1


def recent(limit: int = 50) -> list[dict]:
    """Most recent events, newest last. Capped by the caller's limit."""
    if limit <= 0:
        return []
    with _LOCK:
        items = list(_EVENTS)
    return items[-limit:]


def stats() -> dict:
    """Compact, fixed-size diagnostics block for the status API.

    Deliberately contains no history: only latest durations and rates, so this
    can be embedded in a payload that is polled every second.
    """
    with _LOCK:
        _rotate_event_window(time.perf_counter())
        stages = dict(_STAGES)
        counts = dict(_stage_counts)
        per_second = _events_per_second
        total = _events_total
        buffered = len(_EVENTS)
        capacity = _buffer_capacity
        errors = _errors

    def _ms(key: str) -> float | None:
        value = stages.get(key)
        return round(value, 2) if value is not None else None

    return {
        "level": get_level(),
        "enabled": _enabled,
        # Reported separately so an operator can tell "structured trace is on"
        # from "the expensive per-frame file log is on".
        "textLogEnabled": _text_enabled,
        "bufferSize": buffered,
        "bufferCapacity": capacity,
        "eventsTotal": total,
        "eventsPerSecond": round(per_second, 1),
        # Non-zero means the tracer itself is broken. Surfaced rather than
        # swallowed so a silent diagnostic failure is visible in the UI.
        "errors": errors,
        # Named exactly as the pipeline stages, so the dashboard can render them
        # without knowing which ones are currently populated.
        "lastPipelineMs": _ms("total_ms"),
        "captureMs": _ms("capture_ms"),
        "yoloMs": _ms("yolo_ms"),
        "unknownDetectorMs": _ms("unknown_detector_ms"),
        "trackerMs": _ms("tracker_ms"),
        "openclipMs": _ms("openclip_ms"),
        "hazardMs": _ms("hazard_ms"),
        "stages": {k: counts.get(k, 0) for k in stages},
    }


def reset() -> None:
    """Drop buffered events, recorded stage durations and the error count."""
    global _events_total, _errors
    with _LOCK:
        _STAGES.clear()
        _stage_counts.clear()
        _errors = 0
    _events_total = 0
    clear()



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
    if not _text_enabled:
        return
    ensure_setup()
    _LOG.debug("[DETECT][%s] %s", tag, msg)


def dbg_info(tag: str, msg: str) -> None:
    """Info line: file + console."""
    if not _text_enabled:
        return
    ensure_setup()
    _LOG.info("[DETECT][%s] %s", tag, msg)


def dbg_warn(tag: str, msg: str) -> None:
    if not _text_enabled:
        return
    ensure_setup()
    _LOG.warning("[DETECT][%s] %s", tag, msg)


def dbg_error(tag: str, msg: str) -> None:
    if not _text_enabled:
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