"""AttendanceMonitor state-machine tests: held → released → unattended flow,
reach geometry, dead-feed freeze, false-positive rejection, and alert dedup.

All tests drive ``_reconcile`` / ``step`` synchronously — no real camera,
no real event loop, no real WebSocket.
"""

import asyncio

from app.attendance import (
    AttendanceMonitor,
    GONE,
    HELD,
    POSSIBLY_HELD,
    RELEASED,
    UNKNOWN,
    UNATTENDED,
)

PERSON = {"class_name": "person", "confidence": 0.9, "x1": 100, "y1": 50, "x2": 200, "y2": 350, "timestamp": 0}


def _det(**kw):
    """Near-reach unknown object (center inside the reach region)."""
    kw.setdefault("instance_id", "unknown-1")
    kw.setdefault("confidence", 0.8)
    x1, y1, x2, y2 = kw.pop("x1", 140), kw.pop("y1", 110), kw.pop("x2", 160), kw.pop("y2", 130)
    return {"class_name": "unknown_object", **kw, "x1": x1, "y1": y1, "x2": x2, "y2": y2, "timestamp": 0}


def _live(unknowns, persons=None):
    return {
        "enabled": True,
        "frameWidth": 640,
        "frameHeight": 480,
        "detections": persons or [PERSON],
        "unknownDetections": unknowns,
        "rawDetections": [],
        "rawUnknownDetections": [],
        "inferenceMs": 1,
        "inferenceStatus": "ok",
        "error": None,
    }


STALE = {"enabled": False, "frameWidth": None}


def _make(provider, **kw):
    return AttendanceMonitor(
        provider,
        poll_ms=10,
        held_frames=kw.get("held_frames", 3),
        unattended_frames=kw.get("unattended_frames", 3),
        track_lost_frames=kw.get("track_lost_frames", 5),
        arm_reach=kw.get("arm_reach", 0.6),
        upper_body=kw.get("upper_body", 0.45),
    )


async def _drive(m, payloads):
    it = iter(payloads)
    m._provider = lambda: next(it, payloads[-1])
    for _ in payloads:
        await m.step()


def test_reach_region_geometry():
    from app.attendance import _in_reach_region

    pw = 100
    margin = 0.6 * pw           # 60
    bottom = 50 + 300 * 0.45    # 185
    # Inside: head-region center
    assert _in_reach_region({"x1": 150, "y1": 120, "x2": 170, "y2": 140}, PERSON, 0.6, 0.45)
    # Outside: leg-level object — same horizontal position, well below upper-body band
    assert not _in_reach_region({"x1": 150, "y1": 290, "x2": 170, "y2": 310}, PERSON, 0.6, 0.45)
    # Outside: object to the astronaut's far left
    assert not _in_reach_region({"x1": 350, "y1": 100, "x2": 390, "y2": 140}, PERSON, 0.6, 0.45)


def test_full_held_released_unattended_gone_cycle():
    m = _make(_det(), held_frames=2, unattended_frames=2, track_lost_frames=3)

    # Build the timeline: near for several frames, then far, then absent.
    near_det = _det()
    far_det = _det(x1=140, y1=290, x2=160, y2=310, instance_id="unknown-1")
    payloads = [
        _live([_det()]),                          # 1: POSSIBLY_HELD
        _live([near_det]),                        # 2: still POSSIBLY_HELD
        _live([near_det]),                        # 3: HELD (3rd consecutive near)
        _live([far_det]),                         # 4: leaves reach → RELEASED
        _live([far_det]),                         # 5: still far → UNATTENDED
        _live([far_det]),                         # 6: stays UNATTENDED
        _live([]),                                # 7-11: absent → track lost
        _live([]), _live([]), _live([]), _live([]),
    ]

    asyncio.run(_drive(m, payloads))

    assert m.watches == {}
    transitions = [t["to"] for t in m.latest()["events"] if t.get("kind") == "ATTENDANCE_TRANSITION"]
    for expected in (POSSIBLY_HELD, HELD, RELEASED, UNATTENDED, GONE):
        assert expected in transitions, f"{expected} not in {transitions}"


def test_unattended_raises_alert_and_gone_resolves_it():
    m = _make(_det(), held_frames=2, unattended_frames=2, track_lost_frames=5)

    payloads = [
        _live([_det()]),             # 1: POSSIBLY_HELD
        _live([_det()]),             # 2: stays POSSIBLY_HELD (seen resets on transition)
        _live([_det(x1=140, y1=290, x2=160, y2=310)]),  # 3: RELEASED
        _live([_det(x1=140, y1=290, x2=160, y2=310)]),  # 4: still RELEASED
        _live([_det(x1=140, y1=290, x2=160, y2=310)]),  # 5: UNATTENDED → alert raised
        _live([]),  # 6-10: gone, waits for track loss
        _live([]), _live([]), _live([]), _live([]),
    ]

    async def run():
        await _drive(m, payloads)

    asyncio.run(run())

    # After track lost the watch is gone and the alert resolved event was emitted.
    assert "unknown-1" not in m.watches
    kinds = [ev.get("kind") for ev in m.latest()["events"]]
    assert "ATTENDANCE_ALERT_RAISED" in kinds
    assert "ATTENDANCE_ALERT_RESOLVED" in kinds


