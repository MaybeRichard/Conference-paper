from __future__ import annotations

import pytest

from research_agent.core.dependencies import affected_artifacts
from research_agent.core.errors import IntegrityError
from research_agent.schemas.base import ArtifactRef


def ref(name: str, version: int = 1, digit: str = "1") -> ArtifactRef:
    return ArtifactRef(artifact_id=name, version=version, sha256=digit * 64)


def test_exact_changed_ref_invalidates_all_descendants_breadth_first():
    a = ref("a")
    b = ref("b")
    c = ref("c")
    graph = {
        "a": (),
        "b": (a,),
        "c": (b,),
        "independent": (),
    }

    assert affected_artifacts(graph, a) == {"b", "c"}


def test_same_artifact_id_with_different_version_or_hash_is_not_a_match():
    a_v1 = ref("a", 1, "1")
    graph = {"a": (), "b": (a_v1,)}

    assert affected_artifacts(graph, ref("a", 2, "2")) == set()
    assert affected_artifacts(graph, ref("a", 1, "3")) == set()


def test_branching_dependency_graph_invalidates_only_reachable_descendants():
    a = ref("a")
    b = ref("b")
    c = ref("c")
    graph = {
        "a": (),
        "b": (a,),
        "c": (a,),
        "d": (b, c),
        "unrelated": (),
    }

    assert affected_artifacts(graph, a) == {"b", "c", "d"}
    assert affected_artifacts(graph, b) == {"d"}


def test_missing_dependency_is_rejected_instead_of_partially_traversed():
    graph = {
        "a": (),
        "b": (ref("missing"),),
    }

    with pytest.raises(IntegrityError, match="missing dependency"):
        affected_artifacts(graph, ref("a"))


def test_cycle_and_self_cycle_are_rejected():
    with pytest.raises(IntegrityError, match="cycle"):
        affected_artifacts(
            {"a": (ref("b"),), "b": (ref("a"),)},
            ref("a"),
        )

    with pytest.raises(IntegrityError, match="cycle"):
        affected_artifacts({"a": (ref("a"),)}, ref("a"))


def test_graph_keys_must_match_dependency_artifact_identifiers():
    with pytest.raises(ValueError):
        affected_artifacts({"contains spaces": ()}, ref("a"))
