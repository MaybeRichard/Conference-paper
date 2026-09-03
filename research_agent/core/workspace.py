"""Persistent Workspace creation, ResearchBrief revision and user Gate approval."""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timezone
import os
from pathlib import Path
import re
import shutil
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
import yaml

from research_agent.adapters.corpus_adapter import CorpusAdapter
from research_agent.core.domain_profile import DomainProfile, load_domain_profile
from research_agent.core.errors import ConflictError, IntegrityError, PathViolation
from research_agent.core.gates import gate_for, validate_approval
from research_agent.core.paths import safe_child
from research_agent.core.serialization import digest
from research_agent.core.store import ArtifactStore
from research_agent.schemas.base import ArtifactRef
from research_agent.schemas.research import ResearchBrief
from research_agent.schemas.workflow import DecisionInput, GateRecord, WorkspaceState

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
_ALLOWED_REVISIONS = {"topic", "target_venue", "scope", "start_date", "end_date"}


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def _five_years_before(value: date) -> date:
    year = value.year - 5
    day = min(value.day, monthrange(year, value.month)[1])
    return date(year, value.month, day)


def _publish_projection(path: Path, payload: dict[str, Any]) -> None:
    content = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=True,
        default_flow_style=False,
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=".workspace-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _as_ref(value: object, *, field: str) -> ArtifactRef:
    try:
        return ArtifactRef.model_validate(value)
    except ValidationError:
        raise IntegrityError(f"Workspace event contains an invalid {field} reference") from None


def _brief_from_payload(payload: dict[str, Any]) -> ResearchBrief:
    fields = ResearchBrief.model_fields
    try:
        return ResearchBrief.model_validate({key: payload[key] for key in fields})
    except (KeyError, ValidationError):
        raise IntegrityError("Stored ResearchBrief is missing or invalid") from None


