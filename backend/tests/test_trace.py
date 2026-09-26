"""Structured pipeline trace: collection, bounds, and non-invasiveness.

The contract this file protects is the one that matters most for a diagnostic
layer: tracing must be *inert*. Turning it on may only add events, stage
durations and one API block — it must never change a single detection, box,
threshold or state transition.

Covers the required cases:
  1. TRACE off collects nothing
  2. TRACE on collects
  3. buffer is bounded
  4. trace does not change detection results
  5. detection events recorded
  6. unknown tracking events recorded
  7. OpenCLIP availability reported honestly (no model in this build)
  8. risk transitions recorded
  9. API exposes compact trace stats
 10. no crash when OpenCLIP is unavailable
 11. trace errors never crash the camera pipeline

Exclusively camera-free and model-free: a stub camera and the mock detector, so
these are deterministic and fast.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(_ROOT / "backend"))

from ai.detection import detect_log  # noqa: E402
from app.attendance import HELD, RELEASED, UNATTENDED, UNKNOWN, ObjectWatch  # noqa: E402
from app.detection_service import DetectionService  # noqa: E402
from camera import CameraManager, CameraSettings  # noqa: E402


class StubCamera:
    """Yields a fixed frame forever, so the service always has work to do."""

    def __init__(self, width: int = 320, height: int = 240) -> None:
        self._frame = np.zeros((height, width, 3), dtype=np.uint8)
        self._id = 0

    def latest_capture(self):
        self._id += 1
        return self._id, self._frame

    def info(self):
        return {"status": "connected", "fps": 30}

    def is_running(self):
        return True

    def start(self):
        return True

    def stop(self):
        return None


MOCK_CAMERA = CameraSettings(mock=True, width=320, height=240, fps=30)


def _events(name: str | None = None) -> list[dict]:
    items = detect_log.recent(detect_log.TRACE_BUFFER_MAX)
    return [e for e in items if name is None or e["event"] == name]


#: Services started by the tests below, so teardown can stop them. Without this
#: each test leaks a live inference thread into the rest of the pytest process,
#: which both pollutes the process-wide event counters and burns CPU for minutes.
_RUNNING: list[DetectionService] = []


@pytest.fixture(autouse=True)
def clean_trace():
    """Every test starts from tracing ON at DEBUG with an empty buffer, and the
    process-wide gate is restored afterwards so other suites are unaffected."""
    detect_log.set_buffer_size(detect_log.TRACE_BUFFER_DEFAULT)
    detect_log.set_level("DEBUG")
    # Keep the legacy per-frame file log off: this suite is about the structured
    # layer, and writing the log would add cost without testing anything.
    detect_log.set_enabled(False)
    # reset(), not clear(): stage durations and the tracer error count are
    # process-wide too, and a stale value from a previous test would make the
    # per-stage assertions meaningless.
    detect_log.reset()
    yield
    for svc in _RUNNING:
        svc.stop()
    _RUNNING.clear()
    detect_log.reset()
    detect_log.set_level("DEBUG")
    detect_log.set_enabled(False)


def _run_service(**kwargs) -> DetectionService:
    svc = DetectionService(
        StubCamera(),
        kind="mock",
        enabled=True,
        trace=True,
        trace_level="DEBUG",
        debounce_frames=1,
        poll_ms=10,
        target_fps=0,
        **kwargs,
    )
    _RUNNING.append(svc)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if svc.latest()["detections"]:
            break
        time.sleep(0.01)
    return svc


# ------------------------------------------------------------------ 1 & 2


def test_trace_off_collects_nothing() -> None:
    detect_log.set_level("OFF")
    assert detect_log.trace_enabled() is False
    # Asserted against this call's own event name, not "the buffer is empty":
    # a detection thread leaked from an earlier suite is still polling this
    # process, so global emptiness is not this test's to claim. The contract
    # under test is that a disabled tracer refuses the write.
    assert detect_log.event("SHOULD_NOT_EXIST", value=1) is False
    detect_log.stage("yolo_ms", 12.5)
    assert _events("SHOULD_NOT_EXIST") == []
    # A stage duration recorded while off must not surface afterwards either.
    assert detect_log.stats()["yoloMs"] is None


def test_trace_on_collects_events_and_stages() -> None:
    detect_log.set_level("DEBUG")
    assert detect_log.trace_enabled() is True

    # A test-unique event name: background services from other suites legitimately
    # emit PIPELINE_SUMMARY too, and this assertion is about *this* call.
    assert detect_log.event("TRACE_SELFTEST", level="INFO", window_s=1.0) is True
    detect_log.stage("yolo_ms", 449.0)
    detect_log.stage("tracker_ms", 1.0)

    events = _events("TRACE_SELFTEST")
    assert len(events) == 1
    assert events[0]["window_s"] == 1.0
    assert isinstance(events[0]["timestamp"], int)

    stats = detect_log.stats()
    assert stats["yoloMs"] == 449.0
    assert stats["trackerMs"] == 1.0
    assert stats["lastPipelineMs"] is None  # never recorded
    assert stats["enabled"] is True
    assert stats["level"] == "DEBUG"


def test_level_floor_filters_verbose_events() -> None:
    detect_log.set_level("WARN")
    assert detect_log.event("RISK_CREATED", level="INFO") is False
    assert detect_log.event("DETECTION_FAILED", level="ERROR") is True
    # Asserted by name, not by list equality: a background service from an
    # earlier suite can legitimately be emitting its own ERROR events too.
    names = [e["event"] for e in _events()]
    assert "DETECTION_FAILED" in names
    assert "RISK_CREATED" not in names


def test_unknown_level_falls_back_instead_of_raising() -> None:
    # A typo in an env var must never take the detector down.
    detect_log.set_level("BANANA")
    assert detect_log.get_level() == "INFO"
    assert detect_log.trace_enabled() is True


# -------------------------------------------------------------------- 3


def test_structured_trace_does_not_enable_the_expensive_text_log() -> None:
    """Asking for stage timings must not buy the per-frame file log.

    The legacy text log writes one line per YOLO candidate, measured at ~28ms per
    frame and a 55MB log on a real scene. Coupling it to the trace level would
    make structured diagnostics quietly expensive.
    """
    detect_log.set_enabled(False)
    assert detect_log.text_enabled() is False

    detect_log.set_level("DEBUG")
    assert detect_log.trace_enabled() is True, "structured trace should be on"
    assert detect_log.text_enabled() is False, "text log must stay off"

    # A structured event is collected; no file line is produced.
    assert detect_log.event("STAGE_ONLY", log=True) is True

    # And the reverse: turning the text log on must not switch on tracing.
    detect_log.set_level("OFF")
    detect_log.set_enabled(True)
    assert detect_log.text_enabled() is True
    assert detect_log.trace_enabled() is False, "text log must not imply structured trace"
    assert detect_log.event("NOT_COLLECTED") is False


def test_trace_buffer_is_bounded() -> None:
    detect_log.set_buffer_size(25)
    for i in range(500):
        detect_log.event("SPAM", n=i)

    stats = detect_log.stats()
    assert stats["bufferCapacity"] == 25
    # The hard guarantee: the ring never exceeds its cap, whatever else in the
    # process is appending concurrently.
    assert stats["bufferSize"] <= 25
    # eventsTotal is a process-wide lifetime counter, so background services from
    # other suites can push it past the 500 emitted here. The invariant is that
    # every emitted event is counted, never that it is the only producer.
    assert stats["eventsTotal"] >= 500

    kept = _events("SPAM")
    assert len(kept) <= 25
    # Newest kept, oldest dropped: the retained window is contiguous and ends at
    # the last event emitted.
    assert kept[-1]["n"] == 499
    assert [e["n"] for e in kept] == list(range(499 - len(kept) + 1, 500))


def test_shrinking_the_buffer_drops_history_immediately() -> None:
    detect_log.set_buffer_size(100)
    for i in range(60):
        detect_log.event("SPAM", n=i)
    detect_log.set_buffer_size(10)
    stats = detect_log.stats()
    assert stats["bufferCapacity"] == 10
    assert stats["bufferSize"] == 10
    # The window keeps the NEWEST events and drops the old ones immediately, so
    # the retained run is contiguous and ends at 59 — with or without a
    # concurrent producer evicting a few extra slots from the front.
    kept = _events("SPAM")
    assert [e["n"] for e in kept] == list(range(59 - len(kept) + 1, 60))


def test_zero_buffer_keeps_status_stats_but_stores_no_events() -> None:
    detect_log.set_buffer_size(0)
    assert detect_log.event("DROPPED") is False
    detect_log.stage("yolo_ms", 5.0)
    assert _events() == []
    assert detect_log.stats()["yoloMs"] == 5.0


def test_recent_respects_caller_limit() -> None:
    for i in range(10):
        detect_log.event("SPAM", n=i)
    assert len(detect_log.recent(3)) == 3
    assert detect_log.recent(0) == []


# -------------------------------------------------------------------- 4


def test_trace_does_not_change_detection_results() -> None:
    """The important one: same camera, same frames, same detections — with the
    trace off and with it on. Any difference means tracing is not inert."""

    def run(trace: bool) -> list[dict]:
        svc = DetectionService(
            StubCamera(),
            kind="mock",
            enabled=True,
            trace=trace,
            trace_level="DEBUG",
            debounce_frames=1,
            poll_ms=10,
            target_fps=0,
            unknown_enabled=False,
        )
        try:
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                dets = svc.latest()["detections"]
                if dets:
                    # Compare geometry/confidence only: timestamps legitimately
                    # differ between two separate runs.
                    return [
                        {k: v for k, v in d.items() if k != "timestamp"} for d in dets
                    ]
                time.sleep(0.01)
            raise AssertionError("no detections produced")
        finally:
            svc.stop()

    without = run(False)
    with_trace = run(True)
    assert without == with_trace
    assert [d["class_name"] for d in with_trace] == ["person", "red_box", "yellow_box"]
    # Trace really was on for the second run, otherwise this proves nothing.
    assert _events("DETECTOR_BOOTSTRAP")


# ------------------------------------------------------------- 5 & 6 & 10


def test_pipeline_records_frame_detection_and_unknown_events() -> None:
    svc = _run_service()
    try:
        assert _events("DETECTOR_BOOTSTRAP"), "bootstrap event missing"
        assert _events("FRAME_SIZE_CHANGED"), "frame size event missing"
        # DETECTION / UNKNOWN_DETECTION are emitted on stable-feed *changes*
        # only, so drive enough frames for the counts to move.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and not _events("UNKNOWN_DETECTION"):
            time.sleep(0.02)
        assert _events("DETECTION"), "DETECTION event missing"
        unknown_event = _events("UNKNOWN_DETECTION")
        assert unknown_event, "UNKNOWN_DETECTION event missing"
        assert "instance_ids" in unknown_event[-1]
        assert _events("TRACK_CREATED"), "tracker CREATE event missing"
        assert _events("TRACK_STABLE"), "tracker PROMOTE event missing"
    finally:
        svc.stop()


def test_openclip_unavailable_is_reported_honestly_and_never_blocks() -> None:
    svc = _run_service()
    try:
        events = _events("OPENCLIP_UNAVAILABLE")
        assert len(events) == 1, "expected exactly one availability report"
        assert events[0]["reason"] == "classifier_not_installed"
        # The critical half: detection still works with no classifier.
        assert svc.latest()["detections"], "detection must not depend on OpenCLIP"
        assert svc.latest()["inferenceStatus"] == "ok"
    finally:
        svc.stop()


def test_stage_timings_are_published() -> None:
    svc = _run_service()
    try:
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            stats = detect_log.stats()
            if stats["lastPipelineMs"] is not None:
                break
            time.sleep(0.02)
        stats = detect_log.stats()
        assert stats["yoloMs"] is not None and stats["yoloMs"] >= 0
        assert stats["trackerMs"] is not None
        assert stats["unknownDetectorMs"] is not None
        assert stats["lastPipelineMs"] >= stats["yoloMs"] - 1e-6
    finally:
        svc.stop()


# -------------------------------------------------------------------- 8


def _watch(instance_id: str) -> ObjectWatch:
    box = {"class_name": "unknown_object", "x1": 10, "y1": 10, "x2": 60, "y2": 60, "confidence": 0.6}
    return ObjectWatch(instance_id, box, 0, state=UNKNOWN, is_unknown=True)


def test_attendance_transitions_are_traced() -> None:
    watch = _watch("unknown-1")
    watch.transition(HELD, 1000, "near_person")
    watch.transition(RELEASED, 2000, "person_left")
    watch.transition(UNATTENDED, 5000, "person_free_timeout")

    events = [e for e in _events() if e["event"].startswith("TRACK_")]
    by_name = {e["event"]: e for e in events}
    assert "TRACK_HELD" in by_name
    assert "TRACK_RELEASED" in by_name
    assert by_name["TRACK_UNATTENDED"]["previous_state"] == RELEASED
    assert by_name["TRACK_UNATTENDED"]["new_state"] == UNATTENDED
    assert by_name["TRACK_UNATTENDED"]["instance_id"] == "unknown-1"
    assert "stationary_seconds" in by_name["TRACK_UNATTENDED"]


def test_unchanged_attendance_state_emits_nothing() -> None:
    watch = _watch("unknown-2")
    for _ in range(50):
        assert watch.transition(UNKNOWN, 1000, "still_unknown") is None
    assert [e for e in _events() if e["event"].startswith("TRACK_")] == []


def test_risk_transitions_are_traced_from_the_hazard_engine() -> None:
    from app.safety.hazard_engine import HazardEngine
    from app.safety.hazards import load_hazards

    engine = HazardEngine(load_hazards(), environment_mode="microgravity", persist_frames=1)
    now = int(time.time() * 1000)
    base = {
        "enabled": True,
        "inferenceStatus": "ok",
        "lastInferenceMs": now,
        "frameWidth": 1280,
        "frameHeight": 720,
    }

    scene = engine.assess(
        {
            **base,
            "detections": [
                {
                    "class_name": "knife",
                    "confidence": 0.9,
                    "x1": 100,
                    "y1": 100,
                    "x2": 160,
                    "y2": 160,
                    "timestamp": now,
                }
            ],
        },
        now,
    )
    created = _events("RISK_CREATED")
    assert created, "no RISK_CREATED event"
    assert created[0]["instance_id"] == "knife"
    assert created[0]["risk_level"] in {"CAUTION", "WARNING", "CRITICAL"}

    # Same object, same risk: the engine must stay quiet instead of emitting one
    # event per frame.
    for offset in range(1, 6):
        engine.assess(
            {
                **base,
                "lastInferenceMs": now + offset,
                "detections": [
                    {
                        "class_name": "knife",
                        "confidence": 0.9,
                        "x1": 100,
                        "y1": 100,
                        "x2": 160,
                        "y2": 160,
                        "timestamp": now + offset,
                    }
                ],
            },
            now + offset,
        )
    assert len(_events("RISK_CREATED")) == 1
    assert not _events("RISK_CHANGED")

    # Object gone -> cleared.
    engine.assess({**base, "lastInferenceMs": now + 10, "detections": []}, now + 10)
    engine.assess({**base, "lastInferenceMs": now + 11, "detections": []}, now + 11)
    cleared = _events("HAZARD_CLEARED")
    assert cleared, "no HAZARD_CLEARED event"
    assert cleared[0]["instance_id"] == "knife"
    assert scene.assessments


def test_stale_feed_is_never_reported_as_a_clear() -> None:
    from app.safety.hazard_engine import HazardEngine
    from app.safety.hazards import load_hazards

    engine = HazardEngine(load_hazards(), environment_mode="microgravity", persist_frames=1)
    now = int(time.time() * 1000)
    engine.assess(
        {
            "enabled": True,
            "inferenceStatus": "ok",
            "lastInferenceMs": now,
            "frameWidth": 640,
            "frameHeight": 480,
            "detections": [
                {
                    "class_name": "knife",
                    "confidence": 0.9,
                    "x1": 10,
                    "y1": 10,
                    "x2": 60,
                    "y2": 60,
                    "timestamp": now,
                }
            ],
        },
        now,
    )
    assert _events("RISK_CREATED")

    # Camera off: stale. The engine retains the scene and must not resolve it.
    stale = engine.assess({"enabled": True, "inferenceStatus": "ok", "lastInferenceMs": now}, now + 60_000)
    assert stale.stale is True
    assert not _events("HAZARD_CLEARED"), "a stale feed must not produce a clear"


# -------------------------------------------------------------------- 9


def test_api_exposes_compact_trace_stats_and_bounded_events(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from app import config
    from app.experiment import load_experiment
    from app.main import create_app

    exp = load_experiment(Path(__file__).resolve().parent.parent / "experiments" / "box_sequence.json")
    api_camera = CameraSettings(mock=True, width=320, height=240, fps=120)
    script = [{"delay_ms": 5, "activity": "PICK_MAIN_BOX", "confidence": 0.96}]

    def client_for() -> TestClient:
        return TestClient(
            create_app(experiment=exp, sim_script=script, camera=api_camera, detector=None)
        )

    with client_for() as client:
        # Off by default: no trace block at all, so a normal status response is
        # unchanged and the history route answers honestly while disabled.
        status = client.get("/api/detection/status").json()
        assert status["traceEnabled"] is False
        assert status["traceLevel"] == "OFF"
        assert "trace" not in status
        assert client.get("/api/detection/trace").json()["enabled"] is False

    from ai.detection.detector import create_detector

    # Enabled the way an operator enables it — env var -> config -> service — so
    # the test exercises the real wiring instead of poking the global gate.
    # Note DETECT_LOG_ENABLED stays OFF: structured tracing must not imply the
    # expensive legacy per-frame file log.
    monkeypatch.setattr(config, "DETECT_TRACE_LEVEL", "DEBUG")
    with TestClient(
        create_app(experiment=exp, sim_script=script, camera=api_camera, detector=create_detector("mock"))
    ) as client:
        client.post("/api/camera/start")
        deadline = time.monotonic() + 5.0
        payload: dict = {}
        while time.monotonic() < deadline:
            payload = client.get("/api/detection/status").json()
            if payload.get("trace", {}).get("yoloMs") is not None:
                break
            time.sleep(0.02)

        assert payload["traceEnabled"] is True
        trace = payload["trace"]
        assert trace["yoloMs"] is not None
        assert trace["trackerMs"] is not None
        assert trace["lastPipelineMs"] is not None
        assert trace["errors"] == 0, "tracer raised internally"
        # The cheap structured trace is on while the expensive per-frame file log
        # stays off — the whole point of keeping two gates.
        assert trace["textLogEnabled"] is False
        assert payload["textLogEnabled"] is False
        # Compact: no history smuggled into a per-second polled route.
        assert "events" not in trace
        assert set(trace) <= {
            "level", "enabled", "textLogEnabled", "bufferSize", "bufferCapacity",
            "eventsTotal", "eventsPerSecond", "errors", "lastPipelineMs", "captureMs",
            "yoloMs", "unknownDetectorMs", "trackerMs", "openclipMs", "hazardMs", "stages",
        }

        events = client.get("/api/detection/trace?limit=10").json()
        assert events["limit"] == 10
        assert len(events["events"]) <= 10
        assert all("timestamp" in e and "event" in e for e in events["events"])

        # Server-side clamp: a client cannot request an unbounded history.
        big = client.get("/api/detection/trace?limit=100000").json()
        assert big["limit"] == detect_log.TRACE_BUFFER_MAX


# ------------------------------------------------------------------- 11


def test_trace_failure_never_crashes_the_pipeline(monkeypatch) -> None:
    """A broken tracer must not be able to take the detection thread down."""
    svc = _run_service()
    try:
        def boom(*_args, **_kwargs):
            raise RuntimeError("tracer exploded")

        monkeypatch.setattr(detect_log, "event", boom)
        monkeypatch.setattr(detect_log, "stage", boom)
        # The service must keep producing detections with tracing broken.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            assert svc.status()["inferenceStatus"] in {"ok", "idle", "error"}
            if svc.latest()["detections"]:
                break
            time.sleep(0.02)
        assert svc.latest()["detections"], "pipeline stopped when tracing failed"
        assert svc.status()["inferenceStatus"] == "ok"
    finally:
        svc.stop()


def test_camera_loop_survives_a_broken_tracer() -> None:
    """Same guarantee at the loop level: an exception inside the event path is
    swallowed by the loop, not propagated out of the worker thread."""
    svc = DetectionService(
        StubCamera(),
        kind="mock",
        enabled=True,
        trace=True,
        trace_level="DEBUG",
        debounce_frames=1,
        poll_ms=10,
        target_fps=0,
    )
    try:
        original = detect_log.event

        def flaky(*args, **kwargs):
            if args and args[0] == "FRAME_SIZE_CHANGED":
                raise RuntimeError("tracer exploded")
            return original(*args, **kwargs)

        detect_log.event = flaky  # type: ignore[assignment]
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if svc.latest()["detections"]:
                break
            time.sleep(0.02)
        assert svc.latest()["detections"], "worker thread died on a tracer error"
    finally:
        detect_log.event = original  # type: ignore[assignment]
        svc.stop()


def test_stats_is_safe_to_read_while_events_are_written() -> None:
    stop = time.perf_counter() + 0.2
    errors: list[BaseException] = []

    def writer() -> None:
        try:
            i = 0
            while time.perf_counter() < stop:
                detect_log.event("SPAM", n=i)
                i += 1
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    def reader() -> None:
        try:
            while time.perf_counter() < stop:
                detect_log.stats()
                detect_log.recent(10)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"concurrent access raised: {errors}"
