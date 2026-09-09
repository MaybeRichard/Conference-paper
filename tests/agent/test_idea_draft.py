from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

from research_agent.api import ResearchAgent
from tests.agent.retrieval_factory import make_retrieval_corpus


def test_api_drafts_auditable_hypothesis_without_mutating_workspace(tmp_path: Path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    domain = Path(__file__).resolve().parents[2] / "domains/medical_diffusion_2d/domain.yaml"
    (repo / "domains/medical_diffusion_2d").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(domain, repo / "domains/medical_diffusion_2d/domain.yaml")
    agent = ResearchAgent(repo)
    state = agent.create_workspace("二维医学图像扩散生成", "medical_diffusion_2d")
    agent.build_index()

    result = agent.draft_idea(
        "二维医学图像扩散生成",
        limit=5,
        report=True,
    )

    assert result["schema_version"] == "idea-draft-v1"
    assert result["status"] == "completed"
    assert result["epistemic_status"] == "HYPOTHESIS"
    assert result["workflow_advanced"] is False
    assert result["domain"] == "medical_diffusion_2d"
    assert result["candidates"]
    assert result["hypothesis"]
    assert result["falsification_tests"]
    assert any("unreviewed" in item for item in result["boundaries"])
    assert agent.get_status(state.workspace_id) == state

    report = result["report"]
    assert Path(report["json_path"]).is_file()
    assert Path(report["markdown_path"]).is_file()
    with ZipFile(report["bundle_path"]) as archive:
        assert set(archive.namelist()) == {"idea_draft.json", "idea_draft.md"}
        payload = json.loads(archive.read("idea_draft.json"))
        assert payload["epistemic_status"] == "HYPOTHESIS"
        assert b"Medical diffusion generation" not in archive.read("idea_draft.md")


def test_cli_idea_draft_is_one_json_object_and_requires_existing_index(tmp_path: Path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    command = [
        sys.executable,
        "-m",
        "research_agent",
        "--repo",
        str(repo),
        "--json",
        "idea",
        "draft",
        "--query",
        "diffusion medical synthesis",
    ]
    missing = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert missing.returncode == 5
    assert json.loads(missing.stdout)["error"]["code"] == "index_not_built"

    ResearchAgent(repo).build_index()
    completed = subprocess.run(command + ["--report"], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert completed.stdout.count("\n") == 1
    assert payload["epistemic_status"] == "HYPOTHESIS"
    assert payload["report"]["markdown_path"].endswith("idea_draft.md")
