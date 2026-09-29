"""Voice lifecycle: NOT_STARTED -> STARTING -> READY | ERROR, driven by start().

The bug this guards: the worker used to be spawned from `__init__`, so the
service reported a health string ("initializing"/"ok") that no caller had asked
for, and "ENGINE START" started the experiment but not the voice worker. A
dashboard that renders `voice ok` for a service nobody started is a dashboard
that cannot be wrong about anything else either.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import voice_alert as va  # noqa: E402
from app.voice_alert import (  # noqa: E402
    VOICE_ERROR,
    VOICE_NOT_STARTED,
    VOICE_READY,
    VOICE_STARTING,
    VOICE_STATES,
    VoiceAlertService,
)


class _FakeEngine:
    """Minimal pyttsx3 stand-in; `init` can be made to fail per-test."""

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.stopped = False

    def setProperty(self, key, value):  # noqa: N802 - pyttsx3 API
        return None

    def say(self, message):
        self.spoken.append(message)

    def runAndWait(self):  # noqa: N802 - pyttsx3 API
        return None

    def stop(self):
        self.stopped = True


def test_construction_does_not_start_a_worker():
    v = VoiceAlertService()
    assert v.state == VOICE_NOT_STARTED
    assert v._worker is None
    assert not v.status()["ready"]
    v.close()


def test_start_reaches_ready_and_is_the_only_thing_that_starts_it():
    v = VoiceAlertService()
    engine = _FakeEngine()
    with patch.object(va, "pyttsx3", MagicMock(init=lambda: engine)):
        st = v.start()
    assert st["state"] == VOICE_READY
    assert st["ready"] is True
    assert st["error"] is None
    assert v._worker is not None and v._worker.name == "voice-tts"
    v.close()


def test_start_is_idempotent_and_does_not_spawn_a_second_worker():
    v = VoiceAlertService()
    engine = _FakeEngine()
    with patch.object(va, "pyttsx3", MagicMock(init=lambda: engine)):
        v.start()
        first = v._worker
        v.start()
        assert v._worker is first
        assert v.state == VOICE_READY
    v.close()


def test_init_failure_reports_error_with_the_real_reason():
    v = VoiceAlertService()

    def boom():
        raise RuntimeError("no SAPI5 voice installed")

    with patch.object(va, "pyttsx3", MagicMock(init=boom)):
        st = v.start()
    assert st["state"] == VOICE_ERROR
    assert st["ready"] is False
    assert "no SAPI5 voice installed" in st["error"]
    v.close()


def test_pyttsx3_missing_is_error_not_silent_no_op():
    v = VoiceAlertService()
    with patch.object(va, "_TTS_AVAILABLE", False):
        st = v.start()
    assert st["state"] == VOICE_ERROR
    assert "pyttsx3" in st["error"]
    v.close()


def test_configured_disabled_is_error_not_ready():
    v = VoiceAlertService(enabled=False)
    st = v.start()
    assert st["state"] == VOICE_ERROR
    assert "disabled by configuration" in st["error"]
    assert st["configured"] is False
    v.close()


def test_speak_before_start_is_ignored_rather_than_lost_silently_as_ok():
    """A queued message before start must not be spoken by a later start."""
    v = VoiceAlertService()
    v.speak("must not be spoken", key="k")
    assert v.queue_size == 0
    engine = _FakeEngine()
    with patch.object(va, "pyttsx3", MagicMock(init=lambda: engine)):
        v.start()
        time.sleep(0.3)
    assert engine.spoken == []
    v.close()


def test_speak_after_ready_is_spoken():
    v = VoiceAlertService()
    engine = _FakeEngine()
    with patch.object(va, "pyttsx3", MagicMock(init=lambda: engine)):
        v.start()
        v.speak("hello", key="greeting")
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and not engine.spoken:
            time.sleep(0.02)
    assert "hello" in engine.spoken
    v.close()


def test_every_reported_state_is_in_the_renderable_vocabulary():
    """The UI may only ever render these four; nothing else may leak out."""
    seen = {
        VoiceAlertService().state,
    }
    v = VoiceAlertService()
    seen.add(v.state)
    with patch.object(va, "pyttsx3", MagicMock(init=lambda: _FakeEngine())):
        seen.add(v.start()["state"])
    v.close()
    for st in seen:
        assert st in VOICE_STATES, st


def test_close_returns_to_not_started_and_is_safe_when_never_started():
    v = VoiceAlertService()
    v.close()
    assert v.state == VOICE_NOT_STARTED
    v.close()  # idempotent


def test_starting_is_observable_before_ready(monkeypatch):
    """STARTING must be a real, reachable state — not a dead label."""
    release = __import__("threading").Event()

    def slow_init():
        release.wait(timeout=3.0)
        return _FakeEngine()

    v = VoiceAlertService()
    orig = VoiceAlertService.start

    def start_and_peek(**kwargs):
        import threading as th

        def runner():
            try:
                orig(v, **kwargs)
            finally:
                release.set()

        th.Thread(target=runner, daemon=True).start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and v.state != VOICE_STARTING:
            time.sleep(0.01)
        return v.status()

    with patch.object(va, "pyttsx3", MagicMock(init=slow_init)):
        st = start_and_peek()
    release.set()
    assert st["state"] == VOICE_STARTING
    assert st["ready"] is False
    v.close()


def test_snapshot_reports_voice_state_independently_of_engine_state():
    """A RUNNING experiment must not imply a READY voice worker."""
    from app.experiment_state import ExperimentStateEngine
    from app.schemas import ExperimentDef, StepDef

    exp = ExperimentDef(
        id="voice-test",
        name="Voice test",
        description="d",
        steps=[StepDef(id="s1", activity="APPROACH", label="Approach")],
    )
    v = VoiceAlertService()
    eng = ExperimentStateEngine(exp, voice=v)
    snap = eng.snapshot()
    assert snap["status"] == "NOT_STARTED"
    assert snap["voice"]["state"] == VOICE_NOT_STARTED
    assert snap["voice"]["ready"] is False
    v.close()


def test_engine_start_starts_the_voice_worker():
    from app.experiment_state import ExperimentStateEngine
    from app.schemas import ExperimentDef, StepDef

    exp = ExperimentDef(
        id="voice-start",
        name="Voice start",
        description="d",
        steps=[StepDef(id="s1", activity="APPROACH", label="Approach")],
    )
    v = VoiceAlertService()
    eng = ExperimentStateEngine(exp, voice=v)
    engine_obj = _FakeEngine()
    with patch.object(va, "pyttsx3", MagicMock(init=lambda: engine_obj)):
        snap = eng.start()
    assert snap["status"] == "RUNNING"
    assert snap["voice"]["state"] == VOICE_READY
    assert snap["voice"]["ready"] is True
    v.close()


def test_engine_start_still_runs_when_voice_fails():
    """A dead TTS must never stop the experiment from running."""
    from app.experiment_state import ExperimentStateEngine
    from app.schemas import ExperimentDef, StepDef

    exp = ExperimentDef(
        id="voice-fail",
        name="Voice fail",
        description="d",
        steps=[StepDef(id="s1", activity="APPROACH", label="Approach")],
    )
    v = VoiceAlertService()

    def boom():
        raise RuntimeError("sapi gone")

    with patch.object(va, "pyttsx3", MagicMock(init=boom)):
        snap = ExperimentStateEngine(exp, voice=v).start()
    assert snap["status"] == "RUNNING"
    assert snap["voice"]["state"] == VOICE_ERROR
    assert snap["voice"]["ready"] is False
    v.close()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
