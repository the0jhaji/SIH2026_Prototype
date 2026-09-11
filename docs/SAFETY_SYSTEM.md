# Astronaut Safety & Hazard Monitoring — `docs/SAFETY_SYSTEM.md`

Local-first, offline safety monitoring for BAS experiments. This is the **new
core** of the app (v0.2.0); the box-handling experiment is retained as a
decoupled demo.

## 1. Design rules

- **Perception ≠ decision-making.** The hazard engine turns *detections* into
  *assessments*; only the `SafetyMonitor` state machine decides the mission
  state. No LLM anywhere.
- **No silent fallback.** If the detector errors, status surfaces
  `detector_error` / `AI ENGINE ERROR <reason>` — the UI shows the reason, it
  never pretends a mock is a real model.
- **Honest claims only.** Outputs say "possible hazard / risk assessment /
  emergency candidate" — never a medical diagnosis. Earth escalation is
  **staged locally** (`EARTH_ESCALATION_PACKAGE_READY`), never claimed as
  transmitted.
- **Environment is configuration.** `ENVIRONMENT_MODE=microgravity` is an
  operational env var; it is never inferred from pixels.
- **Temporal gates.** One bad frame must never alarm: hazards confirm only
  after `SAFETY_PERSIST_FRAMES`, resolve only on fresh frames, and incidents
  need confirmed CRITICAL (or near-crew WARNING / EMERGENCY). A **stale** feed
  (camera off / detector down) retains the last scene and escalates nothing.

## 2. Components (`backend/app/safety/`)

| File | Responsibility |
| --- | --- |
| `hazards.json` / `hazards.py` | config-driven class → hazard metadata | no |
| `hazard_engine.py` | temporal trackers + microgravity risk scoring (`SceneAssessment`/`HazardAssessment`) |
| `monitor.py` | `SafetyMonitor` state machine (NORMAL…EMERGENCY, ACKNOWLEDGED, RESOLVED) |
| `emergency.py` | `EmergencyManager` — `POSSIBLE_INJURY`, `POSSIBLE_COLLISION`, `ASTRONAUT_DOWN`, `ASTRONAUT_UNOBSERVED`, `NO_MOTION`, `EMERGENCY_CANDIDATE` |
| `alert_manager.py` | `Alert` lifecycle: de-dupe by root-cause `key`, escalation-in-place, cooldown, ack |
| `incidents.py` | `IncidentLog` + evidence (frame/metadata) + `escalation.json` packaging |
| `transports.py` | `AlertTransport`: `LocalMissionControlTransport`, `FileTransport`, `FutureSpaceStationTransport` (NotImplementedError) |
| `safety_service.py` | orchestrator loop, WS broadcast, station alerts, escalation staging |

### Hazard engine (`hazard_engine.py`)

```
risk_score = base_risk * (0.6 + 0.4 * confidence)
           + min(microgravity_boost, environment.max_boost)
           + proximity_boost (near astronaut)
           + motion_boost    (moving toward astronaut)
clamped to [0, 1], mapped via risk_level_for():
    ≥ 0.80 CRITICAL   ≥ 0.55 WARNING   ≥ 0.30 CAUTION   else SAFE
```

- `HazardAssessment.hazard == False` (or unclassified) ⇒ no hazard claim.
- Unconfirmed hazards are capped at 0.54 → **a single frame can never exceed
  CAUTION**.
- `_near()` uses box overlap or edge-gap ≤ ½ the smaller box diagonal
  ("in the astronaut's vicinity").

### Monitor state machine (`monitor.py`)

`NORMAL → OBSERVING → CAUTION → WARNING → CRITICAL → EMERGENCY`. Confirmed
emergency dominates; an unconfirmed emergency candidate floors at WARNING;
otherwise the confirmed hazard level drives the state. Resolution requires
`resolve_cycles` consecutive *fresh* frames (`target_index == 0`), and only
transitions `RESOLVED` (then `NORMAL`). `ACKNOWLEDGED` survives equal/lower
risk and re-escalates on higher.

### Alerts (`alert_manager.py`)

Signals from confirmed hazards (CAUTION+) and confirmed emergencies are
deduplicated by `key` (`hazard:<object>:<type>`, `emergency:<event_type>`).
Escalations upgrade the *same* alert; resolved alerts are re-raised only after
`ALERT_COOLDOWN_MS`. A persistent hazard never spams the audio/console.

