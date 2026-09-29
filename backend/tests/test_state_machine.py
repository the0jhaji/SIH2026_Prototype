"""Mirror of frontend/scripts/test-reducer.mjs — the backend state machine
must classify identically to the frontend reducer."""

from app.experiment import load_active_experiment, load_experiment
from app.schemas import Detection, ExperimentDef, StepDef
from app.state_machine import ExperimentSession, voice_instruction
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
    # Picking the yellow box when the red box is due: same action, other object.
    "WRONG_OBJECT",
    "STEP_MATCHED",
    "STEP_MATCHED",
    # Putting the yellow box down before picking it up: same object, other action.
    "WRONG_SEQUENCE",
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
    # Both out-of-order detections were refined into a specific recourse, so
    # neither lands in the generic bucket.
    assert session.errors["outOfSequence"] == 0
    assert session.errors["wrongObject"] == 1
    assert session.errors["wrongSequence"] == 1
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
    assert voice == "Warning. The red box is expected, not the yellow box."


def test_voice_for_wrong_sequence() -> None:
    exp = load_experiment(EXPERIMENTS / "box_sequence.json")
    session = ExperimentSession(exp)
    session.start()
    for activity, confidence in (
        ("PICK_MAIN_BOX", 0.96),
        ("OPEN_EXPERIMENT_BOX", 0.91),
        ("PICK_RED_BOX", 0.93),
        ("PLACE_RED_BOX", 0.9),
        ("PLACE_YELLOW_BOX", 0.89),  # placed before it was picked up
    ):
        session.on_detection(Detection(activity=activity, confidence=confidence, ts=1))
    assert session.last_classification.kind == "WRONG_SEQUENCE"
    assert session.last_classification.voice == (
        "Warning. Wrong sequence. Please pick the yellow box."
    )


def test_steps_without_action_metadata_stay_generic() -> None:
    """Legacy steps carry no action/object, so they keep OUT_OF_SEQUENCE."""
    exp = ExperimentDef(
        id="legacy",
        name="Legacy",
        steps=[
            StepDef(id="s1", activity="STEP_A", label="Step a"),
            StepDef(id="s2", activity="STEP_B", label="Step b"),
        ],
    )
    session = ExperimentSession(exp)
    session.start()
    session.on_detection(Detection(activity="STEP_B", confidence=0.9, ts=1))
    assert session.last_classification.kind == "OUT_OF_SEQUENCE"
    assert session.errors["outOfSequence"] == 1
    assert session.errors["wrongObject"] == 0
    assert session.errors["wrongSequence"] == 0


def test_canonical_voice_uses_explicit_instruction() -> None:
    """Canonical labels are third person; the prompt must stay imperative.

    Deriving "Please astronaut the picks up the red box." from the label is the
    bug this guards: the spoken form is data, not a split of the display text.
    """
    exp = load_active_experiment()
    session = ExperimentSession(exp)
    session.start()
    for activity in ("APPROACH", "OPEN_BOX"):
        session.on_detection(Detection(activity=activity, confidence=0.95, ts=1))

    # PICK_RED is now expected; placing the red box is the right object, wrong action.
    session.on_detection(Detection(activity="PLACE_RED", confidence=0.9, ts=2))
    assert session.last_classification.kind == "WRONG_SEQUENCE"
    assert session.last_classification.voice == "Warning. Wrong sequence. Please pick up the red box."

    # And a wrong-object prompt on the same step names both boxes.
    session.on_detection(Detection(activity="PICK_YELLOW", confidence=0.9, ts=3))
    assert session.last_classification.kind == "WRONG_OBJECT"
    assert session.last_classification.voice == (
        "Warning. The red box is expected, not the yellow box."
    )


def test_voice_falls_back_to_label_for_legacy_steps() -> None:
    """Legacy definitions have no voiceInstruction, so the label is used."""
    exp = load_experiment(EXPERIMENTS / "box_sequence.json")
    assert all(step.voiceInstruction is None for step in exp.steps)
    assert voice_instruction(exp.steps[0], "Please continue") == "Please pick the main experiment box."


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