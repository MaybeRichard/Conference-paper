"""Verified, restart-safe execution and reuse of deterministic M1 tasks."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any, Callable
from uuid import uuid4

from pydantic import ValidationError

from research_agent.core.errors import IntegrityError
from research_agent.core.serialization import canonical_bytes, digest
from research_agent.core.store import ArtifactStore
from research_agent.schemas.base import ArtifactRef
from research_agent.schemas.workflow import TaskResult

_WORKFLOW_VERSION = "m1-v1"
_FINGERPRINT_SCHEMA = "task-fingerprint-v1"
_OUTPUT_SCHEMA = "task-output-v1"
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalise_mapping(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    try:
        return json.loads(canonical_bytes(value).decode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        raise ValueError(f"{field} must contain finite canonical JSON values") from None


def _normalise_profile(profile: dict) -> dict[str, Any]:
    normalised = _normalise_mapping(profile, field="profile")
    if "version" not in normalised:
        normalised["version"] = "1"
    version = normalised.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("profile.version must be a non-empty string")
    return json.loads(canonical_bytes(normalised).decode("utf-8"))


def _normalise_inputs(inputs: tuple[ArtifactRef, ...]) -> tuple[ArtifactRef, ...]:
    if not isinstance(inputs, tuple):
        raise ValueError("inputs must be a tuple of ArtifactRef values")
    try:
        normalised = tuple(ArtifactRef.model_validate(item) for item in inputs)
    except ValidationError:
        raise ValueError("inputs contain an invalid ArtifactRef") from None
    if len(set(normalised)) != len(normalised):
        raise ValueError("inputs cannot contain duplicate ArtifactRefs")
    return normalised


def task_fingerprint(
    operation: str,
    inputs: tuple[ArtifactRef, ...],
    profile: dict,
) -> str:
    """Create a stable fingerprint without time, attempt or process identity."""
    if not isinstance(operation, str) or _IDENTIFIER.fullmatch(operation) is None:
        raise ValueError("operation must be an identifier")
    normalised_inputs = _normalise_inputs(inputs)
    normalised_profile = _normalise_profile(profile)
    return digest(
        {
            "schema_version": _FINGERPRINT_SCHEMA,
            "operation": operation,
            "inputs": [item.model_dump(mode="json") for item in normalised_inputs],
            "profile": normalised_profile,
            "workflow_version": _WORKFLOW_VERSION,
        }
    )


class TaskRunner:
    """Run one producer or reuse an already committed and verified output.

    M1 holds the Workspace lock while a producer runs. This deliberately favors
    correctness and single-producer semantics over parallelism inside one
    Workspace; later schedulers can partition independent work more finely.
    """

    def __init__(self, store: ArtifactStore) -> None:
        if not isinstance(store, ArtifactStore):
            raise TypeError("store must be an ArtifactStore")
        self.store = store

    @staticmethod
    def _payloads(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for event in events:
            payload = event.get("payload") if isinstance(event, dict) else None
            if not isinstance(payload, dict):
                raise IntegrityError("Task event envelope is invalid")
            payloads.append(payload)
        return payloads

    @staticmethod
    def _invalidated_refs(payloads: list[dict[str, Any]]) -> set[ArtifactRef]:
        stale: set[ArtifactRef] = set()
        for payload in payloads:
            if payload.get("type") not in {
                "TaskOutputsInvalidated",
                "ArtifactMarkedStale",
            }:
                continue
            raw_refs = payload.get("outputs")
            if raw_refs is None and payload.get("artifact") is not None:
                raw_refs = [payload["artifact"]]
            if not isinstance(raw_refs, list):
                raise IntegrityError("Task invalidation event is malformed")
            try:
                stale.update(ArtifactRef.model_validate(item) for item in raw_refs)
            except ValidationError:
                raise IntegrityError("Task invalidation event has an invalid ArtifactRef") from None
        return stale

    @staticmethod
    def _completed_output_refs(
        payloads: list[dict[str, Any]],
        fingerprint: str,
    ) -> list[ArtifactRef]:
        expected_id = f"task_output_{fingerprint}"
        outputs: list[ArtifactRef] = []
        versions: dict[int, ArtifactRef] = {}
        for payload in payloads:
            if payload.get("type") != "TaskCompleted" or payload.get("fingerprint") != fingerprint:
                continue
            try:
                output = ArtifactRef.model_validate(payload.get("output"))
            except ValidationError:
                raise IntegrityError("TaskCompleted event has an invalid output reference") from None
            if output.artifact_id != expected_id:
                raise IntegrityError("TaskCompleted event uses an unexpected output identifier")
            existing = versions.get(output.version)
            if existing is not None and existing != output:
                raise IntegrityError("One task output version has conflicting hashes")
            versions[output.version] = output
            outputs.append(output)
        return outputs

    def _cached_output(
        self,
        fingerprint: str,
        operation: str,
        inputs: tuple[ArtifactRef, ...],
        profile: dict[str, Any],
    ) -> ArtifactRef | None:
        payloads = self._payloads(self.store.events())
        stale = self._invalidated_refs(payloads)
        matches = [
            output
            for output in self._completed_output_refs(payloads, fingerprint)
            if output not in stale
        ]
        unique = set(matches)
        if len(unique) > 1:
            raise IntegrityError("A task fingerprint has multiple visible completed outputs")
        if not unique:
            return None

        output = next(iter(unique))
        payload = self.store.read(output)
        expected_inputs = [item.model_dump(mode="json") for item in inputs]
        if (
            payload.get("schema_version") != _OUTPUT_SCHEMA
            or payload.get("fingerprint") != fingerprint
            or payload.get("operation") != operation
            or payload.get("workflow_version") != _WORKFLOW_VERSION
            or payload.get("inputs") != expected_inputs
            or payload.get("dependencies") != expected_inputs
            or payload.get("profile") != profile
            or not isinstance(payload.get("result"), dict)
        ):
            raise IntegrityError("Committed task output metadata is inconsistent")
        return output

    def _next_output_version(self, fingerprint: str) -> int:
        payloads = self._payloads(self.store.events())
        refs = self._completed_output_refs(payloads, fingerprint)
        return max((ref.version for ref in refs), default=0) + 1

    def _commit_attempt(
        self,
        *,
        attempt_id: str,
        fingerprint: str,
        operation: str,
        inputs: tuple[ArtifactRef, ...],
        profile: dict[str, Any],
    ) -> ArtifactRef:
        payload = {
            "schema_version": "task-attempt-v1",
            "attempt_id": attempt_id,
            "fingerprint": fingerprint,
            "operation": operation,
            "inputs": [item.model_dump(mode="json") for item in inputs],
            "profile": profile,
            "workflow_version": _WORKFLOW_VERSION,
            "started_at": _utc_now(),
        }
        return self.store.commit(
            f"task_attempt_{attempt_id}",
            1,
            payload,
            [
                {
                    "type": "TaskStarted",
                    "attempt_id": attempt_id,
                    "fingerprint": fingerprint,
                    "operation": operation,
                }
            ],
            f"task_start_{attempt_id}",
        )

    def _commit_failure(
        self,
        *,
        attempt_id: str,
        attempt_ref: ArtifactRef,
        fingerprint: str,
        operation: str,
        error_type: str,
    ) -> None:
        payload = {
            "schema_version": "task-failure-v1",
            "attempt_id": attempt_id,
            "attempt": attempt_ref.model_dump(mode="json"),
            "fingerprint": fingerprint,
            "operation": operation,
            "reason": "producer_failed",
            "error_type": error_type,
            "finished_at": _utc_now(),
        }
        self.store.commit(
            f"task_failure_{attempt_id}",
            1,
            payload,
            [
                {
                    "type": "TaskFailed",
                    "attempt_id": attempt_id,
                    "fingerprint": fingerprint,
                    "operation": operation,
                    "reason": "producer_failed",
                    "error_type": error_type,
                }
            ],
            f"task_fail_{attempt_id}",
        )

    def run(
        self,
        operation: str,
        inputs: tuple[ArtifactRef, ...],
        profile: dict,
        producer: Callable[[], dict],
    ) -> TaskResult:
        """Validate dependencies, reuse a verified result or execute producer once."""
        if not callable(producer):
            raise TypeError("producer must be callable")
        normalised_inputs = _normalise_inputs(inputs)
        normalised_profile = _normalise_profile(profile)
        fingerprint = task_fingerprint(operation, normalised_inputs, normalised_profile)

        with self.store.locked():
            for dependency in normalised_inputs:
                self.store.read(dependency)

            cached = self._cached_output(
                fingerprint,
                operation,
                normalised_inputs,
                normalised_profile,
            )
            if cached is not None:
                return TaskResult(
                    status="completed",
                    outputs=(cached,),
                    cache_hit=True,
                )

            attempt_id = uuid4().hex
            attempt_ref = self._commit_attempt(
                attempt_id=attempt_id,
                fingerprint=fingerprint,
                operation=operation,
                inputs=normalised_inputs,
                profile=normalised_profile,
            )
            try:
                produced = producer()
                result = _normalise_mapping(produced, field="producer result")
            except Exception as error:
                self._commit_failure(
                    attempt_id=attempt_id,
                    attempt_ref=attempt_ref,
                    fingerprint=fingerprint,
                    operation=operation,
                    error_type=type(error).__name__,
                )
                return TaskResult(status="failed", reason="producer_failed")

            output_payload = {
                "schema_version": _OUTPUT_SCHEMA,
                "fingerprint": fingerprint,
                "operation": operation,
                "inputs": [item.model_dump(mode="json") for item in normalised_inputs],
                "dependencies": [
                    item.model_dump(mode="json") for item in normalised_inputs
                ],
                "profile": normalised_profile,
                "workflow_version": _WORKFLOW_VERSION,
                "attempt": attempt_ref.model_dump(mode="json"),
                "result": result,
                "completed_at": _utc_now(),
            }
            output_id = f"task_output_{fingerprint}"
            output_version = self._next_output_version(fingerprint)
            output_ref = self.store.commit(
                output_id,
                output_version,
                output_payload,
                [
                    {
                        "type": "TaskCompleted",
                        "attempt_id": attempt_id,
                        "fingerprint": fingerprint,
                        "operation": operation,
                        "inputs": [
                            item.model_dump(mode="json")
                            for item in normalised_inputs
                        ],
                        "output": {
                            "artifact_id": output_id,
                            "version": output_version,
                            "sha256": digest(output_payload),
                        },
                    }
                ],
                f"task_complete_{attempt_id}",
            )
            return TaskResult(
                status="completed",
                outputs=(output_ref,),
                cache_hit=False,
            )
