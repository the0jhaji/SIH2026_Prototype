"""Regression tests for the experiment state engine.

Covers: state transitions, temporal confirmation, voice alerts, JSONL logging,
out-of-sequence / skipped / repeated detection, lifecycle, snapshot correctness.
23+ tests — all camera-free, no perception, no network.
"""

import json
import tempfile
import time
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock

import pytest

from app.experiment_log import ExperimentLogger
from app.experiment_state import (
    ABORTED,
    COMPLETED,
    NOT_STARTED,
    RUNNING,
    SEQUENCE_VIOLATION,
    STEP_CANDIDATE,
    STEP_CONFIRMED,
    UNCERTAIN,
    WAITING_FOR_STEP,
    ExperimentStateEngine,
)
from app.schemas import Detection, ExperimentDef, StepDef
from app.voice_alert import VoiceAlertService


# ── helpers ──────────────────────────────────────────────────────────────────

def _step(id: str, activity: str, label: str, order: int = 0) -> StepDef:
    return StepDef(id=id, activity=activity, label=label, order=order)


def _exp(steps: Optional[List[StepDef]] = None) -> ExperimentDef:
    if steps is None:
        steps = [
            _step("s1", "APPROACH", "Approach the box", 1),
            _step("s2", "OPEN_BOX", "Open the box", 2),
            _step("s3", "PICK_RED", "Pick the RED box", 3),
            _step("s4", "PLACE_RED", "Place the RED box", 4),
        ]
    return ExperimentDef(
        id="test-exp-01",
        name="Test Experiment",
        description="Unit test experiment",
        steps=steps,
    )


def _det(activity: str, confidence: float = 0.9) -> Detection:
    return Detection(activity=activity, confidence=confidence, ts=int(time.time() * 1000))


def _make_engine(
    confirm_frames: int = 3,
    min_confidence: float = 0.5,
    voice: bool = True,
) -> tuple[ExperimentStateEngine, MagicMock, Optional[ExperimentLogger]]:
    exp = _exp()
    voice_svc = MagicMock(spec=VoiceAlertService) if voice else None
    ws_events = []
    broadcast = MagicMock(side_effect=lambda t, d: ws_events.append((t, d)))
    with tempfile.TemporaryDirectory() as tmpdir:
        logger = ExperimentLogger(root=Path(tmpdir))
        engine = ExperimentStateEngine(
            exp,
            voice=voice_svc,
            log=logger,
            broadcast=broadcast,
            confirm_frames=confirm_frames,
            min_confidence=min_confidence,
        )
        engine._ws_events = ws_events  # type: ignore[attr-defined]
        return engine, broadcast, logger


# ── lifecycle tests ──────────────────────────────────────────────────────────

def test_initial_state() -> None:
    engine, _, _ = _make_engine()
    assert engine.state == NOT_STARTED
    assert engine.run_id is None
    assert engine.completed_count == 0


def test_start_sets_running() -> None:
    engine, _, _ = _make_engine()
    snap = engine.start()
    assert engine.state == RUNNING
    assert engine.run_id is not None
    assert snap["status"] == "RUNNING"
    assert snap["total_steps"] == 4


def test_start_announces_first_step() -> None:
    engine, _, _ = _make_engine()
    engine.start()
    engine._voice.announce_next_step.assert_any_call("Approach the box", 1, 4)  # type: ignore[union-attr]


def test_stop_sets_aborted() -> None:
    engine, _, _ = _make_engine()
    engine.start()
    snap = engine.stop()
    assert engine.state == ABORTED
    assert snap["status"] == "ABORTED"


def test_stop_announces_paused() -> None:
    engine, _, _ = _make_engine()
    engine.start()
    engine.stop()
    engine._voice.announce_experiment_paused.assert_called()  # type: ignore[union-attr]


