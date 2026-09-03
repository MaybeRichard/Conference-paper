"""Recoverable immutable Artifact and append-only Event storage.

A commit marker is the visibility boundary. Artifact files published without a
marker are treated as orphans and quarantined on recovery. This store targets a
trusted, single-user local filesystem; it does not claim hostile-process or
remote-filesystem transaction guarantees.
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
from typing import Any, Callable, Iterator
from uuid import uuid4

from filelock import FileLock, Timeout

from research_agent.core.errors import BusyError, ConflictError, IntegrityError, PathViolation
from research_agent.core.serialization import canonical_bytes, digest
from research_agent.schemas.base import ArtifactRef

_IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]+$")
_ARTIFACT_FILE = re.compile(r"^v([0-9]{8})\.json$")
_COMMIT_FILE = re.compile(r"^([0-9]{20})-([A-Za-z0-9_-]+)\.json$")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite JSON number")
    return result


def _decode_mapping(raw: bytes, *, context: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
            parse_float=_finite_float,
        )
    except (UnicodeError, ValueError, RecursionError):
        raise IntegrityError(f"Invalid {context}; source content omitted") from None
    if not isinstance(value, dict):
        raise IntegrityError(f"Expected an object for {context}")
    return value


def _normalise_mapping(value: object, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a JSON object")
    try:
        return json.loads(canonical_bytes(value).decode("utf-8"))
    except (TypeError, ValueError, RecursionError):
        raise ValueError(f"{field} must contain finite canonical JSON values") from None


def _validate_identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"{field} must contain only letters, digits, underscore or hyphen")
    return value


def _fsync_directory(directory: Path) -> bool:
    """Best-effort POSIX directory fsync; return whether it succeeded."""
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        descriptor = os.open(directory, flags)
    except (AttributeError, OSError):
        return False
    try:
        os.fsync(descriptor)
    except OSError:
        return False
    finally:
        os.close(descriptor)
    return True


def _publish_bytes(path: Path, content: bytes, *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        if not replace and path.exists():
            raise ConflictError("Immutable storage target already exists")
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class ArtifactStore:
    """Persist immutable JSON Artifacts and recover their ordered Events."""

    def __init__(self, workspace_root: Path, *, lock_timeout: float = 2.0) -> None:
        root = Path(workspace_root).absolute()
        try:
            if root.is_symlink() or (root.exists() and not root.is_dir()):
                raise PathViolation("Workspace root must be a real directory")
            root.mkdir(parents=True, exist_ok=True)
            self.root = root.resolve()
        except OSError:
            raise PathViolation("Cannot create or resolve workspace storage") from None
        self.lock_timeout = lock_timeout
        self._lock_path = self.root / ".workspace.lock"
        self._fault_hook: Callable[[str], None] = lambda _checkpoint: None
        for relative in ("artifacts", "commits", "recovery/orphans", "recovery/faults"):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        lock = FileLock(str(self._lock_path), timeout=self.lock_timeout)
        try:
            with lock:
                yield
        except Timeout:
            raise BusyError("Workspace is busy; retry the operation") from None

    @property
    def _events_path(self) -> Path:
        return self.root / "events.jsonl"

    @property
    def _projection_path(self) -> Path:
        return self.root / "projection.json"

    def _artifact_path(self, artifact_id: str, version: int) -> Path:
        return self.root / "artifacts" / artifact_id / f"v{version:08d}.json"

    def _read_markers_locked(self) -> list[dict[str, Any]]:
        files = sorted((self.root / "commits").glob("*.json"))
        markers: list[dict[str, Any]] = []
        transactions: set[str] = set()
        references: set[tuple[str, int]] = set()
        for expected_sequence, path in enumerate(files, 1):
            match = _COMMIT_FILE.fullmatch(path.name)
            if match is None or int(match.group(1)) != expected_sequence:
                raise IntegrityError("Commit markers are missing, duplicated or out of order")
            marker = _decode_mapping(path.read_bytes(), context="commit marker")
            marker_hash = marker.get("marker_hash")
            body = {key: value for key, value in marker.items() if key != "marker_hash"}
            if not isinstance(marker_hash, str) or digest(body) != marker_hash:
                raise IntegrityError("Commit marker hash mismatch")
            if marker.get("schema_version") != "artifact-commit-v1":
                raise IntegrityError("Unsupported commit marker schema")
            if marker.get("sequence") != expected_sequence:
                raise IntegrityError("Commit marker sequence mismatch")
            transaction_id = marker.get("transaction_id")
            if (
                not isinstance(transaction_id, str)
                or _IDENTIFIER.fullmatch(transaction_id) is None
                or transaction_id != match.group(2)
                or transaction_id in transactions
            ):
                raise IntegrityError("Invalid or duplicate transaction ID")
            transactions.add(transaction_id)
            artifact = marker.get("artifact")
            events = marker.get("events")
            if not isinstance(artifact, dict) or not isinstance(events, list):
                raise IntegrityError("Commit marker has invalid artifact or events")
            try:
                ref = ArtifactRef.model_validate(artifact.get("ref"))
            except Exception:
                raise IntegrityError("Commit marker has invalid ArtifactRef") from None
            key = (ref.artifact_id, ref.version)
            if key in references:
                raise IntegrityError("Artifact version is committed more than once")
            references.add(key)
            expected_path = f"artifacts/{ref.artifact_id}/v{ref.version:08d}.json"
            if artifact.get("path") != expected_path:
                raise IntegrityError("Commit marker artifact path mismatch")
            normalised_events: list[dict[str, Any]] = []
            for index, event in enumerate(events):
                if not isinstance(event, dict):
                    raise IntegrityError("Commit marker event is not an object")
                expected_event_id = f"{transaction_id}_{index:04d}"
                if (
                    event.get("event_id") != expected_event_id
                    or event.get("transaction_id") != transaction_id
                    or event.get("sequence") != expected_sequence
                    or event.get("index") != index
                    or not isinstance(event.get("payload"), dict)
                ):
                    raise IntegrityError("Commit marker event identity mismatch")
                normalised_events.append(event["payload"])
            expected_transaction_hash = digest(
                {"artifact": ref.model_dump(mode="json"), "events": normalised_events}
            )
            if marker.get("transaction_hash") != expected_transaction_hash:
                raise IntegrityError("Transaction content hash mismatch")
            self._read_artifact_file_locked(ref)
            markers.append(marker)
        return markers

    def _read_artifact_file_locked(self, ref: ArtifactRef) -> dict[str, Any]:
        path = self._artifact_path(ref.artifact_id, ref.version)
        try:
            if not path.is_file() or path.is_symlink():
                raise IntegrityError("Committed Artifact is missing or not a regular file")
            envelope = _decode_mapping(path.read_bytes(), context="Artifact")
        except OSError:
            raise IntegrityError("Cannot read committed Artifact") from None
        if envelope.get("schema_version") != "artifact-v1":
            raise IntegrityError("Unsupported Artifact schema")
        if envelope.get("artifact_id") != ref.artifact_id or envelope.get("version") != ref.version:
            raise IntegrityError("Artifact identity mismatch")
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            raise IntegrityError("Artifact payload is not an object")
        if envelope.get("sha256") != ref.sha256 or digest(payload) != ref.sha256:
            raise IntegrityError("Artifact payload hash mismatch")
        return payload

    def _quarantine_orphans_locked(self, markers: list[dict[str, Any]]) -> None:
        committed = {
            marker["artifact"]["path"]
            for marker in markers
        }
        artifact_root = self.root / "artifacts"
        for path in sorted(artifact_root.glob("*/v*.json")):
            relative = path.relative_to(self.root).as_posix()
            if relative in committed:
                continue
            match = _ARTIFACT_FILE.fullmatch(path.name)
            if match is None or path.parent.parent != artifact_root:
                raise IntegrityError("Unexpected file in Artifact storage")
            destination = (
                self.root
                / "recovery"
                / "orphans"
                / f"{path.parent.name}-{path.stem}-{uuid4().hex}.json"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(path, destination)
            _fsync_directory(destination.parent)

    @staticmethod
    def _expected_events(markers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [event for marker in markers for event in marker["events"]]

    def _parse_complete_event_lines(self, raw: bytes) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for line in raw.splitlines():
            if not line.strip():
                raise IntegrityError("Event log contains an empty middle line")
            events.append(_decode_mapping(line, context="event log line"))
        return events

    def _sync_events_locked(self, markers: list[dict[str, Any]], *, allow_fault: bool) -> None:
        expected = self._expected_events(markers)
        path = self._events_path
        try:
            raw = path.read_bytes() if path.exists() else b""
        except OSError:
            raise IntegrityError("Cannot read event log") from None

        partial_tail = bool(raw) and not raw.endswith(b"\n")
        if partial_tail:
            complete_raw, _, _tail = raw.rpartition(b"\n")
            complete = self._parse_complete_event_lines(complete_raw) if complete_raw else []
            if complete != expected[: len(complete)]:
                raise IntegrityError("Event log diverges before its partial tail")
            fault = self.root / "recovery" / "faults" / f"events-{uuid4().hex}.jsonl"
            _publish_bytes(fault, raw, replace=False)
            content = b"".join(canonical_bytes(event) + b"\n" for event in expected)
            _publish_bytes(path, content, replace=True)
        else:
            current = self._parse_complete_event_lines(raw) if raw else []
            if current != expected[: len(current)] or len(current) > len(expected):
                raise IntegrityError("Event log is not a valid prefix of committed events")
            if len(current) < len(expected):
                path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with path.open("ab") as stream:
                        for event in expected[len(current):]:
                            stream.write(canonical_bytes(event) + b"\n")
                        stream.flush()
                        os.fsync(stream.fileno())
                    _fsync_directory(path.parent)
                except OSError:
                    raise IntegrityError("Cannot append committed events") from None

        if allow_fault:
            self._fault_hook("after_events_sync")
        projection = {
            "commit_count": len(markers),
            "event_count": len(expected),
            "last_sequence": len(markers),
        }
        _publish_bytes(self._projection_path, canonical_bytes(projection), replace=True)

    def _recover_locked(self) -> list[dict[str, Any]]:
        markers = self._read_markers_locked()
        self._quarantine_orphans_locked(markers)
        self._sync_events_locked(markers, allow_fault=False)
        return markers

    def recover(self) -> None:
        """Validate committed state, quarantine orphans and repair derived files."""
        with self._locked():
            self._recover_locked()

    def commit(
        self,
        artifact_id: str,
        version: int,
        payload: dict,
        events: list[dict],
        transaction_id: str,
    ) -> ArtifactRef:
        """Commit one immutable Artifact and zero or more Events atomically."""
        artifact_id = _validate_identifier(artifact_id, field="artifact_id")
        transaction_id = _validate_identifier(transaction_id, field="transaction_id")
        if type(version) is not int or version < 1:
            raise ValueError("version must be an integer >= 1")
        normalised_payload = _normalise_mapping(payload, field="payload")
        if not isinstance(events, list):
            raise ValueError("events must be a list of JSON objects")
        normalised_events = [_normalise_mapping(event, field="event") for event in events]
        ref = ArtifactRef(
            artifact_id=artifact_id,
            version=version,
            sha256=digest(normalised_payload),
        )
        transaction_hash = digest(
            {"artifact": ref.model_dump(mode="json"), "events": normalised_events}
        )

        with self._locked():
            markers = self._recover_locked()
            by_transaction = {marker["transaction_id"]: marker for marker in markers}
            existing = by_transaction.get(transaction_id)
            if existing is not None:
                if existing["transaction_hash"] != transaction_hash:
                    raise ConflictError("Transaction ID was already used with different content")
                return ArtifactRef.model_validate(existing["artifact"]["ref"])

            if any(
                marker["artifact"]["ref"]["artifact_id"] == artifact_id
                and marker["artifact"]["ref"]["version"] == version
                for marker in markers
            ):
                raise ConflictError("Artifact version is immutable")

            artifact_path = self._artifact_path(artifact_id, version)
            artifact_envelope = {
                "schema_version": "artifact-v1",
                "artifact_id": artifact_id,
                "version": version,
                "sha256": ref.sha256,
                "payload": normalised_payload,
            }
            _publish_bytes(artifact_path, canonical_bytes(artifact_envelope), replace=False)
            self._fault_hook("after_artifact_publish")

            sequence = len(markers) + 1
            event_records = [
                {
                    "event_id": f"{transaction_id}_{index:04d}",
                    "transaction_id": transaction_id,
                    "sequence": sequence,
                    "index": index,
                    "payload": event,
                }
                for index, event in enumerate(normalised_events)
            ]
            marker_body = {
                "schema_version": "artifact-commit-v1",
                "sequence": sequence,
                "transaction_id": transaction_id,
                "transaction_hash": transaction_hash,
                "artifact": {
                    "ref": ref.model_dump(mode="json"),
                    "path": artifact_path.relative_to(self.root).as_posix(),
                },
                "events": event_records,
            }
            marker = {**marker_body, "marker_hash": digest(marker_body)}
            marker_path = self.root / "commits" / f"{sequence:020d}-{transaction_id}.json"
            _publish_bytes(marker_path, canonical_bytes(marker), replace=False)
            self._fault_hook("after_commit_publish")

            markers.append(marker)
            self._sync_events_locked(markers, allow_fault=True)
            return ref

    def read(self, ref: ArtifactRef) -> dict[str, Any]:
        """Return a committed payload after validating its marker and hash."""
        ref = ArtifactRef.model_validate(ref)
        with self._locked():
            markers = self._recover_locked()
            visible = {
                (
                    marker["artifact"]["ref"]["artifact_id"],
                    marker["artifact"]["ref"]["version"],
                    marker["artifact"]["ref"]["sha256"],
                )
                for marker in markers
            }
            if (ref.artifact_id, ref.version, ref.sha256) not in visible:
                raise IntegrityError("Artifact reference is not committed")
            return deepcopy(self._read_artifact_file_locked(ref))

    def events(self) -> list[dict[str, Any]]:
        """Return ordered committed Event envelopes after recovery."""
        with self._locked():
            markers = self._recover_locked()
            return deepcopy(self._expected_events(markers))
