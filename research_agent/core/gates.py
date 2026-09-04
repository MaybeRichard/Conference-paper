"""Deterministic Gate identity and approval validation."""
from __future__ import annotations

from research_agent.core.errors import GateError
from research_agent.core.serialization import digest
from research_agent.schemas.base import ArtifactRef
from research_agent.schemas.workflow import DecisionInput, GateKind, GateRecord, WorkspaceState


def gate_for(kind: GateKind, artifact: ArtifactRef) -> GateRecord:
    """Bind a Gate to one immutable Artifact version and hash."""
    suffix = digest({"kind": kind, "artifact": artifact.model_dump(mode="json")})[:20]
    return GateRecord(gate_id=f"gate_{kind.lower()}_{suffix}", kind=kind, artifact=artifact)


def validate_approval(state: WorkspaceState, decision: DecisionInput) -> GateRecord:
    """Reject stale, mismatched, automated or repeated Gate approvals."""
    gate = state.pending_gate
    if state.status != "waiting_for_user" or gate is None or gate.status != "pending":
        raise GateError("Workspace has no pending user Gate")
    if state.stage != gate.kind:
        raise GateError("Workspace stage and pending Gate do not match")
    if decision.actor != "user" or decision.action != "approve":
        raise GateError("Only an explicit user approval can advance a Gate")
    if decision.gate_id != gate.gate_id or decision.artifact != gate.artifact:
        raise GateError("Approval targets a stale or different Gate Artifact")
    return gate
