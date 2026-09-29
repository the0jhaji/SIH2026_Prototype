"""Exhaustive state-transition tests for the experiment state machine.

Covers every classification outcome from every reachable position in the
sequence, plus all lifecycle transitions and the post-run guard states.
"""

import pytest

from app.experiment import load_experiment
from app.schemas import Detection
from app.state_machine import ExperimentSession
from pathlib import Path

EXPERIMENTS = Path(__file__).resolve().parent.parent / "experiments"


@pytest.fixture()
def exp():
    return load_experiment(EXPERIMENTS / "box_sequence.json")


def session_at(exp, done: int) -> ExperimentSession:
    """Start a run and complete the first ``done`` steps correctly."""
    s = ExperimentSession(exp)
    s.start()
    for i in range(done):
        s.on_detection(Detection(activity=exp.steps[i].activity, confidence=0.99, ts=1))
    return s


def detect(s: ExperimentSession, activity, confidence=0.99) -> list:
    return s.on_detection(Detection(activity=activity, confidence=confidence, ts=1))


# ---------------------------------------------------------------- lifecycle

def test_start_transition(exp) -> None:
    s = ExperimentSession(exp)
    events = s.start()
    assert [e.kind for e in events] == ["EXPERIMENT_STARTED", "RECORDING_STARTED"]
    assert s.status == "RUNNING"
    assert s.recording is True
    assert s.current_step_index == 0
    assert s.completed_step_ids == []
    assert all(err == 0 for err in s.errors.values())


def test_stop_transition(exp) -> None:
    s = session_at(exp, 2)
    events = s.stop()
    assert [e.kind for e in events] == ["EXPERIMENT_STOPPED", "RECORDING_STOPPED"]
    assert s.status == "STOPPED"
    assert s.recording is False
    assert s.current_step_index == 2


# ------------------------------------------------------------- guard states

def test_detection_ignored_when_idle(exp) -> None:
    s = ExperimentSession(exp)
    assert detect(s, "PICK_MAIN_BOX") == []
    assert s.current_step_index == 0
    assert s.last_classification is None


def test_detection_ignored_after_stop(exp) -> None:
    s = session_at(exp, 3)
    s.stop()
    assert detect(s, "PICK_RED_BOX") == []
    assert s.status == "STOPPED"
    assert s.current_step_index == 3


def test_detection_ignored_after_complete(exp) -> None:
    s = session_at(exp, 6)
    assert s.status == "COMPLETED"
    assert detect(s, "PLACE_YELLOW_BOX") == []
    assert detect(s, "PICK_RED_BOX") == []
    assert s.current_step_index == len(exp.steps)
    assert s.completed_step_ids == [step.id for step in exp.steps]


# ------------------------------------------------- classification outcomes

@pytest.mark.parametrize("done", list(range(6)))
def test_low_confidence_never_advances(exp, done: int) -> None:
    s = session_at(exp, done)
    expected = exp.steps[done].activity
    events = detect(s, expected, confidence=0.3)
    assert [e.kind for e in events] == ["LOW_CONFIDENCE"]
    assert events[0].result == "LOW_CONFIDENCE"
    assert events[0].activity == expected
    assert s.current_step_index == done
    assert s.completed_step_ids == [step.id for step in exp.steps[:done]]
    assert s.errors["lowConfidence"] == 1
    assert s.status == "RUNNING"


@pytest.mark.parametrize("done", list(range(6)))
def test_unknown_null_activity(exp, done: int) -> None:
    s = session_at(exp, done)
    events = detect(s, None)
    assert [e.kind for e in events] == ["UNKNOWN_ACTIVITY"]
    assert events[0].result == "UNKNOWN"
    assert s.current_step_index == done
    assert s.errors["unknown"] == 1
    assert s.last_classification is events[0]


@pytest.mark.parametrize("done", list(range(6)))
def test_unknown_unmapped_activity(exp, done: int) -> None:
    s = session_at(exp, done)
    events = detect(s, "STIR_FLUID")
    assert [e.kind for e in events] == ["UNKNOWN_ACTIVITY"]
    assert events[0].result == "UNKNOWN"
    assert events[0].expected == exp.steps[done].activity
    assert s.current_step_index == done
    assert s.errors["unknown"] == 1


