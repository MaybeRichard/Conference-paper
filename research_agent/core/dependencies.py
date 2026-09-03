"""Validate Artifact dependency graphs and find descendants made stale by a change."""
from __future__ import annotations

from collections import deque
import re

from pydantic import ValidationError

from research_agent.core.errors import IntegrityError
from research_agent.schemas.base import ArtifactRef

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")


def _normalise_graph(
    refs: dict[str, tuple[ArtifactRef, ...]],
) -> dict[str, tuple[ArtifactRef, ...]]:
    if not isinstance(refs, dict):
        raise ValueError("dependency graph must be a dictionary")

    graph: dict[str, tuple[ArtifactRef, ...]] = {}
    for artifact_id, raw_dependencies in refs.items():
        if not isinstance(artifact_id, str) or _IDENTIFIER.fullmatch(artifact_id) is None:
            raise ValueError("dependency graph keys must be Artifact identifiers")
        if not isinstance(raw_dependencies, tuple):
            raise ValueError("dependency lists must be tuples")
        try:
            dependencies = tuple(
                ArtifactRef.model_validate(dependency)
                for dependency in raw_dependencies
            )
        except ValidationError:
            raise ValueError("dependency graph contains an invalid ArtifactRef") from None
        if len(set(dependencies)) != len(dependencies):
            raise ValueError("dependency graph contains duplicate edges")
        graph[artifact_id] = dependencies

    for dependencies in graph.values():
        for dependency in dependencies:
            if dependency.artifact_id not in graph:
                raise IntegrityError(
                    "Dependency graph references a missing dependency Artifact"
                )
    return graph


def _reject_cycles(graph: dict[str, tuple[ArtifactRef, ...]]) -> None:
    state: dict[str, int] = {artifact_id: 0 for artifact_id in graph}

    def visit(artifact_id: str) -> None:
        marker = state[artifact_id]
        if marker == 1:
            raise IntegrityError("Dependency graph contains a cycle")
        if marker == 2:
            return
        state[artifact_id] = 1
        for dependency in graph[artifact_id]:
            visit(dependency.artifact_id)
        state[artifact_id] = 2

    for artifact_id in graph:
        visit(artifact_id)


def _known_refs(
    graph: dict[str, tuple[ArtifactRef, ...]],
) -> dict[str, ArtifactRef]:
    """Return the unique exact version/hash used for each referenced node.

    One graph snapshot may contain one exact ArtifactRef per artifact identifier.
    Mixing versions would make an identifier-only node key ambiguous, so it is
    rejected rather than over-invalidating descendants.
    """
    known: dict[str, ArtifactRef] = {}
    for dependencies in graph.values():
        for dependency in dependencies:
            existing = known.get(dependency.artifact_id)
            if existing is not None and existing != dependency:
                raise IntegrityError(
                    "Dependency graph mixes multiple versions of one Artifact"
                )
            known[dependency.artifact_id] = dependency
    return known


def affected_artifacts(
    refs: dict[str, tuple[ArtifactRef, ...]],
    changed: ArtifactRef,
) -> set[str]:
    """Return descendants whose dependency chain includes the exact changed ref.

    Keys identify one Artifact node per identifier for the supplied graph
    snapshot. The first edge must equal ``changed`` in ID, version and hash;
    subsequent propagation follows the exact refs used by downstream nodes.
    The changed node itself is not included in the returned set.
    """
    try:
        changed = ArtifactRef.model_validate(changed)
    except ValidationError:
        raise ValueError("changed must be a valid ArtifactRef") from None

    graph = _normalise_graph(refs)
    _reject_cycles(graph)
    known = _known_refs(graph)

    affected: set[str] = set()
    queue: deque[str] = deque(
        artifact_id
        for artifact_id, dependencies in graph.items()
        if changed in dependencies
    )

    while queue:
        current = queue.popleft()
        if current in affected:
            continue
        affected.add(current)
        current_ref = known.get(current)
        if current_ref is None:
            continue
        for artifact_id, dependencies in graph.items():
            if artifact_id not in affected and current_ref in dependencies:
                queue.append(artifact_id)

    return affected
