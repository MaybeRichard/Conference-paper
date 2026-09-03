"""Pure workflow transition rules shared by services and later orchestration."""
from __future__ import annotations

from typing import cast

from research_agent.core.errors import GateError
from research_agent.schemas.workflow import GateKind, Stage

_GATE_TARGETS: dict[GateKind, Stage] = {
    "G1": "S2",
    "G2": "S4",
    "G3": "S7",
    "G4": "S11",
}


def next_stage_for_gate(kind: str) -> Stage:
    """Return the only legal stage reached by approving a user Gate."""
    if kind not in _GATE_TARGETS:
        raise GateError("Unknown Gate kind; workflow cannot advance")
    return _GATE_TARGETS[cast(GateKind, kind)]
