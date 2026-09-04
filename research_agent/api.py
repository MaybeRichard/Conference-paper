"""Stable Python API for the implemented M1 research workflow boundary."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from research_agent.adapters.corpus_adapter import CorpusAdapter, CorpusVerification
from research_agent.core.errors import IntegrityError, PathViolation
from research_agent.core.orchestrator import Orchestrator
from research_agent.core.paths import safe_child
from research_agent.core.store import ArtifactStore
from research_agent.core.workspace import WorkspaceService
from research_agent.schemas.base import ArtifactRef
from research_agent.schemas.workflow import (
    DecisionInput,
    GateRecord,
    RunResult,
    ValidationReport,
    WorkspaceState,
)

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")


class ResearchAgent:
    """Single public service façade for M1 state-changing operations."""

    def __init__(self, repo_root: Path) -> None:
        self._workspaces = WorkspaceService(repo_root)
        self.repo_root = self._workspaces.repo_root
        self._orchestrator = Orchestrator(self._workspaces)

    def _store(self, workspace_id: str) -> ArtifactStore:
        if not isinstance(workspace_id, str) or _IDENTIFIER.fullmatch(workspace_id) is None:
            raise IntegrityError("Unknown or invalid workspace ID")
        path = safe_child(self.repo_root, f"workspaces/{workspace_id}")
        if not path.is_dir() or path.is_symlink():
            raise IntegrityError("Workspace does not exist")
        return ArtifactStore(path)

    def verify_corpus(self, snapshot_id: str | None = None) -> CorpusVerification:
        return CorpusAdapter(self.repo_root).verify(snapshot_id)

    def create_workspace(self, topic: str, domain: str) -> WorkspaceState:
        return self._workspaces.create(topic, domain)

    def get_status(self, workspace_id: str) -> WorkspaceState:
        return self._workspaces.get_state(workspace_id)

    def get_pending_gate(self, workspace_id: str) -> GateRecord | None:
        return self._workspaces.get_gate(workspace_id)

    def approve_gate(
        self,
        workspace_id: str,
        decision: DecisionInput,
    ) -> WorkspaceState:
        return self._workspaces.approve(workspace_id, decision)

    def revise_brief(
        self,
        workspace_id: str,
        expected: ArtifactRef,
        changes: dict,
    ) -> WorkspaceState:
        return self._workspaces.revise_brief(workspace_id, expected, changes)

    def advance(self, workspace_id: str) -> RunResult:
        return self._orchestrator.advance(workspace_id)

    def get_events(self, workspace_id: str) -> list[dict[str, Any]]:
        self.get_status(workspace_id)
        return self._store(workspace_id).events()

    def validate_workspace(self, workspace_id: str) -> ValidationReport:
        """Validate committed storage and the derived Workspace projection.

        Integrity and path failures are returned as a report so callers can
        inspect a damaged Workspace without treating it as valid. Transient
        operational failures such as a busy lock still propagate with their
        original typed semantics.
        """
        try:
            self.get_status(workspace_id)
            store = self._store(workspace_id)
            store.recover()
            checked = len(list((store.root / "commits").glob("*.json")))
            return ValidationReport(
                valid=True,
                checked_artifacts=checked,
                errors=(),
            )
        except (IntegrityError, PathViolation) as error:
            return ValidationReport(
                valid=False,
                checked_artifacts=0,
                errors=(error.code,),
            )