class WorkspaceService:
    """Create and reopen local Workspaces without modifying the corpus."""

    def __init__(self, repo_root: Path) -> None:
        root = Path(repo_root).absolute()
        try:
            if root.is_symlink() or not root.is_dir():
                raise PathViolation("Repository root must be a real directory")
            self.repo_root = root.resolve()
        except OSError:
            raise PathViolation("Cannot resolve repository root") from None

    @property
    def _workspaces_root(self) -> Path:
        return safe_child(self.repo_root, "workspaces")

    def _domain_path(self, domain: str) -> Path:
        if not isinstance(domain, str) or _IDENTIFIER.fullmatch(domain) is None:
            raise IntegrityError("Unknown or invalid domain profile")
        return safe_child(self.repo_root, f"domains/{domain}/domain.yaml")

    def _load_domain(self, domain: str) -> DomainProfile:
        return load_domain_profile(self._domain_path(domain))

    def _workspace_path(self, workspace_id: str) -> Path:
        if not isinstance(workspace_id, str) or _IDENTIFIER.fullmatch(workspace_id) is None:
            raise IntegrityError("Unknown or invalid workspace ID")
        root = self._workspaces_root
        path = safe_child(root, workspace_id)
        if not path.is_dir() or path.is_symlink():
            raise IntegrityError("Workspace does not exist")
        return path

    @staticmethod
    def _latest_context(events: list[dict[str, Any]], workspace_id: str) -> dict[str, Any]:
        contexts: list[dict[str, Any]] = []
        for envelope in events:
            payload = envelope.get("payload")
            if not isinstance(payload, dict):
                raise IntegrityError("Workspace event payload is invalid")
            if payload.get("type") == "WorkspaceStateChanged":
                if payload.get("workspace_id") != workspace_id:
                    raise IntegrityError("Workspace event identity mismatch")
                contexts.append(payload)
        if not contexts:
            raise IntegrityError("Workspace has no committed state")
        return contexts[-1]

    def _state_context_with_store(
        self,
        workspace_id: str,
        path: Path,
        store: ArtifactStore,
    ) -> tuple[WorkspaceState, ArtifactRef, ArtifactRef]:
        context = self._latest_context(store.events(), workspace_id)
        try:
            state = WorkspaceState.model_validate(context["state"])
        except (KeyError, ValidationError):
            raise IntegrityError("Workspace state event is invalid") from None
        if state.workspace_id != workspace_id:
            raise IntegrityError("Workspace state identity mismatch")
        config_ref = _as_ref(context.get("effective_config"), field="effective_config")
        brief_ref = _as_ref(context.get("research_brief"), field="research_brief")
        config = store.read(config_ref)
        brief = _brief_from_payload(store.read(brief_ref))
        if (
            config.get("snapshot_id") != state.snapshot_id
            or brief.snapshot_id != state.snapshot_id
            or brief.domain != config.get("domain")
        ):
            raise IntegrityError(
                "Workspace state disagrees with its frozen configuration or ResearchBrief"
            )
        self._write_projection(path, state, config_ref, brief_ref)
        return state, config_ref, brief_ref

    def _state_context(
        self,
        workspace_id: str,
    ) -> tuple[ArtifactStore, WorkspaceState, ArtifactRef, ArtifactRef]:
        path = self._workspace_path(workspace_id)
        store = ArtifactStore(path)
        with store.locked():
            state, config_ref, brief_ref = self._state_context_with_store(
                workspace_id, path, store
            )
        return store, state, config_ref, brief_ref

    @staticmethod
    def _projection_payload(
        state: WorkspaceState,
        config_ref: ArtifactRef,
        brief_ref: ArtifactRef,
    ) -> dict[str, Any]:
        return {
            "schema_version": "workspace-projection-v1",
            "state": state.model_dump(mode="json"),
            "effective_config": config_ref.model_dump(mode="json"),
            "research_brief": brief_ref.model_dump(mode="json"),
        }

    def _write_projection(
        self,
        path: Path,
        state: WorkspaceState,
        config_ref: ArtifactRef,
        brief_ref: ArtifactRef,
    ) -> None:
        projection = self._projection_payload(state, config_ref, brief_ref)
        destination = path / "workspace.yaml"
        expected = yaml.safe_dump(
            projection,
            allow_unicode=True,
            sort_keys=True,
            default_flow_style=False,
        ).encode("utf-8")
        try:
            if destination.is_file() and destination.read_bytes() == expected:
                return
        except OSError:
            pass
        _publish_projection(destination, projection)

    def create(
        self,
        topic: str,
        domain: str,
        snapshot_id: str | None = None,
    ) -> WorkspaceState:
        """Verify the full snapshot, freeze the profile, then publish a G1 Workspace."""
        verification = CorpusAdapter(self.repo_root).verify(snapshot_id)
        profile = self._load_domain(domain)
        today = _utc_today()
        workspace_id = f"ws_{today.strftime('%Y%m%d')}_{uuid4().hex[:12]}"
        workspaces_root = self._workspaces_root
        temporary = workspaces_root / f"_creating_{workspace_id}"
        final = workspaces_root / workspace_id
        published = False
        try:
            workspaces_root.mkdir(parents=True, exist_ok=True)
            if temporary.exists() or final.exists():
                raise ConflictError("Workspace ID collision")
            temporary.mkdir()
            store = ArtifactStore(temporary)
            profile_payload = profile.model_dump(mode="json")
            profile_payload.update(
                {
                    "snapshot_id": verification.snapshot_id,
                    "frozen_on": today.isoformat(),
                    "source_path": f"domains/{domain}/domain.yaml",
                }
            )
            config_ref = store.commit(
                "effective_config",
                1,
                profile_payload,
                [
                    {
                        "type": "EffectiveConfigFrozen",
                        "workspace_id": workspace_id,
                        "snapshot_id": verification.snapshot_id,
                    }
                ],
                f"create_config_{workspace_id}",
            )
            brief = ResearchBrief(
                topic=topic,
                domain=domain,
                target_venue=profile.target_venue,
                scope=profile.scope.model_dump(mode="json"),
                start_date=_five_years_before(today),
                end_date=today,
                snapshot_id=verification.snapshot_id,
                creation_basis="profile_and_user_input",
            )
            brief_payload = brief.model_dump(mode="json")
            brief_ref = ArtifactRef(
                artifact_id="research_brief",
                version=1,
                sha256=digest(brief_payload),
            )
            gate = gate_for("G1", brief_ref)
            state = WorkspaceState(
                workspace_id=workspace_id,
                snapshot_id=verification.snapshot_id,
                stage="G1",
                status="waiting_for_user",
                pending_gate=gate,
            )
            events = [
                {
                    "type": "WorkspaceCreated",
                    "workspace_id": workspace_id,
                    "snapshot_id": verification.snapshot_id,
                    "effective_config": config_ref.model_dump(mode="json"),
                    "research_brief": brief_ref.model_dump(mode="json"),
                },
                {
                    "type": "GateOpened",
                    "workspace_id": workspace_id,
                    "gate": gate.model_dump(mode="json"),
                },
                {
                    "type": "WorkspaceStateChanged",
                    "workspace_id": workspace_id,
                    "state": state.model_dump(mode="json"),
                    "effective_config": config_ref.model_dump(mode="json"),
                    "research_brief": brief_ref.model_dump(mode="json"),
                },
            ]
            committed_brief = store.commit(
                "research_brief",
                1,
                brief_payload,
                events,
                f"create_brief_{workspace_id}",
            )
            if committed_brief != brief_ref:
                raise IntegrityError("ResearchBrief reference changed during commit")
            self._write_projection(temporary, state, config_ref, brief_ref)
            os.replace(temporary, final)
            published = True
            return state
        finally:
            if not published and temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def get_state(self, workspace_id: str) -> WorkspaceState:
        return self._state_context(workspace_id)[1]

    def get_gate(self, workspace_id: str) -> GateRecord | None:
        return self.get_state(workspace_id).pending_gate

    def approve(self, workspace_id: str, decision: DecisionInput) -> WorkspaceState:
        from research_agent.core.workspace_actions import approve_workspace

        return approve_workspace(self, workspace_id, decision, validate_approval)

    def revise_brief(
        self,
        workspace_id: str,
        expected: ArtifactRef,
        changes: dict,
    ) -> WorkspaceState:
        from research_agent.core.workspace_actions import revise_workspace_brief

        return revise_workspace_brief(self, workspace_id, expected, changes)
