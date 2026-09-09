from __future__ import annotations

from pathlib import Path

from research_agent.api import ResearchAgent
from research_agent.core.store import ArtifactStore
from research_agent.schemas.workflow import DecisionInput


def _approve_g1(agent: ResearchAgent, state):
    gate = state.pending_gate
    assert gate is not None
    return agent.approve_gate(
        state.workspace_id,
        DecisionInput(
            request_id="m2b_approval_1",
            gate_id=gate.gate_id,
            artifact=gate.artifact,
            actor="user",
            action="approve",
        ),
    )


def test_s2_without_index_is_typed_block_and_does_not_change_workspace(fixture_repo: Path):
    agent = ResearchAgent(fixture_repo)
    state = agent.create_workspace("二维医学图像扩散生成", "medical_diffusion_2d")
    approved = _approve_g1(agent, state)

    result = agent.advance(state.workspace_id)

    assert (result.stage, result.status, result.reason) == ("S2", "blocked", "index_not_built")
    assert result.new_artifacts == ()
    assert agent.get_status(state.workspace_id) == approved


def test_s2_with_index_commits_idea_artifact_and_opens_g2(fixture_repo: Path):
    agent = ResearchAgent(fixture_repo)
    state = agent.create_workspace("二维医学图像扩散生成", "medical_diffusion_2d")
    approved = _approve_g1(agent, state)
    agent.build_index()

    result = agent.advance(state.workspace_id)

    assert result.status == "waiting_for_user"
    assert result.stage == "G2"
    assert result.pending_gate is not None
    assert result.new_artifacts == ()
    artifact = result.pending_gate.artifact
    assert artifact.artifact_id == "idea_draft"
    store = ArtifactStore(fixture_repo / "workspaces" / state.workspace_id)
    payload = store.read(artifact)
    assert payload["schema_version"] == "idea-draft-v1"
    assert payload["epistemic_status"] == "HYPOTHESIS"
    assert payload["workflow_advanced"] is True
    assert agent.get_status(state.workspace_id).pending_gate == result.pending_gate

    event_types = [event["payload"].get("type") for event in agent.get_events(state.workspace_id)]
    assert "S2Completed" in event_types
    assert "GateOpened" in event_types
    assert approved.stage == "S2"

    resumed = ResearchAgent(fixture_repo).advance(state.workspace_id)
    assert resumed.status == "waiting_for_user"
    assert resumed.pending_gate == result.pending_gate


def test_g2_approval_runs_lexical_s3_screening_and_opens_g3(fixture_repo: Path):
    agent = ResearchAgent(fixture_repo)
    state = agent.create_workspace("二维医学图像扩散生成", "medical_diffusion_2d")
    _approve_g1(agent, state)
    agent.build_index()
    g2 = agent.advance(state.workspace_id)
    assert g2.stage == "G2" and g2.pending_gate is not None

    approved = agent.approve_gate(
        state.workspace_id,
        DecisionInput(
            request_id="m2b_g2_approval_1",
            gate_id=g2.pending_gate.gate_id,
            artifact=g2.pending_gate.artifact,
            actor="user",
            action="approve",
        ),
    )
    # M1's persisted gate table keeps G2's immediate target at S4.  The
    # compatibility handler executes the bounded S3 screen from that state.
    assert (approved.stage, approved.status) == ("S4", "not_started")

    result = agent.advance(state.workspace_id)

    assert result.status == "waiting_for_user"
    assert result.stage == "G3"
    assert result.pending_gate is not None
    assert result.pending_gate.artifact.artifact_id == "core_paper_set"
    store = ArtifactStore(fixture_repo / "workspaces" / state.workspace_id)
    payload = store.read(result.pending_gate.artifact)
    assert payload["schema_version"] == "core-paper-set-v1"
    assert payload["status"] == "completed"
    assert payload["source_idea"]["artifact_id"] == "idea_draft"
    assert payload["core_candidate_count"] == len(payload["core_papers"])
    assert all(item["scope_status"] == "unreviewed" for item in payload["core_papers"])
    warnings = " ".join(payload["warnings"]).lower()
    assert "semantic" in warnings and "novelty" in warnings

    event_types = [event["payload"].get("type") for event in agent.get_events(state.workspace_id)]
    assert "S3Completed" in event_types
    assert "GateOpened" in event_types


def test_s3_reuses_persisted_idea_provenance_without_corpus_writes(fixture_repo: Path):
    agent = ResearchAgent(fixture_repo)
    state = agent.create_workspace("二维医学图像扩散生成", "medical_diffusion_2d")
    _approve_g1(agent, state)
    agent.build_index()
    g2 = agent.advance(state.workspace_id)
    assert g2.pending_gate is not None
    agent.approve_gate(
        state.workspace_id,
        DecisionInput(
            request_id="m2b_g2_approval_2",
            gate_id=g2.pending_gate.gate_id,
            artifact=g2.pending_gate.artifact,
            actor="user",
            action="approve",
        ),
    )
    corpus_before = {
        path.relative_to(fixture_repo).as_posix(): path.read_bytes()
        for path in (fixture_repo / "corpus").rglob("*")
        if path.is_file()
    }

    first = agent.advance(state.workspace_id)
    second = ResearchAgent(fixture_repo).advance(state.workspace_id)

    assert second == first
    corpus_after = {
        path.relative_to(fixture_repo).as_posix(): path.read_bytes()
        for path in (fixture_repo / "corpus").rglob("*")
        if path.is_file()
    }
    assert corpus_after == corpus_before