def test_stop_writes_log() -> None:
    engine, _, logger = _make_engine()
    engine.start()
    run_id = logger.run_id
    engine.stop()
    assert run_id is not None
    run_dir = logger._root / run_id  # type: ignore[union-attr]
    summary_path = run_dir / "summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "ABORTED"
    log_path = run_dir / "experiment_log.jsonl"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 2
    first = json.loads(lines[0])
    assert first["event"] == "experiment_started"
    last = json.loads(lines[-1])
    assert last["event"] == "experiment_completed"
    assert last["status"] == "ABORTED"


# ── temporal confirmation tests ──────────────────────────────────────────────

def test_single_frame_becomes_candidate() -> None:
    engine, _, _ = _make_engine(confirm_frames=3)
    engine.start()
    snap = engine.on_detection(_det("APPROACH", 0.9))
    assert engine.state == STEP_CANDIDATE
    assert engine._candidate_activity == "APPROACH"
    assert engine._candidate_frames == 1


def test_candidate_needs_n_frames() -> None:
    engine, _, _ = _make_engine(confirm_frames=3)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    assert engine.state == STEP_CANDIDATE
    engine.on_detection(_det("APPROACH", 0.92))
    assert engine.state == STEP_CANDIDATE
    engine.on_detection(_det("APPROACH", 0.88))
    assert engine._current_step_index == 1
    assert engine.completed_count == 1
    assert engine.state == WAITING_FOR_STEP


def test_candidate_resets_on_different_activity() -> None:
    engine, _, _ = _make_engine(confirm_frames=3)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    assert engine.state == STEP_CANDIDATE
    assert engine._candidate_activity == "APPROACH"
    assert engine._candidate_frames == 1
    engine.on_detection(_det("APPROACH", 0.85))
    assert engine._candidate_frames == 2
    engine.on_detection(_det("OPEN_BOX", 0.9))
    assert engine.state == SEQUENCE_VIOLATION


def test_confidence_tracks_max() -> None:
    engine, _, _ = _make_engine(confirm_frames=2)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.7))
    engine.on_detection(_det("APPROACH", 0.95))
    assert engine._candidate_confidence == 0.95


# ── step advancement tests ──────────────────────────────────────────────────

def test_confirmed_step_advances_index() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    assert engine._current_step_index == 0
    engine.on_detection(_det("APPROACH", 0.9))
    assert engine._current_step_index == 1
    assert engine.completed_count == 1


def test_confirmed_step_announces_completion() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    engine._voice.announce_step_completed.assert_any_call("Approach the box")  # type: ignore[union-attr]


def test_confirmed_step_announces_next() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    engine._voice.announce_next_step.assert_any_call("Open the box", 2, 4)  # type: ignore[union-attr]


def test_experiment_completes() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    engine.on_detection(_det("OPEN_BOX", 0.9))
    engine.on_detection(_det("PICK_RED", 0.9))
    engine.on_detection(_det("PLACE_RED", 0.9))
    assert engine.state == COMPLETED
    assert engine.completed_count == 4


def test_complete_announces_success() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    for act in ["APPROACH", "OPEN_BOX", "PICK_RED", "PLACE_RED"]:
        engine.on_detection(_det(act, 0.9))
    engine._voice.announce_experiment_completed.assert_called()  # type: ignore[union-attr]


def test_complete_writes_summary() -> None:
    engine, _, logger = _make_engine(confirm_frames=1)
    engine.start()
    run_id = logger.run_id
    for act in ["APPROACH", "OPEN_BOX", "PICK_RED", "PLACE_RED"]:
        engine.on_detection(_det(act, 0.9))
    assert run_id is not None
    summary_path = logger._root / run_id / "summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["status"] == "COMPLETED"
    assert summary["completed_steps"] == 4


# ── out-of-sequence / skipped / repeated tests ──────────────────────────────

def test_out_of_sequence_detected() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    snap = engine.on_detection(_det("PICK_RED", 0.9))
    assert engine.state == SEQUENCE_VIOLATION
    alerts = [a for a in snap["violations"] if a["kind"] == "OUT_OF_SEQUENCE"]
    assert len(alerts) >= 1