### Incidents + escalation (`incidents.py`)

- Created for: confirmed CRITICAL hazards, WARNING hazards **near** the
  astronaut, confirmed emergencies.
- On create: + evidence frame (`frame_<ts>.jpg` if camera streaming) +
  `metadata.json` (model version, detections, assessments) +
  `event.json`; station alert delivered to the transport; if
  `EARTH_ESCALATION_ENABLED` and severity ≥ `EARTH_ESCALATION_MIN_LEVEL`, an
  `escalation.json` package is staged (`status: READY`).
- Auto-resolved when the hazard key leaves the scene (`hazard:` triggers only;
  emergencies stay OPEN until human resolution). Reloaded from disk at boot.

### Emergency rules backend (`emergency.py`)

Tracks the astronaut box over frames:

- `ASTRONAUT_UNOBSERVED` after `absent_frames` of no `person`.
- `ASTRONAUT_DOWN` after the astronaut is *absent* for `2 × absent_frames`
  (assuming presence first).
- `NO_MOTION` after `static_frames` with near-zero center movement.
- `POSSIBLE_COLLISION` when a hazard is near + approaching the astronaut;
  `POSSIBLE_INJURY` when a collision-worth hazard overlaps heavily.
- `EMERGENCY_CANDIDATE` when confirmed hazards reach CRITICAL while the
  astronaut is in view.

Each required `EmergencyManager(..., absent_frames, static_frames)` and every
temporal counter is exercised by `backend/tests/test_safety.py`.

## 3. REST + WebSocket contract

REST: `GET /api/safety/status|snapshot|alerts|incidents|incidents/{id}|station|events|emergency`,
`POST /api/safety/start|stop`, `POST /api/safety/alerts/{id}/ack`.
Health: `GET /api/health` now also reports `mission_state` and
`safety_monitoring`.

WebSocket `/ws` on connect sends `{"type":"state"}` then
`{"type":"safety", "data": <snapshot>}`; each monitor cycle broadcasts
`{"type":"safety_event", "data": <event>}`. The snapshot shape is stable and
mirrors `SafetyService.snapshot()`.

## 4. Detection class → hazard mapping (config, not code)

`hazards.json` `classes` map class names to `{hazard, risk_level, base_risk,
microgravity_boost, proximity_boost, motion_boost, hazard_type,
recommended_action, reason}`. `person` + the legacy boxes are benign
(`hazard: false`). Missing classes are reported `UNCLASSIFIED` with **no**
hazard claim. The mock-detector scenes drive deterministic demos/e2e:

| Scene | Detections |
| --- | --- |
| `bas` (default) | `person`, `experiment_box`, `red_box`, `yellow_box`, `target_area` |
| `empty` | none |
| `space_station` | `person`, `floating_tool`, `loose_cable` |
| `safety_sequence` | `person`, `floating_tool`, `loose_cable`, then `person` clears (→ `ASTRONAUT_UNOBSERVED` / `ASTRONAUT_DOWN`) |

`MOCK_SCENE` is threaded through `DetectionService` → `create_detector(...,
scene=...)` — the real-YOLO path is untouched.

## 5. Running & testing

```powershell
# fully synthetic demo (no webcam, no weights)
.\backend\run_mock_demo.ps1

# backend suite: 114 tests including 19 safety scenarios
backend\.venv\Scripts\python.exe -m pytest backend\tests -q

# frontend parity + static checks
cd frontend
npm run test:reducer
npm run lint
npm run build
```

Safety-only e2e: `backend/tests/test_safety.py` (harness:
`StubDetection` + `build_safety_client(tmp_path, stub, ...)`; never touches a
camera device).

## 6. Honest limitations / next phases

- A generic pretrained YOLO does **not** recognise the BAS safety classes;
  the `space_station`/`safety_sequence` scenes currently come from the mock
  and heuristic detectors only. Training a `floating_tool`/`loose_cable`/… /
  astronaut model is the Phase 4C path (see `models/detection/README.md`).
- Rolling pre/post-event frame buffers and real spacecraft/Earth comms are
  explicitly out of scope — staged packages and the station console are the
  prototype's honest ceiling.