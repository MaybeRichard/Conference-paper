"""Locked user actions for an existing Workspace."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import ValidationError

from research_agent.core.domain_profile import BriefScopeBoundary, DomainProfile
from research_agent.core.errors import ConflictError, GateError, IntegrityError
from research_agent.core.gates import gate_for, validate_approval
from research_agent.core.serialization import digest
from research_agent.core.state_machine import next_stage_for_gate
from research_agent.core.store import ArtifactStore
from research_agent.schemas.base import ArtifactRef
from research_agent.schemas.research import ResearchBrief
from research_agent.schemas.workflow import DecisionInput, WorkspaceState

_ALLOWED_REVISIONS = {"topic", "target_venue", "scope", "start_date", "end_date"}


class WorkspaceAccess(Protocol):
    def _workspace_path(self, workspace_id: str): ...

    def _state_context_with_store(
        self,
        workspace_id: str,
        path,
        store: ArtifactStore,
    ) -> tuple[WorkspaceState, ArtifactRef, ArtifactRef]: ...

    def _write_projection(
        self,
        path,
        state: WorkspaceState,
        config_ref: ArtifactRef,
        brief_ref: ArtifactRef,
    ) -> None: ...


def _brief_from_payload(payload: dict[str, Any]) -> ResearchBrief:
    fields = ResearchBrief.model_fields
    try:
        return ResearchBrief.model_validate({key: payload[key] for key in fields})
    except (KeyError, ValidationError):
        raise IntegrityError("Stored ResearchBrief is missing or invalid") from None


def approve_workspace(
    service: WorkspaceAccess,
    workspace_id: str,
    decision: DecisionInput,
    approval_validator: Callable[[WorkspaceState, DecisionInput], Any] = validate_approval,
) -> WorkspaceState:
    decision = DecisionInput.model_validate(decision)
    path = service._workspace_path(workspace_id)
    store = ArtifactStore(path)
    decision_payload = decision.model_dump(mode="json")

    with store.locked():
        state, config_ref, brief_ref = service._state_context_with_store(
            workspace_id, path, store
        )
        for envelope in store.events():
            payload = envelope["payload"]
            if (
                payload.get("type") != "GateApproved"
                or payload.get("request_id") != decision.request_id
            ):
                continue
            previous = payload.get("decision")
            if not isinstance(previous, dict) or digest(previous) != digest(decision_payload):
                raise ConflictError("Approval request ID was reused with different content")
            try:
                return WorkspaceState.model_validate(payload["result_state"])
            except (KeyError, ValidationError):
                raise IntegrityError("Stored approval result is invalid") from None

        gate = approval_validator(state, decision)
        advanced = WorkspaceState(
            workspace_id=workspace_id,
            snapshot_id=state.snapshot_id,
            stage=next_stage_for_gate(gate.kind),
            status="not_started",
            pending_gate=None,
        )
        approved_gate = gate.model_copy(update={"status": "approved"})
        approval_payload = {
            "decision": decision_payload,
            "approved_gate": approved_gate.model_dump(mode="json"),
            "result_state": advanced.model_dump(mode="json"),
            "effective_config": config_ref.model_dump(mode="json"),
            "research_brief": brief_ref.model_dump(mode="json"),
        }
        events = [
            {
                "type": "GateApproved",
                "workspace_id": workspace_id,
                "request_id": decision.request_id,
                "decision": decision_payload,
                "gate": approved_gate.model_dump(mode="json"),
                "result_state": advanced.model_dump(mode="json"),
            },
            {
                "type": "WorkspaceStateChanged",
                "workspace_id": workspace_id,
                "state": advanced.model_dump(mode="json"),
                "effective_config": config_ref.model_dump(mode="json"),
                "research_brief": brief_ref.model_dump(mode="json"),
            },
        ]
        store.commit(
            f"decision_{decision.request_id}",
            1,
            approval_payload,
            events,
            decision.request_id,
        )
        service._write_projection(path, advanced, config_ref, brief_ref)
        return advanced


def revise_workspace_brief(
    service: WorkspaceAccess,
    workspace_id: str,
    expected: ArtifactRef,
    changes: dict,
) -> WorkspaceState:
    expected = ArtifactRef.model_validate(expected)
    if not isinstance(changes, dict) or not changes:
        raise GateError("ResearchBrief revision must contain explicit changes")
    unknown = set(changes) - _ALLOWED_REVISIONS
    if unknown:
        raise GateError("ResearchBrief revision contains immutable or unknown fields")

    path = service._workspace_path(workspace_id)
    store = ArtifactStore(path)
    with store.locked():
        state, config_ref, brief_ref = service._state_context_with_store(
            workspace_id, path, store
        )
        gate = state.pending_gate
        if state.stage != "G1" or state.status != "waiting_for_user" or gate is None:
            raise GateError("ResearchBrief can only be revised at pending G1")
        if expected != gate.artifact or brief_ref != gate.artifact:
            raise GateError("ResearchBrief revision targets a stale Artifact")

        current = _brief_from_payload(store.read(brief_ref))
        update = current.model_dump(mode="json")
        if "scope" in changes:
            scope_change = changes["scope"]
            if not isinstance(scope_change, dict):
                raise GateError("scope revision must be an object")
            update["scope"] = {**update["scope"], **scope_change}
        for key in _ALLOWED_REVISIONS - {"scope"}:
            if key in changes:
                update[key] = changes[key]

        config = store.read(config_ref)
        try:
            profile = DomainProfile.model_validate(
                {key: config[key] for key in ("domain", "target_venue", "scope", "policies")}
            )
            revised = ResearchBrief.model_validate(update)
        except (KeyError, ValidationError):
            raise GateError(
                "ResearchBrief revision violates the approved domain boundary"
            ) from None
        if revised.domain != profile.domain or revised.snapshot_id != state.snapshot_id:
            raise GateError("ResearchBrief cannot change domain or corpus snapshot")
        if revised.target_venue != profile.target_venue:
            raise GateError("M1 cannot change the frozen target-venue profile")
        try:
            boundary = {key: revised.scope[key] for key in BriefScopeBoundary.model_fields}
            BriefScopeBoundary.model_validate(boundary)
        except (KeyError, ValidationError):
            raise GateError(
                "ResearchBrief revision cannot enable 2.5D/3D or leave the profile"
            ) from None

        version = brief_ref.version + 1
        revised_payload = revised.model_dump(mode="json")
        revised_payload["supersedes"] = brief_ref.model_dump(mode="json")
        revised_ref = ArtifactRef(
            artifact_id="research_brief",
            version=version,
            sha256=digest(revised_payload),
        )
        new_gate = gate_for("G1", revised_ref)
        new_state = WorkspaceState(
            workspace_id=workspace_id,
            snapshot_id=state.snapshot_id,
            stage="G1",
            status="waiting_for_user",
            pending_gate=new_gate,
        )
        superseded = gate.model_copy(update={"status": "superseded"})
        transaction_id = (
            "revise_"
            + digest(
                {
                    "expected": expected.model_dump(mode="json"),
                    "revised": revised_payload,
                }
            )[:24]
        )
        events = [
            {
                "type": "GateSuperseded",
                "workspace_id": workspace_id,
                "gate": superseded.model_dump(mode="json"),
            },
            {
                "type": "ResearchBriefRevised",
                "workspace_id": workspace_id,
                "previous": brief_ref.model_dump(mode="json"),
                "current": revised_ref.model_dump(mode="json"),
            },
            {
                "type": "GateOpened",
                "workspace_id": workspace_id,
                "gate": new_gate.model_dump(mode="json"),
            },
            {
                "type": "WorkspaceStateChanged",
                "workspace_id": workspace_id,
                "state": new_state.model_dump(mode="json"),
                "effective_config": config_ref.model_dump(mode="json"),
                "research_brief": revised_ref.model_dump(mode="json"),
            },
        ]
        committed = store.commit(
            "research_brief",
            version,
            revised_payload,
            events,
            transaction_id,
        )
        if committed != revised_ref:
            raise IntegrityError("Revised ResearchBrief reference changed during commit")
        service._write_projection(path, new_state, config_ref, revised_ref)
        return new_state
