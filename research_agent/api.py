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

    def build_index(self, snapshot_id: str | None = None) -> dict:
        """Build a derived index, without advancing any Workspace or Gate."""
        from research_agent.retrieval.index import LexicalIndex
        return LexicalIndex(self.repo_root).build(snapshot_id)

    def verify_index(self, index_id: str | None = None) -> dict:
        from research_agent.retrieval.index import LexicalIndex
        return LexicalIndex(self.repo_root).verify(index_id)

    def index_status(self, index_id: str | None = None) -> dict:
        from research_agent.retrieval.index import LexicalIndex
        return LexicalIndex(self.repo_root).status(index_id)

    def search_papers(
        self, query: str, *, index_id: str | None = None, limit: int = 50,
        per_channel: int = 500, conference: str | None = None,
        year_from: int | None = None, year_to: int | None = None, report: bool = False,
    ) -> dict:
        """Standalone exploratory search; does not perform S2 or approve G2."""
        from research_agent.retrieval.index import LexicalIndex
        from research_agent.retrieval.search import search
        from research_agent.retrieval.report import write_report
        if type(report) is not bool:
            raise ValueError("report must be a boolean")
        result = search(LexicalIndex(self.repo_root), query, index_id=index_id,
                        limit=limit, per_channel=per_channel, conference=conference,
                        year_from=year_from, year_to=year_to)
        if report:
            result["report"] = write_report(self.repo_root, result)
        return result
