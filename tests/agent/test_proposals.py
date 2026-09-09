from __future__ import annotations

from pathlib import Path
import json
import subprocess
import sys

import pytest

from research_agent.api import ResearchAgent
from research_agent.ideation.proposals import build_proposals


def _core(repo: Path, query: str) -> dict:
    agent = ResearchAgent(repo)
    agent.build_index()
    return agent.screen_papers(query, limit=10)


def test_proposals_resolve_index_evidence_and_are_data_conditioned(tmp_path: Path):
    from tests.agent.retrieval_factory import make_retrieval_corpus

    repo = make_retrieval_corpus(tmp_path / "repo")
    retinal = build_proposals(repo, _core(repo, "diffusion retinal synthesis"))
    segmentation = build_proposals(repo, _core(repo, "diffusion medical segmentation"))

    assert retinal["schema_version"] == "idea-proposal-set-v1"
    assert retinal["status"] == "completed"
    assert retinal["proposals"]
    assert segmentation["proposals"]
    assert retinal["proposals"][0]["mechanism"] != segmentation["proposals"][0]["mechanism"]
    assert all(p["epistemic_status"] == "HYPOTHESIS" for p in retinal["proposals"])
    ids = {card["evidence_id"] for card in retinal["evidence_cards"]}
    assert ids
    assert all(ref in ids for p in retinal["proposals"] for ref in p["evidence_ids"])
    assert all(len(card["abstract_excerpt"]) <= 320 for card in retinal["evidence_cards"])
    assert all("abstract" not in card for card in retinal["evidence_cards"])
    assert "novelty" in " ".join(retinal["limitations"]).lower()


def test_proposals_block_without_usable_evidence(tmp_path: Path):
    from tests.agent.retrieval_factory import make_retrieval_corpus

    repo = make_retrieval_corpus(tmp_path / "repo")
    result = build_proposals(
        repo,
        {
            "schema_version": "core-paper-set-v1",
            "status": "completed",
            "artifact_sha256": "0" * 64,
            "source_search": {"index_id": "missing", "snapshot_id": "snapshot_test", "snapshot_checksum": "a" * 64},
            "core_papers": [],
        },
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "insufficient_evidence"
    assert result["proposals"] == []
    assert result["evidence_cards"] == []


def test_proposals_reject_tampered_provenance(tmp_path: Path):
    from tests.agent.retrieval_factory import make_retrieval_corpus

    repo = make_retrieval_corpus(tmp_path / "repo")
    core = _core(repo, "diffusion retinal synthesis")
    core["core_papers"][0]["provenance"]["record_number"] = 999
    with pytest.raises(ValueError, match="(checksum|provenance)"):
        build_proposals(repo, core)


def test_api_propose_ideas_runs_search_screen_and_proposal_pipeline(tmp_path: Path):
    from tests.agent.retrieval_factory import make_retrieval_corpus

    repo = make_retrieval_corpus(tmp_path / "repo")
    agent = ResearchAgent(repo)
    agent.build_index()
    result = agent.propose_ideas("diffusion retinal synthesis", limit=5)

    assert result["status"] == "completed"
    assert result["generation_method"] == "offline_rules_v1"
    assert result["source_core"]["schema_version"] == "core-paper-set-v1"
    assert result["proposals"][0]["evidence_ids"]


def test_cli_propose_ideas_emits_one_json_object(tmp_path: Path):
    from tests.agent.retrieval_factory import make_retrieval_corpus

    repo = make_retrieval_corpus(tmp_path / "repo")
    agent = ResearchAgent(repo)
    agent.build_index()
    command = [sys.executable, "-m", "research_agent", "--repo", str(repo), "--json",
               "idea", "propose", "--query", "diffusion retinal synthesis", "--limit", "5", "--report"]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert completed.stdout.count("\n") == 1
    assert payload["proposals"][0]["epistemic_status"] == "HYPOTHESIS"
    assert Path(payload["report"]["bundle_path"]).is_file()


def test_cli_no_proposals_returns_blocked_exit_not_success(tmp_path):
    from tests.agent.retrieval_factory import make_retrieval_corpus
    repo = make_retrieval_corpus(tmp_path / "repo")
    ResearchAgent(repo).build_index()
    result = subprocess.run([sys.executable, "-m", "research_agent", "--repo", str(repo), "--json",
                             "idea", "propose", "--query", "language classification", "--report"],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 5
    assert json.loads(result.stdout)["reason"] == "unsupported_evidence_context"
    assert not (repo / "indexes/reports").exists()


def test_unrelated_records_do_not_produce_generic_medical_proposals(tmp_path: Path):
    from tests.agent.retrieval_factory import make_retrieval_corpus
    repo = make_retrieval_corpus(tmp_path / "repo")
    result = build_proposals(repo, _core(repo, "language classification"))
    assert result["status"] == "blocked"
    assert result["reason"] == "unsupported_evidence_context"
    assert result["proposals"] == []


def test_retinal_and_staining_sources_produce_distinct_plans_with_matching_refs(tmp_path: Path):
    from tests.agent.retrieval_factory import make_retrieval_corpus
    repo = make_retrieval_corpus(tmp_path / "repo")
    result = build_proposals(repo, _core(repo, "二维医学图像扩散生成"))
    proposals = {p["theme"]: p for p in result["proposals"]}
    assert {"retinal", "staining"} <= set(proposals)
    assert proposals["retinal"]["experiment_blueprint"] != proposals["staining"]["experiment_blueprint"]
    cards = {c["evidence_id"]: c for c in result["evidence_cards"]}
    assert all("retinal" in cards[ref]["lexical_themes"] for ref in proposals["retinal"]["evidence_ids"])
    assert all("staining" in cards[ref]["lexical_themes"] for ref in proposals["staining"]["evidence_ids"])


def test_core_content_checksum_is_verified_before_generating_proposals(tmp_path):
    from tests.agent.retrieval_factory import make_retrieval_corpus
    repo = make_retrieval_corpus(tmp_path / "repo")
    core = _core(repo, "diffusion retinal synthesis")
    core["artifact_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        build_proposals(repo, core)
