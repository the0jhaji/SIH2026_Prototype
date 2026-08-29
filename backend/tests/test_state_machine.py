"""Mirror of frontend/scripts/test-reducer.mjs — the backend state machine
must classify identically to the frontend reducer."""

from app.experiment import load_experiment
from app.schemas import Detection
from app.state_machine import ExperimentSession
from pathlib import Path

EXPERIMENTS = Path(__file__).resolve().parent.parent / "experiments"

SCRIPT = [
    ("PICK_MAIN_BOX", 0.96),
    ("OPEN_EXPERIMENT_BOX", 0.91),
    ("OPEN_EXPERIMENT_BOX", 0.41),
    ("PICK_YELLOW_BOX", 0.88),
    ("PICK_RED_BOX", 0.93),
    ("PLACE_RED_BOX", 0.9),
    ("PLACE_YELLOW_BOX", 0.89),
    ("PICK_RED_BOX", 0.87),
    ("WRITING_ON_SURFACE", 0.72),
    ("PICK_YELLOW_BOX", 0.95),
    ("PLACE_YELLOW_BOX", 0.94),
]

EXPECTED_KINDS = [
    "STEP_MATCHED",
    "STEP_MATCHED",
    "LOW_CONFIDENCE",
    "OUT_OF_SEQUENCE",
    "STEP_MATCHED",
    "STEP_MATCHED",
    "OUT_OF_SEQUENCE",
    "REPEATED_STEP",
    "UNKNOWN_ACTIVITY",
    "STEP_MATCHED",
    "STEP_MATCHED",
]


def test_classification_matches_frontend() -> None:
    exp = load_experiment(EXPERIMENTS / "box_sequence.json")
    session = ExperimentSession(exp)
    session.start()

    classified = []
    for activity, confidence in SCRIPT:
        session.on_detection(Detection(activity=activity, confidence=confidence, ts=1))
        classified.append(session.last_classification.kind)

    assert classified == EXPECTED_KINDS
    assert session.errors["outOfSequence"] == 2
    assert session.errors["skipped"] == 2
    assert session.errors["repeated"] == 1
    assert session.errors["unknown"] == 1
    assert session.errors["lowConfidence"] == 1
    assert session.completed_step_ids == ["s1", "s2", "s3", "s4", "s5", "s6"]
    assert session.status == "COMPLETED"


def test_voice_matches_spec_example() -> None:
    exp = load_experiment(EXPERIMENTS / "box_sequence.json")
    session = ExperimentSession(exp)
    session.start()
    session.on_detection(Detection(activity="PICK_MAIN_BOX", confidence=0.96, ts=1))
    session.on_detection(Detection(activity="OPEN_EXPERIMENT_BOX", confidence=0.91, ts=2))
    session.on_detection(Detection(activity="PICK_YELLOW_BOX", confidence=0.88, ts=3))
    voice = session.last_classification.voice
    assert voice == "Incorrect sequence. Please pick the red box."


def test_detection_ignored_when_idle() -> None:
    exp = load_experiment(EXPERIMENTS / "box_sequence.json")
    session = ExperimentSession(exp)
    events = session.on_detection(Detection(activity="PICK_RED_BOX", confidence=0.99, ts=1))
    assert events == []
    assert session.current_step_index == 0


def test_stop_ends_run() -> None:
    exp = load_experiment(EXPERIMENTS / "box_sequence.json")
    session = ExperimentSession(exp)
    session.start()
    session.stop()
    assert session.status == "STOPPED"
    assert session.recording is False