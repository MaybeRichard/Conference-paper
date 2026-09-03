from __future__ import annotations

from pathlib import Path
import shutil

import pytest
from pydantic import ValidationError

from research_agent.core.errors import ConflictError, GateError
from research_agent.core.gates import gate_for
from research_agent.core.state_machine import next_stage_for_gate
from research_agent.core.store import ArtifactStore
from research_agent.core.workspace import WorkspaceService
from research_agent.schemas.base import ArtifactRef
from research_agent.schemas.workflow import DecisionInput
from tests.agent.corpus_factory import make_corpus


DOMAIN_RELATIVE = Path("domains/medical_diffusion_2d/domain.yaml")


def prepare_repo(tmp_path: Path) -> Path:
    repo = make_corpus(tmp_path / "repo")
    source = Path(__file__).resolve().parents[2] / DOMAIN_RELATIVE
    destination = repo / DOMAIN_RELATIVE
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return repo


def decision_for(state, request_id: str = "approval_1") -> DecisionInput:
    gate = state.pending_gate
    assert gate is not None
    return DecisionInput(
        request_id=request_id,
        gate_id=gate.gate_id,
        artifact=gate.artifact,
        actor="user",
        action="approve",
    )


def test_valid_g1_approval_advances_and_survives_restart(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    service = WorkspaceService(repo)
    created = service.create("二维医学图像扩散生成", "medical_diffusion_2d")
    decision = decision_for(created)

    advanced = service.approve(created.workspace_id, decision)
    assert advanced.stage == "S2"
    assert advanced.status == "not_started"
    assert advanced.pending_gate is None
    assert WorkspaceService(repo).get_state(created.workspace_id) == advanced
    assert WorkspaceService(repo).get_gate(created.workspace_id) is None

    events = [
        entry["payload"]
        for entry in ArtifactStore(repo / "workspaces" / created.workspace_id).events()
    ]
    assert sum(event["type"] == "GateApproved" for event in events) == 1


def test_identical_request_retry_returns_original_result_without_duplicate_event(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    service = WorkspaceService(repo)
    created = service.create("二维生成", "medical_diffusion_2d")
    decision = decision_for(created, "approval_retry")

    first = service.approve(created.workspace_id, decision)
    second = WorkspaceService(repo).approve(created.workspace_id, decision)
    assert second == first
    events = [
        entry["payload"]
        for entry in ArtifactStore(repo / "workspaces" / created.workspace_id).events()
    ]
    assert sum(event["type"] == "GateApproved" for event in events) == 1


def test_same_request_id_with_different_payload_conflicts(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    service = WorkspaceService(repo)
    created = service.create("二维生成", "medical_diffusion_2d")
    original = decision_for(created, "approval_conflict")
    service.approve(created.workspace_id, original)
    changed = original.model_copy(update={"gate_id": "different_gate"})

    with pytest.raises(ConflictError):
        WorkspaceService(repo).approve(created.workspace_id, changed)


def test_stale_approval_cannot_advance(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    service = WorkspaceService(repo)
    created = service.create("二维医学图像扩散生成", "medical_diffusion_2d")
    old = service.get_gate(created.workspace_id)
    assert old is not None
    service.revise_brief(
        created.workspace_id,
        old.artifact,
        {"topic": "二维病灶条件生成"},
    )

    with pytest.raises(GateError):
        service.approve(
            created.workspace_id,
            DecisionInput(
                request_id="approval_stale",
                gate_id=old.gate_id,
                artifact=old.artifact,
                actor="user",
                action="approve",
            ),
        )


def test_wrong_hash_version_gate_and_second_request_are_rejected(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    service = WorkspaceService(repo)
    created = service.create("二维生成", "medical_diffusion_2d")
    gate = created.pending_gate
    assert gate is not None

    wrong_ref = ArtifactRef(
        artifact_id=gate.artifact.artifact_id,
        version=gate.artifact.version,
        sha256="0" * 64,
    )
    with pytest.raises(GateError):
        service.approve(
            created.workspace_id,
            DecisionInput(
                request_id="wrong_hash",
                gate_id=gate.gate_id,
                artifact=wrong_ref,
                actor="user",
                action="approve",
            ),
        )

    service.approve(created.workspace_id, decision_for(created, "approval_ok"))
    with pytest.raises(GateError):
        service.approve(created.workspace_id, decision_for(created, "approval_second"))


def test_non_user_actor_is_rejected_by_contract():
    ref = ArtifactRef(artifact_id="brief", version=1, sha256="0" * 64)
    gate = gate_for("G1", ref)
    with pytest.raises(ValidationError):
        DecisionInput(
            request_id="request_1",
            gate_id=gate.gate_id,
            artifact=ref,
            actor="agent",
            action="approve",
        )


def test_gate_transition_table_is_explicit():
    assert next_stage_for_gate("G1") == "S2"
    assert next_stage_for_gate("G2") == "S4"
    assert next_stage_for_gate("G3") == "S7"
    assert next_stage_for_gate("G4") == "S11"
    with pytest.raises(GateError):
        next_stage_for_gate("S2")


def test_gate_decision_holds_workspace_lock_across_validation_and_commit(
    tmp_path: Path,
    monkeypatch,
):
    import threading
    import time
    import research_agent.core.workspace as workspace_module

    repo = prepare_repo(tmp_path)
    service = WorkspaceService(repo)
    created = service.create("二维生成", "medical_diffusion_2d")
    decision = decision_for(created, "approval_atomic")
    entered = threading.Event()
    release = threading.Event()
    approval_errors: list[BaseException] = []
    revision_errors: list[BaseException] = []
    revision_finished = threading.Event()
    original_validate = workspace_module.validate_approval

    def paused_validate(state, supplied):
        gate = original_validate(state, supplied)
        entered.set()
        assert release.wait(2)
        return gate

    monkeypatch.setattr(workspace_module, "validate_approval", paused_validate)

    def approve_worker():
        try:
            WorkspaceService(repo).approve(created.workspace_id, decision)
        except BaseException as exc:
            approval_errors.append(exc)

    def revise_worker():
        try:
            WorkspaceService(repo).revise_brief(
                created.workspace_id,
                created.pending_gate.artifact,
                {"topic": "并发修订"},
            )
        except BaseException as exc:
            revision_errors.append(exc)
        finally:
            revision_finished.set()

    approval_thread = threading.Thread(target=approve_worker)
    approval_thread.start()
    assert entered.wait(2)
    revision_thread = threading.Thread(target=revise_worker)
    revision_thread.start()
    time.sleep(0.05)
    assert not revision_finished.is_set(), "revision crossed an in-flight Gate decision"
    release.set()
    approval_thread.join(2)
    revision_thread.join(2)

    assert approval_errors == []
    assert len(revision_errors) == 1
    assert isinstance(revision_errors[0], GateError)
    assert WorkspaceService(repo).get_state(created.workspace_id).stage == "S2"


def test_approval_recovers_if_process_fails_after_commit_marker(tmp_path: Path, monkeypatch):
    repo = prepare_repo(tmp_path)
    created = WorkspaceService(repo).create("二维生成", "medical_diffusion_2d")
    decision = decision_for(created, "approval_crash")
    original_commit = ArtifactStore.commit
    crashed = False

    def crash_once(self, artifact_id, version, payload, events, transaction_id):
        nonlocal crashed
        if artifact_id.startswith("decision_") and not crashed:
            crashed = True

            def hook(checkpoint):
                if checkpoint == "after_commit_publish":
                    raise RuntimeError("injected approval crash")

            self._fault_hook = hook
        return original_commit(self, artifact_id, version, payload, events, transaction_id)

    monkeypatch.setattr(ArtifactStore, "commit", crash_once)
    with pytest.raises(RuntimeError, match="injected approval crash"):
        WorkspaceService(repo).approve(created.workspace_id, decision)

    recovered = WorkspaceService(repo).approve(created.workspace_id, decision)
    assert recovered.stage == "S2"
    events = [
        entry["payload"]
        for entry in ArtifactStore(repo / "workspaces" / created.workspace_id).events()
    ]
    assert sum(event["type"] == "GateApproved" for event in events) == 1
