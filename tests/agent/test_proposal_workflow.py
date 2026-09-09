from pathlib import Path
import shutil

from research_agent.api import ResearchAgent
from research_agent.core.store import ArtifactStore
from research_agent.core.serialization import digest
from research_agent.schemas.base import ArtifactRef
from research_agent.schemas.workflow import DecisionInput
from tests.agent.retrieval_factory import make_retrieval_corpus


def approval(api, workspace_id):
    gate = api.get_pending_gate(workspace_id)
    return api.approve_gate(workspace_id, DecisionInput(
        request_id="fixture_" + gate.kind, gate_id=gate.gate_id,
        artifact=gate.artifact, actor="user", action="approve"))


def at_gate(tmp_path, target="G4"):
    repo = make_retrieval_corpus(tmp_path / "repo")
    domain = Path(__file__).resolve().parents[2] / "domains/medical_diffusion_2d/domain.yaml"
    (repo / "domains/medical_diffusion_2d").mkdir(parents=True)
    shutil.copyfile(domain, repo / "domains/medical_diffusion_2d/domain.yaml")
    api = ResearchAgent(repo)
    ws = api.create_workspace("二维医学图像扩散生成", "medical_diffusion_2d")
    api.build_index()
    for expected in ("G2", "G3", "G4"):
        approval(api, ws.workspace_id)
        result = api.advance(ws.workspace_id)
        assert result.stage == expected
        if expected == target:
            break
    return repo, api, ws.workspace_id, result.pending_gate


def test_g4_review_export_then_final_package_is_bound_to_approved_version(tmp_path):
    repo, api, workspace_id, gate = at_gate(tmp_path)
    export = api.export_workspace(workspace_id)
    assert "研究问题" in Path(export["report_path"]).read_text()
    # Export must not silently approve a research Gate.
    assert api.get_pending_gate(workspace_id) == gate
    approval(api, workspace_id)
    result = ResearchAgent(repo).advance(workspace_id)
    assert (result.stage, result.status) == ("S11", "completed")
    assert len(result.new_artifacts) == 1
    payload = ArtifactStore(repo / "workspaces" / workspace_id).read(result.new_artifacts[0])
    assert payload["source_proposal"] == gate.artifact.model_dump(mode="json")
    assert payload["proposal_set"]["proposals"]
    assert payload["scientific_validation"] == "not_performed"
    before = api.get_events(workspace_id)
    repeated = ResearchAgent(repo).advance(workspace_id)
    assert repeated.status == "completed" and repeated.new_artifacts == ()
    assert api.get_events(workspace_id) == before
    assert api.validate_workspace(workspace_id).valid
    assert Path(api.export_workspace(workspace_id)["bundle_path"]).is_file()


def test_proposal_stage_uses_approved_core_version_not_latest_completion_event(tmp_path):
    repo, api, workspace_id, g3 = at_gate(tmp_path, "G3")
    store = ArtifactStore(repo / "workspaces" / workspace_id)
    unapproved = store.read(g3.artifact)
    unapproved["core_papers"] = []
    unapproved["core_candidate_count"] = 0
    ref = ArtifactRef(artifact_id="core_paper_set", version=2, sha256=digest(unapproved))
    store.commit("core_paper_set", 2, unapproved, [
        {"type": "S3Completed", "workspace_id": workspace_id, "artifact": ref.model_dump(mode="json")}
    ], "fixture_unapproved_completion")
    approval(api, workspace_id)
    result = api.advance(workspace_id)
    assert result.stage == "G4"
    proposal = store.read(result.pending_gate.artifact)
    assert proposal["source_core_ref"] == g3.artifact.model_dump(mode="json")
