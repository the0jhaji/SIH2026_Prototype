"""Unattended object in a container: the KNOWN-class chain.

Camera-free and deterministic. Feeds the AttendanceMonitor the same camelCase
payload shape DetectionService.latest() produces, and drives the real reported
sequence:

    PERSON + empty box -> person places bottle -> bottle inside box
    -> person walks away -> 2s unattended timer -> UNATTENDED -> alert

Covers the failures this replaces: a known object was never watched at all, the
chain could only be reached through HELD, and the timer counted frames rather
than wall clock.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.app.attendance import (
    ATTENDED,
    IN_CONTAINER,
    UNATTENDED,
    AttendanceMonitor,
    _containment_score,
)

CONTAINERS = ("experiment_box",)
TRACKED = ("bottle", "floating_tool")


def det(cls: str, x1: int, y1: int, x2: int, y2: int, conf: float = 0.8, iid: str | None = None) -> dict:
    d = {
        "class_name": cls,
        "confidence": conf,
        "x1": x1,
        "y1": y1,
        "x2": x2,
        "y2": y2,
        "timestamp": int(time.time() * 1000),
    }
    if iid:
        d["instance_id"] = iid
    return d


def payload(detections: list[dict], unknown: list[dict] | None = None, w: int = 1280, h: int = 720) -> dict:
    return {
        "enabled": True,
        "frameWidth": w,
        "frameHeight": h,
        "detections": detections,
        "unknownDetections": unknown or [],
    }


def monitor(**kw) -> AttendanceMonitor:
    params = {
        "unattended_timeout_ms": 2000,
        "proximity": 0.18,
        "containment": 0.6,
        "container_classes": CONTAINERS,
        "tracked_classes": TRACKED,
    }
    params.update(kw)
    return AttendanceMonitor(lambda: params.pop("_payload", payload([])), **params)


def drive(mon: AttendanceMonitor, p: dict, steps: int = 1) -> list[dict]:
    """Run ``steps`` async ticks against a fixed payload, returning all events."""
    out: list[dict] = []
    for _ in range(steps):
        mon._provider = lambda p=p: p
        asyncio.run(mon.step())
        out.extend(mon._events[-40:])
    return out


# --------------------------------------------------------------------- geometry

def test_containment_score_is_object_relative() -> None:
    # Bottle fully inside a large box -> 1.0
    assert _containment_score(det("bottle", 500, 400, 540, 440), det("experiment_box", 400, 350, 700, 550)) == 1.0
    # Bottle half out -> ~0.5
    assert 0.4 < _containment_score(det("bottle", 650, 400, 750, 440), det("experiment_box", 400, 350, 700, 550)) < 0.6
    # No overlap -> 0.0
    assert _containment_score(det("bottle", 0, 0, 20, 20), det("experiment_box", 400, 350, 700, 550)) == 0.0


def test_zero_area_object_does_not_divide_by_zero() -> None:
    assert _containment_score(det("bottle", 500, 400, 500, 400), det("experiment_box", 400, 350, 700, 550)) == 0.0


# ----------------------------------------------------------------- known watching

def test_known_object_is_watched_at_all() -> None:
    """The core bug: a bottle is a KNOWN class and used to be invisible here."""
    mon = monitor()
    drive(mon, payload([det("bottle", 500, 400, 540, 440), det("person", 300, 200, 400, 600)]), 3)
    assert len(mon.watches) == 1
    watch = next(iter(mon.watches.values()))
    assert watch.class_name == "bottle"
    assert watch.is_unknown is False


def test_person_class_is_never_watched_as_an_object() -> None:
    mon = monitor()
    drive(mon, payload([det("person", 300, 200, 400, 600)]), 3)
    assert mon.watches == {}


def test_untracked_known_class_is_ignored() -> None:
    mon = monitor()
    drive(mon, payload([det("laptop", 100, 100, 200, 200)]), 3)
    assert mon.watches == {}


def test_watch_identity_is_stable_across_frames_via_iou() -> None:
    mon = monitor()
    drive(mon, payload([det("bottle", 500, 400, 540, 440), det("person", 300, 200, 400, 600)]), 2)
    first = next(iter(mon.watches.values())).instance_id
    drive(mon, payload([det("bottle", 504, 403, 545, 444), det("person", 302, 201, 401, 601)]), 3)
    assert len(mon.watches) == 1
    assert next(iter(mon.watches.values())).instance_id == first


# -------------------------------------------------------------------- containment

def test_object_inside_box_emits_its_own_event() -> None:
    mon = monitor()
    events = drive(
        mon,
        payload([det("experiment_box", 400, 350, 700, 550), det("bottle", 500, 400, 540, 440), det("person", 300, 200, 400, 600)]),
        2,
    )
    kinds = [e.get("kind") for e in events]
    assert "OBJECT_INSIDE_BOX" in kinds
    ev = next(e for e in events if e["kind"] == "OBJECT_INSIDE_BOX")
    assert ev["objectClass"] == "bottle"
    assert ev["containerClass"] == "experiment_box"
    assert ev["containmentScore"] >= 0.6
    watch = next(iter(mon.watches.values()))
    assert watch.inside_container is True
    assert watch.containment_score >= 0.6
    # containment is a separate fact from attendance, not a competing state
    assert watch.state == ATTENDED, "person is right there, so the object is attended"


def test_object_outside_box_does_not_report_containment() -> None:
    mon = monitor()
    events = drive(
        mon,
        payload([det("experiment_box", 400, 350, 700, 550), det("bottle", 50, 50, 90, 90), det("person", 300, 200, 400, 600)]),
        2,
    )
    assert "OBJECT_INSIDE_BOX" not in [e.get("kind") for e in events]
    watch = next(iter(mon.watches.values()))
    assert watch.inside_container is False


# -------------------------------------------------------------- the attended path

def test_person_in_proximity_keeps_object_attended() -> None:
    mon = monitor()
    # Bottle and person both near the centre; diagonal of 1280x720 is ~1468.
    drive(
        mon,
        payload([det("experiment_box", 400, 350, 700, 550), det("bottle", 500, 400, 540, 440), det("person", 520, 380, 620, 600)]),
        4,
    )
    watch = next(iter(mon.watches.values()))
    assert watch.state == ATTENDED
    assert watch.person_id is not None
    assert watch.person_free_ms == 0


# ----------------------------------------------------------- the unattended flow

def test_full_flow_bottle_in_box_person_leaves_becomes_unattended() -> None:
    """person + box -> bottle placed inside -> person walks away -> UNATTENDED."""
    mon = monitor()
    box = det("experiment_box", 400, 350, 700, 550)
    bottle = det("bottle", 500, 400, 540, 440)
    near_person = det("person", 460, 360, 560, 620)   # close to the bottle
    far_person = det("person", 1150, 40, 1270, 300)  # walked to the far corner

    # 1. person + empty box
    drive(mon, payload([box, near_person]), 1)
    assert mon.watches == {}, "no object yet, nothing to watch"

    # 2. person places the bottle inside the box
    drive(mon, payload([box, bottle, near_person]), 2)
    watch = next(iter(mon.watches.values()))
    assert watch.inside_container is True
    assert watch.state == ATTENDED

    # 3. person walks away; timer is wall-clock so it cannot elapse instantly
    drive(mon, payload([box, bottle, far_person]), 2)
    watch = next(iter(mon.watches.values()))
    assert watch.state == UNATTENDED, "walking away must flag unattended immediately"
    assert watch.person_id is None
    assert watch.inside_container is True, "containment survives the person leaving"
    assert mon.status()["unattendedCount"] == 1


def test_unattended_is_time_gated_not_frame_gated() -> None:
    """A 0ms timeout fires at once; a long timeout must NOT fire on frame count."""
    tight = monitor(unattended_timeout_ms=0)
    box, bottle, far = det("experiment_box", 400, 350, 700, 550), det("bottle", 500, 400, 540, 440), det("person", 1150, 40, 1270, 300)
    drive(tight, payload([box, bottle, far]), 1)
    assert next(iter(tight.watches.values())).state == UNATTENDED

    slow = monitor(unattended_timeout_ms=600_000)
    drive(slow, payload([box, bottle, far]), 10)  # 10 ticks, still well under 10 minutes
    assert next(iter(slow.watches.values())).state != UNATTENDED


def test_person_returning_clears_unattended() -> None:
    mon = monitor(unattended_timeout_ms=0)
    box, bottle = det("experiment_box", 400, 350, 700, 550), det("bottle", 500, 400, 540, 440)
    far, near = det("person", 1150, 40, 1270, 300), det("person", 460, 360, 560, 620)
    drive(mon, payload([box, bottle, far]), 1)
    watch = next(iter(mon.watches.values()))
    assert watch.state == UNATTENDED
    drive(mon, payload([box, bottle, near]), 2)
    watch = next(iter(mon.watches.values()))
    assert watch.state == ATTENDED
    assert watch.person_free_since_ms is None


def test_unattended_alert_is_raised_for_known_object() -> None:
    mon = monitor(unattended_timeout_ms=0)
    box, bottle, far = det("experiment_box", 400, 350, 700, 550), det("bottle", 500, 400, 540, 440), det("person", 1150, 40, 1270, 300)
    drive(mon, payload([box, bottle, far]), 2)
    alerts = [a for a in mon.alerts.active() if a.hazard_type == "unattended_object"]
    assert alerts, "an unattended known object must raise an alert"
    assert alerts[0].object == "bottle"


def test_containment_alert_dedupes_by_instance() -> None:
    mon = monitor(unattended_timeout_ms=0)
    box, bottle, far = det("experiment_box", 400, 350, 700, 550), det("bottle", 500, 400, 540, 440), det("person", 1150, 40, 1270, 300)
    for _ in range(5):
        drive(mon, payload([box, bottle, far]), 1)
    alerts = [a for a in mon.alerts.active() if a.hazard_type == "unattended_object"]
    assert len(alerts) == 1, "one physical object must not spam alerts"


# ------------------------------------------------------------------- honest edges

def test_stale_feed_freezes_watches() -> None:
    mon = monitor()
    box, bottle, far = det("experiment_box", 400, 350, 700, 550), det("bottle", 500, 400, 540, 440), det("person", 1150, 40, 1270, 300)
    drive(mon, payload([box, bottle, far]), 1)
    before = next(iter(mon.watches.values())).state
    mon._provider = lambda: {"enabled": False, "frameWidth": None, "frameHeight": None, "detections": [], "unknownDetections": []}
    for _ in range(5):
        asyncio.run(mon.step())
    assert next(iter(mon.watches.values())).state == before
    assert mon.status()["unattendedCount"] == 0


def test_person_only_frame_reports_nothing() -> None:
    mon = monitor()
    drive(mon, payload([det("person", 300, 200, 400, 600)]), 3)
    assert mon.watches == {}


def test_two_objects_get_separate_alerts() -> None:
    mon = monitor(unattended_timeout_ms=0)
    box = det("experiment_box", 400, 350, 700, 550)
    far = det("person", 1150, 40, 1270, 300)
    drive(mon, payload([box, det("bottle", 450, 400, 490, 440), det("floating_tool", 600, 400, 650, 440), far]), 2)
    assert len(mon.watches) == 2
    assert mon.status()["unattendedCount"] == 2
