"""Deterministic M1 orchestration up to the first unimplemented research stage."""
from __future__ import annotations

from research_agent.core.workspace import WorkspaceService
from research_agent.schemas.workflow import RunResult


class Orchestrator:
    """Advance only stages with installed handlers; never synthesize missing work."""

    def __init__(self, workspaces: WorkspaceService) -> None:
        if not isinstance(workspaces, WorkspaceService):
            raise TypeError("workspaces must be a WorkspaceService")
        self.workspaces = workspaces

    def advance(self, workspace_id: str) -> RunResult:
        state = self.workspaces.get_state(workspace_id)
        if state.status == "waiting_for_user":
            return RunResult(
                workspace_id=state.workspace_id,
                stage=state.stage,
                status="waiting_for_user",
                pending_gate=state.pending_gate,
            )

        if state.stage == "S2" and state.status == "not_started":
            return self.workspaces.run_s2(workspace_id)

        # The persisted M1 gate table keeps G2's immediate target at S4.
        # S4/not_started is the compatibility entry point for the bounded
        # lexical S3 screen until that historical transition is migrated.
        if state.stage == "S4" and state.status == "not_started":
            return self.workspaces.run_s3(workspace_id)

        if state.stage == "S7" and state.status == "not_started":
            return self.workspaces.run_s7(workspace_id)

        if state.stage == "S11":
            if state.status == "completed":
                return RunResult(workspace_id=workspace_id, stage="S11", status="completed")
            if state.status == "not_started":
                from research_agent.core.proposal_workflow import run_final_package
                return run_final_package(self.workspaces, workspace_id)

        # S0/S1 are performed deterministically by WorkspaceService.create().
        # Any stage without an installed handler remains an honest block.
        return RunResult(
            workspace_id=state.workspace_id,
            stage=state.stage,
            status="blocked",
            reason="stage_handler_not_installed",
        )
