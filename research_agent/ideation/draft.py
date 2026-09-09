"""A bounded idea draft built from lexical retrieval evidence.

This module deliberately produces a hypothesis scaffold, not a scientific
conclusion. It does not call an LLM, mutate a Workspace, or include abstracts.
"""
from __future__ import annotations

from collections import Counter


def _focus(plan: dict) -> str:
    concepts = [
        str(group.get("concept", ""))
        for group in plan.get("groups", [])
        if group.get("concept") != "literal"
    ]
    return ", ".join(dict.fromkeys(concepts)) or "the requested topic"


def _mechanism(signals: Counter[str]) -> str:
    if signals["retinal_mentioned"]:
        return "modality-conditioned diffusion with an explicit condition-consistency check"
    if signals["augmentation"]:
        return "conditioned diffusion with a data-utility and fidelity control loop"
    if signals["translation"] or signals["staining"]:
        return "conditioned diffusion with target-domain consistency constraints"
    return "conditioned diffusion with an explicit condition-consistency constraint"


def draft_idea(search_result: dict, *, domain: str = "medical_diffusion_2d") -> dict:
    """Create a hypothesis scaffold from one completed local search result."""
    if not isinstance(search_result, dict) or search_result.get("status") != "completed":
        raise ValueError("idea drafting requires a completed lexical search")
    if domain != "medical_diffusion_2d":
        raise ValueError("Only the medical_diffusion_2d domain is supported")
    plan = search_result.get("query_plan")
    candidates = search_result.get("candidates")
    if not isinstance(plan, dict) or not isinstance(candidates, list):
        raise ValueError("Search result is missing its query plan or candidates")

    signals: Counter[str] = Counter()
    compact_candidates = []
    for item in candidates[:20]:
        if not isinstance(item, dict):
            continue
        hints = item.get("review_hints") or {}
        signals.update(hints.get("signals", ()))
        compact_candidates.append({
            "record_key": item.get("record_key"),
            "rank": item.get("rank"),
            "paper_id": item.get("paper_id"),
            "source_paper_id": item.get("source_paper_id"),
            "title": item.get("title"),
            "conference": item.get("conference"),
            "year": item.get("year"),
            "doi": item.get("doi", ""),
            "scope_status": item.get("scope_status", "unreviewed"),
            "review_hints": item.get("review_hints", {}),
            "retrieval_evidence": item.get("retrieval_evidence", []),
            "provenance": item.get("provenance", {}),
        })
    focus = _focus(plan)
    mechanism = _mechanism(signals)
    query = str(plan.get("original_query", "")).strip()
    return {
        "schema_version": "idea-draft-v1",
        "status": "completed",
        "mode": "standalone_idea_draft",
        "workflow_advanced": False,
        "domain": domain,
        "epistemic_status": "HYPOTHESIS",
        "topic": query,
        "problem_statement": (
            f"The query '{query}' identifies a retrieval area around {focus}; "
            "the concrete failure mode still requires paper-level verification."
        ),
        "residual_gap": (
            "The retrieved metadata does not establish whether existing methods "
            "test condition fidelity, failure cases, or independent 2D validity."
        ),
        "proposed_mechanism": mechanism,
        "hypothesis": (
            f"If {mechanism} is applied to {focus}, it may improve controllability "
            "under the stated 2D medical setting; this is a testable hypothesis, "
            "not an established result."
        ),
        "predictions": [
            "Condition-consistency should improve on a pre-registered held-out split.",
            "Any gain should remain after comparison with a strong unmodified diffusion baseline.",
        ],
        "falsification_tests": [
            "The proposed constraint does not improve the primary pre-registered metric.",
            "The gain disappears under a patient-level split or a modality-held-out test.",
            "A matched simple baseline reaches the same result with lower cost or complexity.",
        ],
        "baseline": "A strong unmodified conditional diffusion model with the same data, split and compute budget.",
        "boundaries": [
            "scope_status=unreviewed",
            "metadata and lexical matches are not evidence of scientific relevance",
            "no fulltext was read and no novelty or eligibility verdict was made",
            "no experiment has been run and no result is claimed",
        ],
        "source_search": {
            "index_id": search_result.get("index_id"),
            "snapshot_id": search_result.get("snapshot_id"),
            "snapshot_checksum": search_result.get("snapshot_checksum"),
            "query_plan": plan,
            "coverage": search_result.get("coverage", {}),
        },
        "candidates": compact_candidates,
        "warnings": [
            "This draft is a deterministic scaffold from local lexical retrieval; semantic screening is required.",
            "Candidate titles and provenance are retained for audit, while abstracts are intentionally omitted.",
        ],
    }