@pytest.mark.parametrize("done", list(range(1, 6)))
def test_repeated_completed_step(exp, done: int) -> None:
    s = session_at(exp, done)
    event = detect(s, exp.steps[done - 1].activity)
    assert [e.kind for e in event] == ["REPEATED_STEP"]
    assert event[0].result == "REPEATED"
    assert event[0].activity == exp.steps[done - 1].activity
    assert event[0].expected == exp.steps[done].activity
    assert s.current_step_index == done
    assert s.errors["repeated"] == 1


#: What stepping one step too far is called, per position. The two steps share
#: an object (``MAIN_BOX`` at 0->1, ``RED_BOX`` at 2->3, ``YELLOW_BOX`` at 4->5)
#: and disagree on the action, so the refusal is specific: WRONG_SEQUENCE. The
#: two crossings that change both action and object (1->2, 3->4) have nothing
#: to be specific about and stay OUT_OF_SEQUENCE.
LATER_STEP_RECOURSE = {
    0: "WRONG_SEQUENCE",
    1: "OUT_OF_SEQUENCE",
    2: "WRONG_SEQUENCE",
    3: "OUT_OF_SEQUENCE",
    4: "WRONG_SEQUENCE",
}

COUNTER_FOR = {
    "WRONG_OBJECT": "wrongObject",
    "WRONG_SEQUENCE": "wrongSequence",
    "OUT_OF_SEQUENCE": "outOfSequence",
}


@pytest.mark.parametrize("done", list(range(5)))
def test_out_of_sequence_also_skips(exp, done: int) -> None:
    s = session_at(exp, done)
    future = exp.steps[done + 1]
    kind = LATER_STEP_RECOURSE[done]
    events = detect(s, future.activity)
    assert [e.kind for e in events] == [kind, "SKIPPED_STEP"]
    primary, advisory = events
    assert primary.result == kind
    assert primary.severity == "error"
    assert primary.activity == future.activity
    assert primary.expected == exp.steps[done].activity
    assert advisory.result == "SKIPPED"
    assert advisory.step_id == exp.steps[done].id
    assert s.last_classification is primary
    assert s.errors[COUNTER_FOR[kind]] == 1
    assert s.errors["skipped"] == 1
    assert s.current_step_index == done


def test_wrong_object_is_named_for_the_operator(exp) -> None:
    """Picking the yellow box while the red box is due names both objects."""
    s = session_at(exp, 2)  # PICK_RED_BOX is expected
    events = detect(s, exp.steps[4].activity)  # PICK_YELLOW_BOX instead
    primary = events[0]
    assert primary.kind == "WRONG_OBJECT"
    assert primary.voice == "Warning. The red box is expected, not the yellow box."
    assert s.errors["wrongObject"] == 1
    assert s.current_step_index == 2


@pytest.mark.parametrize("done", list(range(5)))
def test_correct_step_advances(exp, done: int) -> None:
    s = session_at(exp, done)
    step = exp.steps[done]
    events = detect(s, step.activity)
    assert [e.kind for e in events] == ["STEP_MATCHED"]
    assert events[0].result == "CORRECT"
    assert events[0].step_id == step.id
    assert s.current_step_index == done + 1
    assert s.completed_step_ids == [st.id for st in exp.steps[: done + 1]]
    assert s.status == "RUNNING"


def test_final_step_completes(exp) -> None:
    s = session_at(exp, 5)
    events = detect(s, "PLACE_YELLOW_BOX")
    assert [e.kind for e in events] == ["STEP_MATCHED", "EXPERIMENT_COMPLETED", "RECORDING_STOPPED"]
    assert events[0].result == "CORRECT"
    assert events[0].step_id == "s6"
    assert s.status == "COMPLETED"
    assert s.recording is False
    assert s.current_step_index == 6
    assert s.completed_step_ids == [step.id for step in exp.steps]


def test_completion_emits_zero_errors(exp) -> None:
    s = session_at(exp, 6)
    assert all(err == 0 for err in s.errors.values())