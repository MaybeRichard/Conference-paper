"""State and decision data only; transition execution belongs to later tasks."""
from typing import Literal, Self

from pydantic import StrictBool, model_validator

from research_agent.schemas.base import ArtifactRef, Contract, Identifier, NonEmptyText

GateKind = Literal["G1", "G2", "G3", "G4"]
Stage = Literal["S0", "S1", "G1", "S2", "S3", "G2", "S4", "S5", "S6",
                "G3", "S7", "S8", "S9", "S10", "G4", "S11"]
StageStatus = Literal["not_started", "running", "completed", "waiting_for_user",
                      "blocked", "needs_revision", "superseded", "failed"]


class DecisionInput(Contract):
    request_id: Identifier
    gate_id: Identifier
    artifact: ArtifactRef
    actor: Literal["user"]
    action: Literal["approve"]


class GateRecord(Contract):
    gate_id: Identifier
    kind: GateKind
    artifact: ArtifactRef
    status: Literal["pending", "approved", "superseded"] = "pending"


class WorkspaceState(Contract):
    workspace_id: Identifier
    snapshot_id: Identifier
    stage: Stage
    status: StageStatus
    pending_gate: GateRecord | None = None

    @model_validator(mode="after")
    def validate_pending_gate(self) -> Self:
        gate = self.pending_gate
        if self.status == "waiting_for_user":
            if gate is None or gate.status != "pending" or self.stage != gate.kind:
                raise ValueError("Waiting state requires its matching pending gate")
        elif gate is not None:
            raise ValueError("Only a waiting state may carry a pending gate")
        return self


class TaskResult(Contract):
    status: Literal["completed", "blocked", "failed"]
    outputs: tuple[ArtifactRef, ...] = ()
    reason: NonEmptyText | None = None
    cache_hit: StrictBool = False

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if self.status == "completed":
            if self.reason is not None:
                raise ValueError("Completed tasks cannot carry a failure reason")
        elif self.outputs or self.cache_hit or self.reason is None:
            raise ValueError("Incomplete tasks require a reason and no completed outputs/cache hit")
        return self