def test_stale_feed_freezes_transitions():
    near = _det()
    payloads = [
        _live([near]),  # 1: POSSIBLY_HELD
        _live([near]),  # 2: stays POSSIBLY_HELD
        STALE,          # 3: freeze — object gone but tick did NOT advance
        _live([near]),  # 4: still POSSIBLY_HELD (no expiry because no frames counted)
    ]

    m = _make(near, held_frames=5, unattended_frames=5, track_lost_frames=5)

    async def run():
        await _drive(m, payloads)

    asyncio.run(run())

    assert len(m.watches) == 1
    assert m.watches["unknown-1"].state == POSSIBLY_HELD


def test_object_by_legs_never_may_be_held():
    legs_det = _det(x1=140, y1=290, x2=160, y2=310)
    m = _make(legs_det, held_frames=2, unattended_frames=5, track_lost_frames=10)
    payloads = [_live([legs_det]) for _ in range(8)]

    asyncio.run(_drive(m, payloads))

    assert m.watches["unknown-1"].state == UNKNOWN  # never left it


def test_multiple_unknown_objects_are_tracked_independently():
    m = _make(_det(), held_frames=10, unattended_frames=5, track_lost_frames=5)
    obj_a = _det(instance_id="obj-A", x1=140, y1=110, x2=160, y2=130)
    obj_b = _det(instance_id="obj-B", x1=140, y1=290, x2=160, y2=310)  # near legs
    payloads = [_live([obj_a, obj_b]) for _ in range(6)]

    asyncio.run(_drive(m, payloads))

    assert m.watches["obj-A"].state == POSSIBLY_HELD
    assert m.watches["obj-B"].state == UNKNOWN


def test_acknowledge_alert():
    m = _make(_det(), held_frames=1, unattended_frames=1, track_lost_frames=5)
    payloads = [
        _live([_det()]),  # 1: POSSIBLY_HELD
        _live([_det(x1=140, y1=290, x2=160, y2=310)]),  # 2: RELEASED → UNATTENDED (1 frame)
        _live([_det(x1=140, y1=290, x2=160, y2=310)]),
    ]

    asyncio.run(_drive(m, payloads))

    active = m.alerts.active()
    assert len(active) == 1
    alert_id = active[0].id
    result = asyncio.run(m.acknowledge(alert_id, note="secured"))
    assert result["found"] is True
    assert result["alert"].acknowledged is True


def test_status_reports_counts():
    m = _make(_det(), held_frames=1, unattended_frames=1, track_lost_frames=5)
    st = m.status()
    assert st["monitoring"] is False
    assert st["objects"] == 0
    assert st["thresholds"]["heldFrames"] == 1


def test_configurable_thresholds_control_transition_speed():
    """Tight thresholds reach speed dependent states quickly; loose ones never
    leave POSSIBLY_HELD within the same frame budget."""
    fast = _make(_det(), held_frames=1, unattended_frames=1, track_lost_frames=5)
    slow = _make(_det(), held_frames=10, unattended_frames=10, track_lost_frames=5)
    seq = [_live([_det()]) for _ in range(3)] + [
        _live([_det(x1=140, y1=290, x2=160, y2=310)]) for _ in range(3)
    ]

    asyncio.run(_drive(fast, seq))
    assert fast.watches["unknown-1"].state == UNATTENDED

    asyncio.run(_drive(slow, seq))
    slow_states = [t["state"] for t in slow.watches["unknown-1"].transitions]
    assert HELD not in slow_states
    assert slow.watches["unknown-1"].state == RELEASED


def test_alert_is_deduplicated_across_unattended_frames():
    """Half a dozen unattended frames raise exactly one alert, not one per frame."""
    m = _make(_det(), held_frames=1, unattended_frames=1, track_lost_frames=5)
    far = _det(x1=140, y1=290, x2=160, y2=310)
    seq = [
        _live([_det()]),  # POSSIBLY_HELD
        _live([_det()]),  # HELD
        _live([far]),     # RELEASED
        _live([far]),     # UNATTENDED (alert raised)
        _live([far]),     # still unattended -> deduped
        _live([far]),     # still unattended -> deduped
    ]

    asyncio.run(_drive(m, seq))

    raised = [e for e in m.latest()["events"] if e.get("kind") == "ATTENDANCE_ALERT_RAISED"]
    assert len(raised) == 1
    assert len(m.alerts.active()) == 1


def test_reset_clears_watches_events_and_alerts():
    m = _make(_det(), held_frames=1, unattended_frames=1, track_lost_frames=5)
    far = _det(x1=140, y1=290, x2=160, y2=310)
    seq = [_live([_det()]), _live([_det()]), _live([far]), _live([far])]

    asyncio.run(_drive(m, seq))
    assert m.watches and m.alerts.active()

    m.reset()
    assert m.watches == {}
    assert m.latest()["events"] == []
    assert m.alerts.active() == []