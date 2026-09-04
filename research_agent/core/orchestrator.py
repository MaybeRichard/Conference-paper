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

        # S0/S1 are performed deterministically by WorkspaceService.create().
        # M1 intentionally has no S2 retrieval handler. Returning a blocked run
        # is evidence of the missing capability, not a synthetic empty result.
        return RunResult(
            workspace_id=state.workspace_id,
            stage=state.stage,
            status="blocked",
            reason="stage_handler_not_installed",
        )
