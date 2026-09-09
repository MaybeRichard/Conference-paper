from __future__ import annotations

import copy
from pathlib import Path
import shutil

import pytest

from research_agent.api import ResearchAgent
from research_agent.retrieval.screening import screen_candidates
from tests.agent.retrieval_factory import make_retrieval_corpus


def _search_result() -> dict:
    return {
        "status": "completed",
        "schema_version": "lexical-search-v1",
        "index_id": "idx_test",
        "snapshot_id": "snapshot_test",
        "snapshot_checksum": "a" * 64,
        "query_plan": {"original_query": "二维医学图像扩散生成", "groups": []},
        "coverage": {"returned_records": 4},
        "candidates": [
            {
                "record_key": "r1",
                "paper_id": "a",
                "source_paper_id": "a-src",
                "title": "RetiDiff: Diffusion Synthesis",
                "conference": "MICCAI",
                "year": 2025,
                "doi": "10.1234/RETI",
                "scope_status": "unreviewed",
                "review_hints": {"scope_status": "unreviewed", "signals": ["diffusion_mentioned", "generation_mentioned"]},
                "retrieval_evidence": [{"channel": "title", "rank": 1}],
                "provenance": {"record_number": 1, "shard_path": "corpus/x.jsonl"},
            },
            {
                "record_key": "r2",
                "paper_id": "a-variant",
                "source_paper_id": "a2-src",
                "title": "RetiDiff Diffusion Synthesis",
                "conference": "MICCAI",
                "year": 2025,
                "doi": "10.1234/reti",
                "scope_status": "unreviewed",
                "review_hints": {"scope_status": "unreviewed", "signals": ["diffusion_mentioned"]},
                "retrieval_evidence": [{"channel": "abstract", "rank": 2}],
                "provenance": {"record_number": 2, "shard_path": "corpus/x.jsonl"},
            },
            {
                "record_key": "r3",
                "paper_id": "b",
                "source_paper_id": "b-src",
                "title": "Medical Segmentation Benchmark",
                "conference": "CVPR",
                "year": 2024,
                "doi": "",
                "scope_status": "unreviewed",
                "review_hints": {"scope_status": "unreviewed", "signals": ["segmentation_mentioned"]},
                "retrieval_evidence": [{"channel": "title", "rank": 3}],
                "provenance": {"record_number": 3, "shard_path": "corpus/x.jsonl"},
            },
            {
                "record_key": "r4",
                "paper_id": "c",
                "source_paper_id": "c-src",
                "title": "Medical Segmentation Benchmark",
                "conference": "CVPR",
                "year": 2024,
                "doi": "",
                "scope_status": "unreviewed",
                "review_hints": {"scope_status": "unreviewed", "signals": ["segmentation_mentioned"]},
                "retrieval_evidence": [{"channel": "combined", "rank": 4}],
                "provenance": {"record_number": 4, "shard_path": "corpus/x.jsonl"},
            },
        ],
    }


def test_screening_deduplicates_with_stable_representative_and_reasons():
    result = screen_candidates(_search_result())

    assert result["schema_version"] == "core-paper-set-v1"
    assert result["status"] == "completed"
    assert len(result["core_papers"]) == 2
    assert result["core_papers"][0]["paper_id"] == "a"
    assert result["duplicate_groups"] == [
        {"key": "doi:10.1234/reti", "record_keys": ["r1", "r2"], "representative": "r1"},
        {"key": "title:medical segmentation benchmark", "record_keys": ["r3", "r4"], "representative": "r3"},
    ]
    decisions = {item["record_key"]: item for item in result["screening_decisions"]}
    assert decisions["r1"]["status"] == "retained"
    assert decisions["r1"]["reason"] == "lexical_candidate_representative"
    assert decisions["r2"]["status"] == "duplicate"
    assert decisions["r2"]["duplicate_of"] == "r1"
    assert decisions["r3"]["status"] == "retained"
    assert all(item["scope_status"] == "unreviewed" for item in result["core_papers"])


def test_screening_clusters_from_lexical_signals_and_preserves_provenance():
    result = screen_candidates(_search_result())

    assert {cluster["label"] for cluster in result["clusters"]} == {
        "diffusion_generation",
        "downstream_task",
    }
    diffusion = next(c for c in result["clusters"] if c["label"] == "diffusion_generation")
    assert diffusion["record_keys"] == ["r1"]
    assert diffusion["basis"] == "lexical_review_hints"
    assert result["core_papers"][0]["provenance"]["record_number"] == 1
    assert "semantic" in " ".join(result["warnings"]).lower()
    assert "novelty" in " ".join(result["warnings"]).lower()


def test_screening_is_deterministic_and_does_not_mutate_search_result():
    source = _search_result()
    before = copy.deepcopy(source)

    first = screen_candidates(source)
    second = screen_candidates(source)

    assert first == second
    assert source == before
    assert first["artifact_sha256"] == second["artifact_sha256"]


def test_screening_rejects_incomplete_or_malformed_search():
    with pytest.raises(ValueError, match="completed lexical search"):
        screen_candidates({"status": "blocked"})
    malformed = _search_result()
    malformed["candidates"] = [{"record_key": "only-key"}]
    with pytest.raises(ValueError, match="candidate"):
        screen_candidates(malformed)


def test_api_screen_papers_runs_s3_without_workspace_writes(tmp_path: Path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    domain = Path(__file__).resolve().parents[2] / "domains/medical_diffusion_2d/domain.yaml"
    (repo / "domains/medical_diffusion_2d").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(domain, repo / "domains/medical_diffusion_2d/domain.yaml")
    agent = ResearchAgent(repo)
    agent.build_index()

    result = agent.screen_papers("medical diffusion synthesis", limit=5)

    assert result["schema_version"] == "core-paper-set-v1"
    assert result["artifact_sha256"]
    assert not (repo / "workspaces").exists()
