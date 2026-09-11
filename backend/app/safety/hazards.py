"""Hazard knowledge base: config-driven class -> hazard metadata mapping.

Class names are DATA (``hazards.json``), never hardcoded. A detected class
absent from the KB is reported as UNCLASSIFIED — the system never claims a
hazard for a class it does not know.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .. import config

_HERE = Path(__file__).resolve().parent
DEFAULT_HAZARDS_FILE = _HERE / "hazards.json"

RiskLevel = Literal["SAFE", "CAUTION", "WARNING", "HIGH", "CRITICAL"]


class EnvironmentSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    score_boost: float = 0.0
    max_boost: float = 0.0
    note: str = ""


class HazardSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = "object"
    hazard: bool = False
    risk_level: RiskLevel = "SAFE"
    base_risk: float = 0.0
    hazard_type: Optional[str] = None
    hazard_types: list[str] = Field(default_factory=list)
    microgravity_boost: float = 0.0
    motion_boost: float = 0.0
    proximity_boost: float = 0.05
    recommended_action: str = ""
    reason: str = ""


class HazardKnowledgeBase(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemaVersion: str = "1.0"
    id: str = ""
    description: str = ""
    environment: dict[str, EnvironmentSpec] = Field(default_factory=dict)
    classes: dict[str, HazardSpec] = Field(default_factory=dict)

    def spec_for(self, class_name: str) -> Optional[HazardSpec]:
        """KB entry for a class, or ``None`` when the class is not assessed."""
        return self.classes.get(class_name)

    def known_classes(self) -> list[str]:
        return sorted(self.classes)


def load_hazards(path: Optional[Path | str] = None) -> HazardKnowledgeBase:
    """Load the canonical hazard KB. ``path``/``HAZARDS_FILE`` override the
    canonical ``backend/app/safety/hazards.json`` (mirrors the experiment-file
    override convention)."""
    candidate: Optional[Path] = None
    if path:
        candidate = Path(path)
    elif config.HAZARDS_FILE:
        candidate = Path(config.HAZARDS_FILE)
    file = candidate if candidate and candidate.exists() else DEFAULT_HAZARDS_FILE
    raw = json.loads(file.read_text(encoding="utf-8"))
    return HazardKnowledgeBase(**raw)