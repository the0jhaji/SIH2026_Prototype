"""Phase 5A definition checks for the BAS prototype experiment.

Validates experiment/experiment.json as machine-readable data for the future
activity-recognition + sequence-validation modules: it loads cleanly, the step
order is correct, ids/names are unique, every step has its required fields,
expected objects resolve against the object table, and the validation
rules / error types match the canonical vocabulary.

Pure data validation - no cameras, no AI, no model training.
"""

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_PATH = REPO_ROOT / "experiment" / "experiment.json"
CLASSES_PATH = REPO_ROOT / "dataset" / "annotation" / "classes.json"

EXPECTED_SEQUENCE = [
    "APPROACH",
    "OPEN_BOX",
    "PICK_RED",
    "PLACE_RED",
    "PICK_YELLOW",
    "PLACE_YELLOW",
    "COMPLETE",
]

REQUIRED_STEP_FIELDS = {"id", "order", "activity", "label", "description", "expectedObjects"}

CANONICAL_RESULTS = [
    "CORRECT",
    "OUT_OF_SEQUENCE",
    "SKIPPED",
    "REPEATED",
    "UNKNOWN",
    "LOW_CONFIDENCE",
]

CANONICAL_KINDS = [
    "STEP_MATCHED",
    "OUT_OF_SEQUENCE",
    "SKIPPED_STEP",
    "REPEATED_STEP",
    "UNKNOWN_ACTIVITY",
    "LOW_CONFIDENCE",
    "EXPERIMENT_STARTED",
    "EXPERIMENT_STOPPED",
    "EXPERIMENT_COMPLETED",
    "RECORDING_STARTED",
    "RECORDING_STOPPED",
]


@pytest.fixture(scope="module")
def experiment() -> dict:
    return json.loads(EXPERIMENT_PATH.read_text(encoding="utf-8"))


def test_experiment_definition_loads() -> None:
    assert EXPERIMENT_PATH.is_file(), f"missing {EXPERIMENT_PATH}"
    data = json.loads(EXPERIMENT_PATH.read_text(encoding="utf-8"))
    assert data["schemaVersion"] == "1.0"
    assert data["prototype"] is True
    assert data["name"] == "BAS Box Handling Experiment"
    assert data["disclaimer"] and "NOT the official ISRO sequence" in data["disclaimer"]
    assert data["description"]


def test_step_order_matches_expected_sequence(experiment) -> None:
    activities = [step["activity"] for step in experiment["steps"]]
    assert activities == EXPECTED_SEQUENCE
    for index, step in enumerate(experiment["steps"], start=1):
        assert step["order"] == index, f"step {step['id']} out of order"


def test_terminal_step_is_last(experiment) -> None:
    terminal = [step["activity"] for step in experiment["steps"] if step.get("terminal")]
    assert terminal == ["COMPLETE"]
    assert experiment["steps"][-1]["activity"] == "COMPLETE"
    assert experiment["validationRules"]["terminalSteps"] == ["COMPLETE"]


def test_object_ids_are_unique(experiment) -> None:
    ids = [obj["id"] for obj in experiment["objects"]]
    class_ids = [obj["classId"] for obj in experiment["objects"]]
    assert len(ids) == len(set(ids)), f"duplicate object ids: {ids}"
    assert len(class_ids) == len(set(class_ids)), f"duplicate classIds: {class_ids}"


def test_object_ids_match_dataset_classes(experiment) -> None:
    """The box-demo object table vs the dataset training vocabulary.

    The demo table uses the legacy 5-class scene scheme (person, experiment_box,
    red_box, yellow_box, target_area); the dataset vocabulary now holds the
    8-class training set (classes.json), where the box-demo-only classes
    (experiment_box, target_area) deliberately do NOT exist — they are
    untrainable scene props. The contract that matters is that the noun
    classes both schemes share resolve under the same names, and that the
    demo-only classes are visibly declared as such instead of being silently
    remapped onto trained class ids.
    """
    dataset_classes = json.loads(CLASSES_PATH.read_text(encoding="utf-8"))["classes"]
    assert len(dataset_classes) >= 5
    shared = {obj["id"] for obj in experiment["objects"]} & set(dataset_classes)
    assert shared >= {"person", "red_box", "yellow_box"}
    demo_only = {obj["id"] for obj in experiment["objects"]} - set(dataset_classes)
    assert demo_only <= {"experiment_box", "target_area"}


def test_activity_names_are_unique(experiment) -> None:
    activities = experiment["activities"]
    assert len(activities) == len(set(activities))
    assert activities == EXPECTED_SEQUENCE
    assert set(activities) == {step["activity"] for step in experiment["steps"]}


def test_every_step_has_required_fields(experiment) -> None:
    object_ids = {obj["id"] for obj in experiment["objects"]}
    for step in experiment["steps"]:
        missing = REQUIRED_STEP_FIELDS - set(step)
        assert not missing, f"step {step.get('id')} missing {missing}"
        assert step["expectedObjects"], f"step {step['id']} has empty expectedObjects"
        for expected in step["expectedObjects"]:
            assert expected in object_ids, (
                f"step {step['id']} references unknown object {expected!r}"
            )


def test_validation_rules_are_valid(experiment) -> None:
    rules = experiment["validationRules"]
    assert rules["mode"] == "strict-sequence"
    assert rules["advanceOnMatch"] is True
    assert rules["stayOnStepOnError"] is True
    threshold = rules["lowConfidenceThreshold"]
    assert 0.0 < threshold <= 1.0
    assert rules["canonicalResultLabels"] == CANONICAL_RESULTS
    assert rules["canonicalEventKinds"] == CANONICAL_KINDS
    assert rules["terminalSteps"] == ["COMPLETE"]


def test_error_types_are_consistent(experiment) -> None:
    rules = experiment["validationRules"]
    codes = [err["code"] for err in experiment["errorTypes"]]
    kinds = [err["kind"] for err in experiment["errorTypes"]]
    assert codes == rules["canonicalResultLabels"], f"error codes {codes}"
    assert kinds == rules["canonicalEventKinds"][:6], f"error kinds {kinds}"
    matched = {err["code"]: err for err in experiment["errorTypes"] if err["kind"] == "STEP_MATCHED"}
    assert matched["CORRECT"]["advance"] is True
    for err in experiment["errorTypes"]:
        if err["code"] != "CORRECT":
            assert err["advance"] is False


def test_worked_example_matches_error_types(experiment) -> None:
    example = experiment["example"]
    assert example["expected"] == "PICK_RED"
    assert example["observed"] == "PICK_YELLOW"
    assert example["result"] == "OUT_OF_SEQUENCE"
    assert example["nextExpected"] == "PICK_RED"
    kinds = {err["code"] for err in experiment["errorTypes"]}
    assert example["result"] in kinds
    out_of_seq = next(err for err in experiment["errorTypes"] if err["code"] == "OUT_OF_SEQUENCE")
    assert out_of_seq["advance"] is False


def test_step_activities_all_defined(experiment) -> None:
    activities = set(experiment["activities"])
    for step in experiment["steps"]:
        assert step["activity"] in activities, f"step {step['id']} has undefined activity"