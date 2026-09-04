"""Workflow state, decision, task, run and validation contracts."""
from typing import Any, Literal, Self

from pydantic import Field, StrictBool, model_validator

from research_agent.schemas.base import ArtifactRef, Contract, Identifier, NonEmptyText

GateKind = Literal["G1", "G2", "G3", "G4"]
Stage = Literal[
    "S0",
    "S1",
    "G1",
    "S2",
    "S3",
    "G2",
    "S4",
    "S5",
    "S6",
    "G3",
    "S7",
    "S8",
    "S9",
    "S10",
    "G4",
    "S11",
]
StageStatus = Literal[
    "not_started",
    "running",
    "completed",
    "waiting_for_user",
    "blocked",
    "needs_revision",
    "superseded",
    "failed",
]
RunStatus = Literal["completed", "waiting_for_user", "blocked", "failed"]


class DecisionInput(Contract):
    request_id: Identifier
    gate_id: Identifier
    artifact: ArtifactRef
    actor: Literal["user"]
    action: Literal["approve"]


class BriefRevisionInput(Contract):
    expected: ArtifactRef
    changes: dict[str, Any]

    @model_validator(mode="after")
    def validate_changes(self) -> Self:
        if not self.changes:
            raise ValueError("Brief revision changes cannot be empty")
        return self


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
            raise ValueError(
                "Incomplete tasks require a reason and no completed outputs/cache hit"
            )
        return self


class RunResult(Contract):
    workspace_id: Identifier
    stage: Stage
    status: RunStatus
    reason: NonEmptyText | None = None
    pending_gate: GateRecord | None = None
    new_artifacts: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_run_result(self) -> Self:
        if self.status == "waiting_for_user":
            if self.pending_gate is None or self.reason is not None or self.new_artifacts:
                raise ValueError(
                    "A waiting run requires one Gate and no reason or new Artifacts"
                )
        elif self.status in {"blocked", "failed"}:
            if self.reason is None or self.pending_gate is not None or self.new_artifacts:
                raise ValueError(
                    "A blocked/failed run requires a reason and no Gate or new Artifacts"
                )
        elif self.reason is not None or self.pending_gate is not None:
            raise ValueError("A completed run cannot carry a reason or pending Gate")
        return self


class ValidationReport(Contract):
    valid: StrictBool
    checked_artifacts: int = Field(strict=True, ge=0)
    errors: tuple[NonEmptyText, ...] = ()

    @model_validator(mode="after")
    def validate_report(self) -> Self:
        if self.valid and self.errors:
            raise ValueError("A valid report cannot contain errors")
        if not self.valid and not self.errors:
            raise ValueError("An invalid report requires at least one error code")
        return self
