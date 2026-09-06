from pathlib import Path
import pytest

from research_agent.retrieval.index import LexicalIndex
from research_agent.retrieval.query import plan_query
from research_agent.retrieval.search import search
from tests.agent.retrieval_factory import make_retrieval_corpus


@pytest.fixture
def index(tmp_path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    obj = LexicalIndex(repo)
    obj.build()
    return obj


def ids(result): return {r["paper_id"] for r in result["candidates"]}


def test_chinese_query_preserves_title_only_and_split_field_hits(index):
    result = search(index, "二维医学图像扩散生成", limit=20)
    assert {"reti", "stain", "split", "full"} <= ids(result)
    assert "generic" not in ids(result)
    assert result["mode"] == "exploratory_local_lexical"
    assert result["workflow_advanced"] is False
    assert result["query_plan"]["dimension_intent"] == "2d"
    assert all(r["scope_status"] == "unreviewed" for r in result["candidates"])
    reti = next(x for x in result["candidates"] if x["paper_id"] == "reti")
    assert reti["abstract_status"] == "missing"
    assert reti["retrieval_evidence"]
    assert reti["provenance"]["record_number"] == 1
    assert {"reti", "stain"} <= {x["paper_id"] for x in result["missing_abstract_queue"]}


def test_filters_applied_before_topk(index):
    result = search(index, "diffusion", conference="cvpr", year_from=2024, year_to=2024, limit=1, per_channel=1)
    assert ids(result) == {"split"}
    assert result["filters"]["conference"] == "CVPR"


def test_deterministic_ranking_and_cross_process_reopen(index):
    first = search(index, "medical diffusion generation")
    second = search(LexicalIndex(index.repo_root), "medical diffusion generation")
    assert first == second


def test_missing_abstract_reserved_slot_among_strong_complete_matches(tmp_path):
    papers = [dict(paper_id=f"full{i}", title="medical diffusion generation", abstract="medical diffusion generation "*8,
                   conference="MICCAI", year=2025) for i in range(35)]
    papers.append(dict(paper_id="missing", title="medical diffusion generation with limited annotation", abstract="",
                       conference="MICCAI", year=2025))
    obj = LexicalIndex(make_retrieval_corpus(tmp_path/"repo", papers)); obj.build()
    result = search(obj, "medical diffusion generation", limit=5, per_channel=50)
    assert "missing" in ids(result)
    row = next(x for x in result["candidates"] if x["paper_id"] == "missing")
    assert "missing_abstract_reserved" in row["selection_reasons"]
    assert len(result["candidates"]) == 5


def test_scope_signals_are_not_automatic_exclusions(index):
    result = search(index, "diffusion", limit=20)
    mixed = next(x for x in result["candidates"] if x["paper_id"] == "mixed")
    assert {"2d_mentioned", "3d_mentioned", "slice_dependency_mentioned"} <= set(mixed["review_hints"]["signals"])
    assert mixed["scope_status"] == "unreviewed"
    assert "seg" in ids(result)


def test_unrelated_or_injection_query_is_literal_and_cannot_damage_db(index):
    result = search(index, "zzunlikelytoken OR DROP TABLE documents --")
    assert result["candidates"] == []
    assert index.verify()["document_count"] == 7
    for query in ['"diffusion"', 'diffusion:gen*', 'diffusion ( medical )']:
        assert search(index, query)["status"] == "completed"


@pytest.mark.parametrize("query", ["", "   ", "***", "a"*2001, "医学图像扩散生成火星", "不要三维医学扩散生成"])
def test_empty_oversized_or_unsupported_chinese_queries_fail_explicitly(query):
    with pytest.raises(ValueError): plan_query(query)


@pytest.mark.parametrize("kwargs", [{"limit":0}, {"limit":True}, {"limit":1001}, {"per_channel":0}, {"year_from":2025,"year_to":2024}])
def test_invalid_limits_and_year_range_rejected(index, kwargs):
    with pytest.raises(ValueError): search(index, "diffusion", **kwargs)


def test_reported_truncation_is_not_a_claim_of_complete_recall(index):
    result = search(index, "diffusion", per_channel=1, limit=2)
    assert any(x["truncated"] for x in result["channel_audit"])
    assert result["coverage"]["exhaustive"] is False
    assert result["coverage"]["known_recall"] is None


def test_same_title_variants_not_destructively_merged(tmp_path):
    papers = [dict(paper_id=i, title="Medical diffusion generation", abstract="", conference="MICCAI", year=2025)
              for i in ["v1", "v2"]]
    obj = LexicalIndex(make_retrieval_corpus(tmp_path/"repo", papers)); obj.build()
    result = search(obj, "diffusion", limit=10)
    assert ids(result) == {"v1", "v2"}
    assert all(r["same_title_records"] == 2 for r in result["candidates"])


def test_full_abstract_not_exported_in_search_result(index):
    result = search(index, "diffusion")
    for row in result["candidates"]:
        assert "abstract" not in row
        assert "abstract_text" not in row


@pytest.mark.parametrize("title,signals", [
    ("Diffusion-Adapted Spatial Filtering", {"diffusion_mentioned","physical_diffusion_caution"}),
    ("Flow Matching and Diffusion for Medical Image Synthesis", {"flow_matching_mentioned","diffusion_mentioned","generation_mentioned"}),
    ("2.5D Diffusion MRI Reconstruction", {"2_5d_mentioned","reconstruction_mentioned"}),
])
def test_regression_hints_are_independent_not_final_labels(title,signals):
    from research_agent.retrieval.records import review_hints
    result=review_hints(title,"")
    assert signals <= set(result["signals"])
    assert result["scope_status"]=="unreviewed"