def test_out_of_sequence_announces() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("PICK_RED", 0.9))
    engine._voice.announce_out_of_sequence.assert_called()  # type: ignore[union-attr]


def test_skipped_steps_detected() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    snap = engine.on_detection(_det("PLACE_RED", 0.9))
    skip_alerts = [a for a in snap["violations"] if a["kind"] == "SKIPPED_STEP"]
    assert len(skip_alerts) >= 2


def test_repeated_step_detected() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    snap = engine.on_detection(_det("APPROACH", 0.9))
    alerts = [a for a in snap["violations"] if a["kind"] == "REPEATED_STEP"]
    assert len(alerts) >= 1


def test_repeated_step_announces() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    engine.on_detection(_det("APPROACH", 0.9))
    engine._voice.announce_repeated_step.assert_any_call("Approach the box")  # type: ignore[union-attr]


# ── low confidence / unknown tests ──────────────────────────────────────────

def test_low_confidence_returns_uncertain() -> None:
    engine, _, _ = _make_engine(confirm_frames=1, min_confidence=0.5)
    engine.start()
    snap = engine.on_detection(_det("APPROACH", 0.3))
    assert engine.state == UNCERTAIN


def test_unknown_activity_returns_uncertain() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    snap = engine.on_detection(_det("NONEXISTENT_ACTIVITY", 0.9))
    assert engine.state == UNCERTAIN


def test_low_confidence_announces_uncertain() -> None:
    engine, _, _ = _make_engine(confirm_frames=1, min_confidence=0.5)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.3))
    engine._voice.announce_uncertain.assert_called()  # type: ignore[union-attr]


# ── snapshot tests ──────────────────────────────────────────────────────────

def test_snapshot_has_all_fields() -> None:
    engine, _, _ = _make_engine()
    engine.start()
    snap = engine.snapshot()
    assert "run_id" in snap
    assert "experiment_id" in snap
    assert "experiment_name" in snap
    assert "status" in snap
    assert "current_step" in snap
    assert "next_step" in snap
    assert "completed_steps" in snap
    assert "completed_count" in snap
    assert "total_steps" in snap
    assert "violations" in snap
    assert "violation_count" in snap


def test_snapshot_current_step_first() -> None:
    engine, _, _ = _make_engine()
    engine.start()
    snap = engine.snapshot()
    assert snap["current_step"]["activity"] == "APPROACH"
    assert snap["current_step"]["step_number"] == 1


def test_snapshot_next_step_after_advance() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    snap = engine.snapshot()
    assert snap["current_step"]["activity"] == "OPEN_BOX"
    assert snap["next_step"]["activity"] == "PICK_RED"


def test_snapshot_no_step_when_completed() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    for act in ["APPROACH", "OPEN_BOX", "PICK_RED", "PLACE_RED"]:
        engine.on_detection(_det(act, 0.9))
    snap = engine.snapshot()
    assert snap["current_step"] is None
    assert snap["next_step"] is None


# ── WebSocket broadcast tests ───────────────────────────────────────────────

def test_start_broadcasts_experiment_started() -> None:
    engine, broadcast, _ = _make_engine()
    engine.start()
    types = [t for t, _ in engine._ws_events]  # type: ignore[attr-defined]
    assert "experiment_started" in types


def test_confirmed_step_broadcasts() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    types = [t for t, _ in engine._ws_events]  # type: ignore[attr-defined]
    assert "step_confirmed" in types
    assert "next_step" in types


def test_completion_broadcasts() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    for act in ["APPROACH", "OPEN_BOX", "PICK_RED", "PLACE_RED"]:
        engine.on_detection(_det(act, 0.9))
    types = [t for t, _ in engine._ws_events]  # type: ignore[attr-defined]
    assert "experiment_completed" in types


def test_violation_broadcasts() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("PICK_RED", 0.9))
    types = [t for t, _ in engine._ws_events]  # type: ignore[attr-defined]
    assert "out_of_sequence" in types
    assert "step_skipped" in types


