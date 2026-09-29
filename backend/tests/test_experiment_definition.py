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
    "WRONG_OBJECT",
    "WRONG_SEQUENCE",
    "SKIPPED",
    "REPEATED",
    "UNKNOWN",
    "LOW_CONFIDENCE",
]

CANONICAL_KINDS = [
    "STEP_MATCHED",
    "OUT_OF_SEQUENCE",
    "WRONG_OBJECT",
    "WRONG_SEQUENCE",
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

#: The KINDS above that classify a detection, in order — the prefix the
#: errorTypes table mirrors one-to-one.
CLASSIFICATION_KINDS = CANONICAL_KINDS[:8]

EVIDENCE_KINDS = {"PRESENT", "MOVED", "PLACED"}


@pytest.fixture(scope="module")
def experiment() -> dict:
    return json.loads(EXPERIMENT_PATH.read_text(encoding="utf-8"))


def test_experiment_definition_loads() -> None:
    assert EXPERIMENT_PATH.is_file(), f"missing {EXPERIMENT_PATH}"
    data = json.loads(EXPERIMENT_PATH.read_text(encoding="utf-8"))
    assert data["schemaVersion"] == "1.1"
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
    assert kinds == CLASSIFICATION_KINDS, f"error kinds {kinds}"
    matched = {err["code"]: err for err in experiment["errorTypes"] if err["kind"] == "STEP_MATCHED"}
    assert matched["CORRECT"]["advance"] is True
    for err in experiment["errorTypes"]:
        if err["code"] != "CORRECT":
            assert err["advance"] is False


def test_worked_example_matches_error_types(experiment) -> None:
    example = experiment["example"]
    assert example["expected"] == "PICK_RED"
    assert example["observed"] == "PICK_YELLOW"
    # Same action, different object: the refined classification, not the
    # generic one.
    assert example["result"] == "WRONG_OBJECT"
    assert example["nextExpected"] == "PICK_RED"
    kinds = {err["code"] for err in experiment["errorTypes"]}
    assert example["result"] in kinds
    wrong_object = next(err for err in experiment["errorTypes"] if err["code"] == "WRONG_OBJECT")
    assert wrong_object["advance"] is False


def test_expected_events_are_a_valid_evidence_contract(experiment) -> None:
    """Every step declares the tracker evidence that satisfies it."""
    object_ids = {obj["id"] for obj in experiment["objects"]}
    assert set(experiment["evidenceKinds"]) == EVIDENCE_KINDS
    assert experiment["evidenceNotes"], "the evidence contract must state its own limits"
    for step in experiment["steps"]:
        events = step.get("expectedEvents")
        assert events, f"step {step['id']} declares no expectedEvents"
        for rule in events:
            assert rule["event"] in EVIDENCE_KINDS, rule
            objects = rule["object"] if isinstance(rule["object"], list) else [rule["object"]]
            assert objects, f"step {step['id']} has an evidence rule with no object"
            for obj in objects:
                assert obj in object_ids, f"step {step['id']} references unknown object {obj!r}"


def test_action_and_object_metadata_support_the_refinement(experiment) -> None:
    """The recourse classification is only possible where the metadata exists.

    A step pair sharing an action must differ in object (WRONG_OBJECT) and a
    pair sharing an object must differ in action (WRONG_SEQUENCE) for the
    example in experiment["example"] to be classifiable at all.
    """
    by_activity = {step["activity"]: step for step in experiment["steps"]}
    pick_red = by_activity["PICK_RED"]
    pick_yellow = by_activity["PICK_YELLOW"]
    assert pick_red["action"] == pick_yellow["action"] == "PICK"
    assert pick_red["object"] == "RED_BOX"
    assert pick_yellow["object"] == "YELLOW_BOX"
    place_red = by_activity["PLACE_RED"]
    assert place_red["action"] == "PLACE" and place_red["object"] == "RED_BOX"
    # Steps that are pure presence or terminal bookkeeping carry no action.
    assert by_activity["APPROACH"]["action"] is None
    assert by_activity["COMPLETE"]["action"] is None


def test_step_activities_all_defined(experiment) -> None:
    activities = set(experiment["activities"])
    for step in experiment["steps"]:
        assert step["activity"] in activities, f"step {step['id']} has undefined activity"


def test_no_step_requires_a_class_no_detector_can_see(experiment) -> None:
    """Every grounding class must be emitted by some shipped detector.

    ``experiment_box`` is declared in the object table but no shipped model
    produces it (the custom model knows only red/yellow; the heuristic detector
    sees person/red/yellow). Grounding OPEN_BOX on it would stall the run at
    step 2 forever with no error, which is the silent failure this guards.

    ``target_area`` is deliberately NOT in this set: it is a fixed piece of
    station hardware, not something a model can see. It is supplied by
    ``ACTIVITY_TARGET_AREA`` config instead, and the run reports
    ``placedGrounded=false`` when that is unset.
    """
    detectable = {"person", "red_box", "yellow_box"}
    for step in experiment["steps"]:
        for rule in step["expectedEvents"]:
            objects = rule["object"] if isinstance(rule["object"], list) else [rule["object"]]
            for obj in objects:
                assert obj in detectable, (
                    f"step {step['id']} requires {obj!r}, which no shipped detector emits"
                )

    by_activity = {step["activity"]: step for step in experiment["steps"]}
    open_box = by_activity["OPEN_BOX"]
    assert open_box["expectedEvents"] == [
        {"event": "MOVED", "object": ["red_box", "yellow_box"]}
    ]
    # And the limitation is stated, not hidden.
    assert "no container or lid detector" in experiment["evidenceNotes"]["KNOWN_LIMITS"]


def test_every_step_has_an_imperative_voice_instruction(experiment) -> None:
    """Voice prompts are data, because labels are third-person operator prose."""
    for step in experiment["steps"]:
        assert step["voiceInstruction"], f"step {step['id']} has no voiceInstruction"
        assert not step["voiceInstruction"].lower().startswith(("please", "astronaut", "the astronaut"))
    # The spoken form is imperative even though the label is not.
    assert experiment["steps"][2]["label"].startswith("Astronaut ")
    assert experiment["steps"][2]["voiceInstruction"] == "pick up the red box"