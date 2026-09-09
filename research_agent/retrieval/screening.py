"""Deterministic S3 screening hints over a completed lexical search.

This module intentionally stays below semantic screening.  It records why a
retrieved record was retained or marked as a duplicate and groups retained
records using already computed lexical review hints.  It never edits the
source corpus or a Workspace and never claims relevance, eligibility or
novelty.
"""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from research_agent.core.serialization import digest
from research_agent.retrieval.records import clean_text


_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)" , re.IGNORECASE)


def _normalised_title(value: object) -> str:
    title = clean_text(value).casefold()
    return re.sub(r"[^\w]+", " ", title, flags=re.UNICODE).strip()


def _normalised_doi(value: object) -> str:
    doi = clean_text(value).casefold()
    return _DOI_PREFIX.sub("", doi).strip()


def _identity_key(candidate: dict[str, Any]) -> str:
    doi = _normalised_doi(candidate.get("doi"))
    if doi:
        return f"doi:{doi}"
    title = _normalised_title(candidate.get("title"))
    if not title:
        raise ValueError("candidate title is required when DOI is unavailable")
    return f"title:{title}"


def _order_key(candidate: dict[str, Any], position: int) -> tuple[int, str, int]:
    rank = candidate.get("rank")
    rank_value = rank if type(rank) is int and rank >= 1 else 10**9
    return rank_value, clean_text(candidate.get("record_key")), position


def _cluster_label(candidate: dict[str, Any]) -> str:
    hints = candidate.get("review_hints")
    signals = hints.get("signals", ()) if isinstance(hints, dict) else ()
    if not isinstance(signals, (list, tuple, set)):
        signals = ()
    signal_set = {str(signal) for signal in signals}
    if {"diffusion_mentioned", "generation_mentioned", "flow_matching_mentioned"} & signal_set:
        return "diffusion_generation"
    if {"translation", "staining"} & signal_set:
        return "cross_modal_synthesis"
    if {"segmentation_mentioned", "reconstruction_mentioned"} & signal_set:
        return "downstream_task"
    return "other"


def _validate_search_result(search_result: object) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(search_result, dict) or search_result.get("status") != "completed":
        raise ValueError("screening requires a completed lexical search")
    if search_result.get("schema_version") != "lexical-search-v1":
        raise ValueError("screening requires a completed lexical search")
    candidates = search_result.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("lexical search candidates must be a list")
    validated: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise ValueError("candidate must be an object")
        if not clean_text(candidate.get("record_key")):
            raise ValueError("candidate record_key is required")
        if not clean_text(candidate.get("title")):
            raise ValueError("candidate title is required")
        # Resolve the identity now so malformed DOI/title values fail before
        # producing a partially formed artifact.
        _identity_key(candidate)
        validated.append(candidate)
    return search_result, validated


def screen_candidates(search_result: dict[str, Any]) -> dict[str, Any]:
    """Create an immutable S3 core-paper-set suggestion from lexical results.

    The returned mapping is deterministic for a given search result.  It is a
    value artifact for callers to persist through their own ArtifactStore;
    this function itself performs no filesystem writes.
    """
    source, candidates = _validate_search_result(search_result)
    groups: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for position, candidate in enumerate(candidates):
        groups.setdefault(_identity_key(candidate), []).append((position, candidate))

    representatives: dict[str, tuple[int, dict[str, Any]]] = {}
    decisions: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []
    for key, members in groups.items():
        representative_position, representative = min(
            members, key=lambda item: _order_key(item[1], item[0])
        )
        representatives[key] = (representative_position, representative)
        record_keys = [clean_text(item.get("record_key")) for _, item in members]
        if len(members) > 1:
            duplicate_groups.append(
                {
                    "key": key,
                    "record_keys": record_keys,
                    "representative": clean_text(representative.get("record_key")),
                }
            )
        for position, candidate in members:
            record_key = clean_text(candidate.get("record_key"))
            if position == representative_position:
                decisions.append(
                    {
                        "record_key": record_key,
                        "status": "retained",
                        "reason": "lexical_candidate_representative",
                        "identity_key": key,
                    }
                )
            else:
                decisions.append(
                    {
                        "record_key": record_key,
                        "status": "duplicate",
                        "reason": "duplicate_identity_key",
                        "identity_key": key,
                        "duplicate_of": clean_text(representative.get("record_key")),
                    }
                )

    decisions.sort(key=lambda item: item["record_key"])
    selected = sorted(representatives.values(), key=lambda item: _order_key(item[1], item[0]))
    core_papers: list[dict[str, Any]] = []
    cluster_records: dict[str, list[str]] = {}
    for _, original in selected:
        candidate = deepcopy(original)
        cluster = _cluster_label(candidate)
        candidate["screening_status"] = "retained"
        candidate["screening_reason"] = "lexical_candidate_representative"
        candidate["cluster"] = cluster
        core_papers.append(candidate)
        cluster_records.setdefault(cluster, []).append(clean_text(candidate["record_key"]))

    clusters = [
        {
            "label": label,
            "record_keys": keys,
            "basis": "lexical_review_hints",
        }
        for label, keys in sorted(cluster_records.items())
    ]
    duplicate_groups.sort(key=lambda item: item["key"])
    base: dict[str, Any] = {
        "schema_version": "core-paper-set-v1",
        "status": "completed",
        "mode": "standalone_lexical_screening",
        "selection_policy": {
            "deduplication": "doi_then_normalized_title",
            "representative": "lowest_search_rank_then_record_key",
            "clustering": "review_hints_lexical_signals",
        },
        "source_search": {
            "schema_version": source.get("schema_version"),
            "index_id": source.get("index_id"),
            "snapshot_id": source.get("snapshot_id"),
            "snapshot_checksum": source.get("snapshot_checksum"),
            "query_plan": deepcopy(source.get("query_plan", {})),
            "coverage": deepcopy(source.get("coverage", {})),
        },
        "input_candidate_count": len(candidates),
        "core_candidate_count": len(core_papers),
        "screening_decisions": decisions,
        "duplicate_groups": duplicate_groups,
        "clusters": clusters,
        "core_papers": core_papers,
        "warnings": [
            "This is lexical triage only; semantic relevance and scope eligibility remain unreviewed.",
            "No novelty, priority or completeness conclusion was made.",
            "Duplicate groups are deterministic identity hints; source variants remain auditable in decisions.",
        ],
    }
    return {**base, "artifact_sha256": digest(base)}

