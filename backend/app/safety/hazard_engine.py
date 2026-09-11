"""Hazard assessment / risk engine.

Turns raw object detections into a structured hazard assessment per object,
using temporal confirmation so a single bad frame cannot trigger an alarm:

    detection appears for one frame  -> candidate (capped at CAUTION)
    detection persists               -> confirmed hazard (full risk score)
    detection approaches astronaut   -> risk boosted (proximity + motion)
    detection disappears             -> resolves after SAFETY_RESOLVE_FRAMES
    feed goes stale (camera off)     -> last known scene is retained, marked
                                        stale; nothing is resolved out of thin air

Risk score = base_risk(from KB) * confidence_weight + microgravity boost +
proximity boost + motion boost, clamped to [0, 1] and mapped to a level
(SAFE/CAUTION/WARNING/CRITICAL). Microgravity is ENVIRONMENT_MODE operational
configuration — never inferred from pixels.
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .. import config
from .hazards import HazardKnowledgeBase, RiskLevel, load_hazards

BOX_KEYS = ("x1", "y1", "x2", "y2")


def risk_level_for(score: float) -> RiskLevel:
    """Score -> severity level. Kept in one place so the monitor and the UI
    use the same boundaries (0.3/0.55/0.8)."""
    if score >= 0.8:
        return "CRITICAL"
    if score >= 0.55:
        return "WARNING"
    if score >= 0.3:
        return "CAUTION"
    return "SAFE"


class HazardAssessment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    object: str
    confidence: float
    hazard: bool
    hazard_type: Optional[str] = None
    risk_level: RiskLevel = "SAFE"
    risk_score: float = 0.0
    confirmed: bool = False
    frames_persisted: int = 0
    near_astronaut: bool = False
    proximity: str = "FAR"  # NEAR | FAR | UNKNOWN_ASTRONAUT
    moving_toward_astronaut: bool = False
    reason: str = ""
    recommended_action: str = ""
    unclassified: bool = False
    timestamp: int = 0
    position: Dict[str, int] = Field(default_factory=dict)
    velocity: Optional[Dict[str, float]] = None


class SceneAssessment(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    timestamp: int
    stale: bool = False
    environment_mode: str = "microgravity"
    assessments: List[HazardAssessment] = Field(default_factory=list)
    hazards: List[HazardAssessment] = Field(default_factory=list)
    top_hazard: Optional[HazardAssessment] = None
    overall_risk_score: float = 0.0
    overall_risk_level: RiskLevel = "SAFE"
    astronaut_in_view: bool = False
    astronaut_box: Optional[dict] = None
    unclassified: List[str] = Field(default_factory=list)

    @property
    def has_active_hazards(self) -> bool:
        return any(a.confirmed and a.hazard for a in self.assessments)

    @property
    def has_candidates(self) -> bool:
        return any(not a.confirmed and a.hazard for a in self.assessments)


def _box_center(box: dict) -> tuple[float, float]:
    return ((box["x1"] + box["x2"]) / 2.0, (box["y1"] + box["y2"]) / 2.0)


def _box_diagonal(box: dict) -> float:
    import math

    return math.hypot(box["x2"] - box["x1"], box["y2"] - box["y1"])


def _best_per_class(detections: list[dict]) -> dict[str, dict]:
    best: dict[str, dict] = {}
    for d in detections:
        name = d.get("class_name")
        if not name:
            continue
        conf = float(d.get("confidence", 0.0))
        if name not in best or conf > best[name]["confidence"]:
            best[name] = d
    return best


class HazardEngine:
    """Owns the temporal trackers and produces :class:`SceneAssessment`."""

    def __init__(
        self,
        knowledge_base: Optional[HazardKnowledgeBase] = None,
        *,
        environment_mode: str = "microgravity",
        persist_frames: int = 2,
        resolve_frames: int = 2,
        stale_after_ms: int = 5000,
    ) -> None:
        self.kb = knowledge_base or load_hazards()
        self.environment = environment_mode
        self.persist_frames = max(1, persist_frames)
        self.resolve_frames = max(1, resolve_frames)
        self.stale_after_ms = stale_after_ms
        self._persist: Dict[str, int] = {}
        self._gone: Dict[str, int] = {}
        self._centers: Dict[str, Deque[tuple[float, float]]] = {}
        self._last_scene: Optional[SceneAssessment] = None

    # -------------------------------------------------------------- tracking

    def reset(self) -> None:
        self._persist.clear()
        self._gone.clear()
        self._centers.clear()
        self._last_scene = None

    def _tick_tracker(self, seen: set[str]) -> None:
        for name in set(self._persist):
            if name not in seen:
                self._persist.pop(name, None)
                self._centers.pop(name, None)
                self._gone[name] = 0
        for name in seen:
            self._gone.pop(name, None)
            self._persist[name] = self._persist.get(name, 0) + 1

    def _box_history(self, name: str, center: tuple[float, float]) -> None:
        history = self._centers.setdefault(name, deque(maxlen=8))
        history.append(center)

    def _velocity(self, name: str) -> Optional[dict]:
        history = self._centers.get(name)
        if not history or len(history) < 2:
            return None
        (x0, y0) = history[-2]
        (x1, y1) = history[-1]
        return {
            "dx": round(x1 - x0, 2),
            "dy": round(y1 - y0, 2),
            "speed": round(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5, 2),
        }

    @staticmethod
    def _approaching(vel: Optional[dict], src: tuple[float, float], dst: tuple[float, float]) -> bool:
        if not vel:
            return False
        separation = (dst[0] - src[0], dst[1] - src[1])
        dot = vel["dx"] * separation[0] + vel["dy"] * separation[1]
        return dot > 0

    @staticmethod
    def _near(box_a: dict, box_b: dict) -> bool:
        """True when boxes overlap or their edge distance is a small fraction
        of the smaller box diagonal (a robust "in the astronaut's vicinity")."""
        dx_left = box_b["x2"] - box_a["x1"]
        dx_right = box_a["x2"] - box_b["x1"]
        dy_top = box_b["y2"] - box_a["y1"]
        dy_bottom = box_a["y2"] - box_b["y1"]
        inter_w = min(dx_left, dx_right)
        inter_h = min(dy_top, dy_bottom)
        if inter_w > 0 and inter_h > 0:
            return True
        diag = min(_box_diagonal(box_a), _box_diagonal(box_b))
        gap = min(
            abs(min(dx_left, dx_right)),
            abs(min(dy_top, dy_bottom)),
        )
        return diag > 0 and gap <= 0.5 * diag

    # -------------------------------------------------------------- scoring

    def _risk_score(self, spec, confidence: float, near: bool, approaching: bool) -> float:
        score = spec.base_risk * (0.6 + 0.4 * min(1.0, max(0.0, confidence)))
        if self.environment == "microgravity":
            # Microgravity is operational configuration (ENVIRONMENT_MODE) —
            # never inferred from pixels. The per-class ``microgravity_boost``
            # is clamped by the environment cap so boosts stay sane.
            env = self.kb.environment.get("microgravity")
            cap = env.max_boost if env else 0.2
            score += min(spec.microgravity_boost, cap)
        if near and spec.proximity_boost:
            score += spec.proximity_boost
        if approaching and spec.motion_boost:
            score += spec.motion_boost
        return round(min(1.0, score), 4)

    # -------------------------------------------------------------- assess

    def assess(self, payload: Optional[dict], now_ms: Optional[int] = None) -> SceneAssessment:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        if not payload or not payload.get("enabled") or payload.get("inferenceStatus") != "ok":
            return self._stale_scene(now)
        last_inf = payload.get("lastInferenceMs")
        if last_inf is None or now - int(last_inf) > self.stale_after_ms:
            return self._stale_scene(now)
        return self._assess_fresh(payload, now)

    def _stale_scene(self, now: int) -> SceneAssessment:
        if self._last_scene is not None:
            scene = self._last_scene.model_copy(deep=True)
            scene.stale = True
            scene.timestamp = now
            return scene
        return SceneAssessment(timestamp=now, stale=True, environment_mode=self.environment)

    def _assess_fresh(self, payload: dict, now: int) -> SceneAssessment:
        dets = payload.get("detections") or []
        frame_w = payload.get("frameWidth") or 0
        frame_h = payload.get("frameHeight") or 0
        best = _best_per_class(dets)

        astronaut_box = best.get("person") if "person" in best else None
        astronaut_center = _box_center(astronaut_box) if astronaut_box else None
        astronaut_in_view = astronaut_box is not None and astronaut_box.get("confidence", 0) >= 0.5

        seen = set(best)
        self._tick_tracker(seen)
        for name, box in best.items():
            self._box_history(name, _box_center(box))

        assessments: List[HazardAssessment] = []
        unclassified: List[str] = []
        for name in sorted(best):
            box = best[name]
            conf = float(box.get("confidence", 0.0))
            spec = self.kb.spec_for(name)
            pos = {key: int(box.get(key, 0)) for key in BOX_KEYS}
            if spec is None:
                unclassified.append(name)
                assessments.append(
                    HazardAssessment(
                        object=name,
                        confidence=conf,
                        hazard=False,
                        hazard_type=None,
                        risk_level="SAFE",
                        risk_score=0.0,
                        confirmed=False,
                        frames_persisted=self._persist.get(name, 1),
                        near_astronaut=False,
                        proximity="FAR",
                        reason="Class not present in the hazard knowledge base; no hazard claim is made.",
                        recommended_action="Review object",
                        unclassified=True,
                        timestamp=now,
                        position=pos,
                    )
                )
                continue

            near = False
            approaching = False
            proximity = "FAR"
            if astronaut_box is not None and name != "person":
                near = self._near(box, astronaut_box)
                proximity = "NEAR" if near else "FAR"
                vel = self._velocity(name)
                if astronaut_center is not None:
                    approaching = self._approaching(vel, _box_center(box), astronaut_center)

            if not spec.hazard:
                level = risk_level_for(spec.base_risk)
                assessments.append(
                    HazardAssessment(
                        object=name,
                        confidence=conf,
                        hazard=False,
                        hazard_type=None,
                        risk_level=level,
                        risk_score=round(min(1.0, spec.base_risk), 4),
                        confirmed=self._persist.get(name, 0) >= self.persist_frames,
                        frames_persisted=self._persist.get(name, 1),
                        near_astronaut=near,
                        proximity=proximity if astronaut_box else "UNKNOWN_ASTRONAUT",
                        moving_toward_astronaut=approaching,
                        reason=spec.reason or "Known benign object in the environment.",
                        recommended_action=spec.recommended_action or "No action",
                        timestamp=now,
                        position=pos,
                        velocity=self._velocity(name),
                    )
                )
                continue

            frames = self._persist.get(name, 1)
            confirmed = frames >= self.persist_frames
            score = self._risk_score(spec, conf, near, approaching)
            if not confirmed:
                # Temporal confirmation gate: a one-frame blip can never exceed
                # CAUTION, so a single bad frame cannot raise a real alarm.
                score = min(score, 0.54)
            level = risk_level_for(score)
            assessments.append(
                HazardAssessment(
                    object=name,
                    confidence=conf,
                    hazard=True,
                    hazard_type=spec.hazard_type,
                    risk_level=level,
                    risk_score=score,
                    confirmed=confirmed,
                    frames_persisted=frames,
                    near_astronaut=near,
                    proximity=proximity if astronaut_box else "UNKNOWN_ASTRONAUT",
                    moving_toward_astronaut=approaching,
                    reason=spec.reason,
                    recommended_action=spec.recommended_action,
                    timestamp=now,
                    position=pos,
                    velocity=self._velocity(name),
                )
            )

        hazards = [a for a in assessments if a.hazard]
        top = max(hazards, key=lambda a: (a.risk_score, a.confirmed)) if hazards else None
        active = [a for a in hazards if a.confirmed]
        overall = max((a.risk_score for a in active), default=0.0)
        scene = SceneAssessment(
            timestamp=now,
            stale=False,
            environment_mode=self.environment,
            assessments=assessments,
            hazards=hazards,
            top_hazard=top,
            overall_risk_score=round(overall, 4),
            overall_risk_level=risk_level_for(overall),
            astronaut_in_view=astronaut_in_view,
            astronaut_box=astronaut_box,
            unclassified=unclassified,
        )
        self._last_scene = scene
        return scene

    # ------------------------------------------------------------ resolution

    def resolve_check(self, scene: SceneAssessment) -> Optional[int]:
        """Consecutive resolve-frames with no confirmed hazards. Returns the
        resolve count reached (>= resolve_frames) or ``None``. Only meaningful
        on a fresh, non-stale scene — a dead feed must never auto-resolve."""
        if scene.stale:
            return None
        if scene.has_active_hazards:
            self._clean_gone = 0
            return None
        cleaned = getattr(self, "_clean_gone", 0) + 1
        self._clean_gone = cleaned
        return cleaned if cleaned >= self.resolve_frames else None


def engine_from_config() -> HazardEngine:
    """Build the engine from env config (used by the app factory and tests)."""
    return HazardEngine(
        load_hazards(),
        environment_mode=config.ENVIRONMENT_MODE,
        persist_frames=config.SAFETY_PERSIST_FRAMES,
        resolve_frames=config.SAFETY_RESOLVE_FRAMES,
        stale_after_ms=config.SAFETY_STALE_MS,
    )