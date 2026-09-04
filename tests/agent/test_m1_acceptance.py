from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_agent.api import ResearchAgent
from research_agent.core.errors import GateError
from research_agent.core.store import ArtifactStore
from research_agent.schemas.workflow import DecisionInput


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _repository_hashes_outside_runtime(repo: Path) -> dict[str, str]:
    return {
        path.relative_to(repo).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(repo.rglob("*"))
        if path.is_file() and "workspaces" not in path.relative_to(repo).parts
    }


def test_create_wait_approve_reopen_and_block_leave_corpus_unchanged(
    fixture_repo: Path,
):
    corpus = fixture_repo / "corpus"
    corpus_before = _tree_hashes(corpus)
    repository_before = _repository_hashes_outside_runtime(fixture_repo)

    agent = ResearchAgent(fixture_repo)
    state = agent.create_workspace(
        "二维医学图像扩散生成",
        "medical_diffusion_2d",
    )
    assert state.stage == "G1"
    assert state.status == "waiting_for_user"
    assert agent.advance(state.workspace_id).status == "waiting_for_user"
    gate = agent.get_pending_gate(state.workspace_id)
    assert gate is not None

    approved = agent.approve_gate(
        state.workspace_id,
        DecisionInput(
            request_id="acceptance_approval_1",
            gate_id=gate.gate_id,
            artifact=gate.artifact,
            actor="user",
            action="approve",
        ),
    )
    assert (approved.stage, approved.status, approved.pending_gate) == (
        "S2",
        "not_started",
        None,
    )

    reopened = ResearchAgent(fixture_repo)
    assert reopened.get_status(state.workspace_id) == approved
    blocked = reopened.advance(state.workspace_id)
    assert (blocked.stage, blocked.status, blocked.reason) == (
        "S2",
        "blocked",
        "stage_handler_not_installed",
    )
    assert blocked.new_artifacts == ()
    assert reopened.get_status(state.workspace_id) == approved
    assert reopened.validate_workspace(state.workspace_id).valid is True

    assert _tree_hashes(corpus) == corpus_before
    assert _repository_hashes_outside_runtime(fixture_repo) == repository_before


def test_revised_g1_preserves_history_and_rejects_stale_approval(
    fixture_repo: Path,
):
    agent = ResearchAgent(fixture_repo)
    state = agent.create_workspace("二维生成", "medical_diffusion_2d")
    old_gate = agent.get_pending_gate(state.workspace_id)
    assert old_gate is not None

    revised = agent.revise_brief(
        state.workspace_id,
        old_gate.artifact,
        {
            "topic": "二维病灶条件生成",
            "scope": {"allow_independent_ct_mri_slices": False},
        },
    )
    new_gate = revised.pending_gate
    assert new_gate is not None
    assert new_gate.gate_id != old_gate.gate_id
    assert new_gate.artifact.version == old_gate.artifact.version + 1

    with pytest.raises(GateError):
        agent.approve_gate(
            state.workspace_id,
            DecisionInput(
                request_id="stale_acceptance_approval",
                gate_id=old_gate.gate_id,
                artifact=old_gate.artifact,
                actor="user",
                action="approve",
            ),
        )

    events = agent.get_events(state.workspace_id)
    event_types = [event["payload"].get("type") for event in events]
    assert "ResearchBriefRevised" in event_types
    assert event_types.count("GateOpened") == 2
    assert ArtifactStore(
        fixture_repo / "workspaces" / state.workspace_id
    ).read(old_gate.artifact)["topic"] == "二维生成"


def test_partial_event_tail_is_recovered_during_workspace_reopen(
    fixture_repo: Path,
):
    agent = ResearchAgent(fixture_repo)
    state = agent.create_workspace("二维生成", "medical_diffusion_2d")
    workspace = fixture_repo / "workspaces" / state.workspace_id
    log = workspace / "events.jsonl"
    original = log.read_bytes()
    assert original.endswith(b"\n")
    log.write_bytes(original[:-7])

    reopened = ResearchAgent(fixture_repo)
    assert reopened.get_status(state.workspace_id) == state
    assert log.read_bytes() == original
    assert list((workspace / "recovery" / "faults").glob("events-*.jsonl"))


def test_damaged_committed_artifact_is_reported_invalid(
    fixture_repo: Path,
):
    agent = ResearchAgent(fixture_repo)
    state = agent.create_workspace("二维生成", "medical_diffusion_2d")
    workspace = fixture_repo / "workspaces" / state.workspace_id
    artifact = workspace / "artifacts" / "research_brief" / "v00000001.json"
    envelope = json.loads(artifact.read_text(encoding="utf-8"))
    envelope["payload"]["topic"] = "tampered"
    artifact.write_text(json.dumps(envelope), encoding="utf-8")

    report = ResearchAgent(fixture_repo).validate_workspace(state.workspace_id)
    assert report.valid is False
    assert report.checked_artifacts == 0
    assert report.errors == ("integrity_error",)
