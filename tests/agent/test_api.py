from __future__ import annotations

from pathlib import Path

from research_agent.api import ResearchAgent
from research_agent.schemas.workflow import DecisionInput


def decision_for(state, request_id: str = "user_approval_1") -> DecisionInput:
    gate = state.pending_gate
    assert gate is not None
    return DecisionInput(
        request_id=request_id,
        gate_id=gate.gate_id,
        artifact=gate.artifact,
        actor="user",
        action="approve",
    )


def test_m1_stops_honestly_at_missing_retrieval(fixture_repo: Path):
    agent = ResearchAgent(fixture_repo)
    workspace = agent.create_workspace(
        "二维医学图像扩散生成", "medical_diffusion_2d"
    )
    gate = agent.get_pending_gate(workspace.workspace_id)
    assert gate == workspace.pending_gate

    waiting = agent.advance(workspace.workspace_id)
    assert waiting.workspace_id == workspace.workspace_id
    assert waiting.stage == "G1"
    assert waiting.status == "waiting_for_user"
    assert waiting.pending_gate == gate
    assert waiting.new_artifacts == ()
    assert agent.get_status(workspace.workspace_id) == workspace

    approved = agent.approve_gate(
        workspace.workspace_id,
        decision_for(workspace),
    )
    assert (approved.stage, approved.status, approved.pending_gate) == (
        "S2",
        "not_started",
        None,
    )

    reopened = ResearchAgent(fixture_repo)
    result = reopened.advance(workspace.workspace_id)
    assert (result.stage, result.status, result.reason) == (
        "S2",
        "blocked",
        "stage_handler_not_installed",
    )
    assert result.pending_gate is None
    assert result.new_artifacts == ()
    assert reopened.get_status(workspace.workspace_id) == approved


def test_api_revises_brief_and_rebinds_g1(fixture_repo: Path):
    agent = ResearchAgent(fixture_repo)
    workspace = agent.create_workspace("二维生成", "medical_diffusion_2d")
    old_gate = workspace.pending_gate
    assert old_gate is not None

    revised = agent.revise_brief(
        workspace.workspace_id,
        old_gate.artifact,
        {
            "topic": "二维病灶条件生成",
            "scope": {"allow_independent_ct_mri_slices": False},
        },
    )

    assert revised.stage == "G1"
    assert revised.status == "waiting_for_user"
    assert revised.pending_gate is not None
    assert revised.pending_gate.gate_id != old_gate.gate_id
    assert revised.pending_gate.artifact.version == 2
    assert agent.get_pending_gate(workspace.workspace_id) == revised.pending_gate


def test_validate_workspace_checks_all_committed_artifacts(fixture_repo: Path):
    agent = ResearchAgent(fixture_repo)
    workspace = agent.create_workspace("二维生成", "medical_diffusion_2d")

    report = agent.validate_workspace(workspace.workspace_id)

    assert report.valid is True
    assert report.checked_artifacts >= 2
    assert report.errors == ()


def test_validate_workspace_reports_corruption_without_claiming_validity(
    fixture_repo: Path,
):
    agent = ResearchAgent(fixture_repo)
    workspace = agent.create_workspace("二维生成", "medical_diffusion_2d")
    gate = workspace.pending_gate
    assert gate is not None
    artifact = (
        fixture_repo
        / "workspaces"
        / workspace.workspace_id
        / "artifacts"
        / gate.artifact.artifact_id
        / f"v{gate.artifact.version:08d}.json"
    )
    artifact.write_text("{}", encoding="utf-8")

    report = ResearchAgent(fixture_repo).validate_workspace(workspace.workspace_id)

    assert report.valid is False
    assert report.checked_artifacts == 0
    assert report.errors == ("integrity_error",)


def test_api_exposes_read_only_corpus_and_event_views(fixture_repo: Path):
    agent = ResearchAgent(fixture_repo)
    verification = agent.verify_corpus()
    workspace = agent.create_workspace("二维生成", "medical_diffusion_2d")

    assert verification.snapshot_id == "snapshot_test"
    events = agent.get_events(workspace.workspace_id)
    assert events
    assert any(item["payload"].get("type") == "WorkspaceCreated" for item in events)
