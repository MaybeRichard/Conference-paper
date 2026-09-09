"""Proposal-stage persistence using exact user-approved upstream versions."""
from __future__ import annotations

from pydantic import ValidationError

from research_agent.core.errors import IntegrityError, UnsupportedStage
from research_agent.core.gates import gate_for
from research_agent.core.serialization import digest
from research_agent.core.store import ArtifactStore
from research_agent.schemas.base import ArtifactRef
from research_agent.schemas.workflow import GateRecord, RunResult, WorkspaceState


def approved_source(store, workspace_id: str, kind: str, artifact_id: str):
    for event in reversed(store.events()):
        payload = event["payload"]
        if payload.get("type") != "GateApproved" or payload.get("workspace_id") != workspace_id:
            continue
        try:
            gate = GateRecord.model_validate(payload["gate"])
        except (KeyError, ValidationError):
            raise IntegrityError("Invalid approved Gate record") from None
        if gate.kind != kind:
            continue
        if gate.status != "approved" or gate.artifact.artifact_id != artifact_id or gate.gate_id != gate_for(gate.kind, gate.artifact).gate_id:
            raise IntegrityError("Approved Gate is bound to an unexpected artifact")
        if payload.get("decision", {}).get("artifact") != gate.artifact.model_dump(mode="json"):
            raise IntegrityError("Approval decision does not match Gate artifact")
        store.read(gate.artifact)
        return gate.artifact
    return None


def run_final_package(service, workspace_id: str) -> RunResult:
    path = service._workspace_path(workspace_id)
    store = ArtifactStore(path)
    with store.locked():
        state, config_ref, brief_ref = service._state_context_with_store(workspace_id, path, store)
        if state.stage != "S11" or state.status != "not_started":
            return RunResult(workspace_id=workspace_id, stage=state.stage, status="blocked", reason="s11_not_ready")
        source_ref = approved_source(store, workspace_id, "G4", "idea_proposal_set")
        if source_ref is None:
            return RunResult(workspace_id=workspace_id, stage="S11", status="blocked", reason="approved_proposals_missing")
        source = store.read(source_ref)
        if source.get("schema_version") != "idea-proposal-set-v1" or source.get("status") != "completed" or source.get("source_search", {}).get("snapshot_id") != state.snapshot_id:
            raise IntegrityError("Approved proposal content does not match Workspace")
        payload = {"schema_version": "research-package-v1", "status": "draft", "scientific_validation": "not_performed",
                   "source_proposal": source_ref.model_dump(mode="json"), "proposal_set": source,
                   "limitations": source["limitations"], "snapshot_id": state.snapshot_id}
        ref = ArtifactRef(artifact_id="research_package", version=1, sha256=digest(payload))
        finished = WorkspaceState(workspace_id=workspace_id, snapshot_id=state.snapshot_id, stage="S11", status="completed")
        events = [
            {"type": "ResearchPackageCreated", "workspace_id": workspace_id, "artifact": ref.model_dump(mode="json"), "source_proposal": source_ref.model_dump(mode="json")},
            {"type": "WorkspaceStateChanged", "workspace_id": workspace_id, "state": finished.model_dump(mode="json"), "effective_config": config_ref.model_dump(mode="json"), "research_brief": brief_ref.model_dump(mode="json")},
        ]
        actual = store.commit("research_package", 1, payload, events, f"s11_{workspace_id}_{source_ref.version}")
        if actual != ref:
            raise IntegrityError("Final package reference changed")
        service._write_projection(path, finished, config_ref, brief_ref)
        return RunResult(workspace_id=workspace_id, stage="S11", status="completed", new_artifacts=(ref,))


def export_workspace(service, workspace_id: str) -> dict:
    from research_agent.ideation.proposal_report import write_proposal_report
    path = service._workspace_path(workspace_id)
    store = ArtifactStore(path)
    with store.locked():
        state, _, _ = service._state_context_with_store(workspace_id, path, store)
        if state.stage == "G4" and state.pending_gate is not None:
            ref = state.pending_gate.artifact
        elif state.stage == "S11" and state.status == "completed":
            matches = [event["payload"] for event in store.events()
                       if event["payload"].get("type") == "ResearchPackageCreated" and event["payload"].get("workspace_id") == workspace_id]
            if not matches:
                raise IntegrityError("Completed Workspace has no research package")
            ref = ArtifactRef.model_validate(matches[-1]["artifact"])
        else:
            raise UnsupportedStage("Proposal export is available at G4 or after final packaging")
        payload = store.read(ref)
    return write_proposal_report(service.repo_root, payload)