# ── JSONL logging tests ─────────────────────────────────────────────────────

def test_jsonl_logs_step_confirmed() -> None:
    engine, _, logger = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    lines = [
        json.loads(line)
        for line in logger.log_path.read_text(encoding="utf-8").strip().splitlines()  # type: ignore[union-attr]
    ]
    confirmed = [l for l in lines if l["event"] == "step_confirmed"]
    assert len(confirmed) == 1
    assert confirmed[0]["step_id"] == "s1"
    assert confirmed[0]["status"] == "SUCCESS"


def test_jsonl_logs_next_step() -> None:
    engine, _, logger = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    lines = [
        json.loads(line)
        for line in logger.log_path.read_text(encoding="utf-8").strip().splitlines()  # type: ignore[union-attr]
    ]
    next_steps = [l for l in lines if l["event"] == "next_step"]
    assert len(next_steps) == 2  # initial + after first confirm


def test_jsonl_logs_out_of_sequence() -> None:
    engine, _, logger = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("PICK_RED", 0.9))
    lines = [
        json.loads(line)
        for line in logger.log_path.read_text(encoding="utf-8").strip().splitlines()  # type: ignore[union-attr]
    ]
    oos = [l for l in lines if l["event"] == "out_of_sequence"]
    assert len(oos) >= 1
    assert oos[0]["status"] == "SEQUENCE_VIOLATION"


def test_jsonl_logs_skipped_steps() -> None:
    engine, _, logger = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("PLACE_RED", 0.9))
    lines = [
        json.loads(line)
        for line in logger.log_path.read_text(encoding="utf-8").strip().splitlines()  # type: ignore[union-attr]
    ]
    skipped = [l for l in lines if l["event"] == "step_skipped"]
    assert len(skipped) >= 2


def test_jsonl_logs_repeated_step() -> None:
    engine, _, logger = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.9))
    engine.on_detection(_det("APPROACH", 0.9))
    lines = [
        json.loads(line)
        for line in logger.log_path.read_text(encoding="utf-8").strip().splitlines()  # type: ignore[union-attr]
    ]
    repeated = [l for l in lines if l["event"] == "repeated_step"]
    assert len(repeated) >= 1
    assert repeated[0]["status"] == "REPEATED"


def test_jsonl_logs_low_confidence() -> None:
    engine, _, logger = _make_engine(confirm_frames=1, min_confidence=0.5)
    engine.start()
    engine.on_detection(_det("APPROACH", 0.3))
    lines = [
        json.loads(line)
        for line in logger.log_path.read_text(encoding="utf-8").strip().splitlines()  # type: ignore[union-attr]
    ]
    uncertain = [l for l in lines if l["event"] == "activity_uncertain"]
    assert len(uncertain) >= 1
    assert uncertain[0]["reason"] == "low_confidence"


def test_jsonl_logs_unknown_activity() -> None:
    engine, _, logger = _make_engine(confirm_frames=1)
    engine.start()
    engine.on_detection(_det("NONEXISTENT", 0.9))
    lines = [
        json.loads(line)
        for line in logger.log_path.read_text(encoding="utf-8").strip().splitlines()  # type: ignore[union-attr]
    ]
    uncertain = [l for l in lines if l["event"] == "activity_uncertain"]
    assert len(uncertain) >= 1
    assert uncertain[0]["reason"] == "unknown_activity"


# ── idle / no-op when not running ───────────────────────────────────────────

def test_detection_before_start_ignored() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    snap = engine.on_detection(_det("APPROACH", 0.9))
    assert engine.state == NOT_STARTED


def test_detection_after_complete_ignored() -> None:
    engine, _, _ = _make_engine(confirm_frames=1)
    engine.start()
    for act in ["APPROACH", "OPEN_BOX", "PICK_RED", "PLACE_RED"]:
        engine.on_detection(_det(act, 0.9))
    snap = engine.on_detection(_det("APPROACH", 0.9))
    assert engine.state == COMPLETED
    assert snap["completed_count"] == 4
