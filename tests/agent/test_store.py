from __future__ import annotations

import json
from pathlib import Path

import pytest
from filelock import FileLock

from research_agent.core.errors import BusyError, ConflictError, IntegrityError
from research_agent.core.store import ArtifactStore


def event_payloads(store: ArtifactStore) -> list[dict]:
    return [entry["payload"] for entry in store.events()]


def test_artifact_is_immutable_reopenable_and_transaction_retry_is_idempotent(tmp_path: Path):
    workspace = tmp_path / "ws"
    store = ArtifactStore(workspace)
    events = [{"type": "BriefStored", "artifact_id": "brief"}]

    ref = store.commit("brief", 1, {"topic": "二维生成"}, events, "tx_1")
    assert ArtifactStore(workspace).read(ref)["topic"] == "二维生成"
    assert event_payloads(ArtifactStore(workspace)) == events

    retried = ArtifactStore(workspace).commit(
        "brief", 1, {"topic": "二维生成"}, events, "tx_1"
    )
    assert retried == ref
    assert len(ArtifactStore(workspace).events()) == 1

    with pytest.raises(ConflictError):
        store.commit("brief", 1, {"topic": "different"}, [], "tx_2")


def test_same_transaction_id_with_different_content_is_rejected(tmp_path: Path):
    store = ArtifactStore(tmp_path / "ws")
    store.commit("brief", 1, {"topic": "A"}, [], "request_1")

    with pytest.raises(ConflictError):
        store.commit("brief", 1, {"topic": "B"}, [], "request_1")


def test_invalid_identifiers_and_non_json_payloads_are_rejected(tmp_path: Path):
    store = ArtifactStore(tmp_path / "ws")

    for invalid in ("", "../brief", "brief.json", "brief/one", " brief"):
        with pytest.raises((ValueError, ConflictError)):
            store.commit(invalid, 1, {"ok": True}, [], "tx_valid")

    with pytest.raises(ValueError):
        store.commit("brief", 0, {"ok": True}, [], "tx_valid")
    with pytest.raises(ValueError):
        store.commit("brief", 1, {"value": float("nan")}, [], "tx_nan")


def test_committed_artifact_hash_tampering_is_detected(tmp_path: Path):
    workspace = tmp_path / "ws"
    store = ArtifactStore(workspace)
    ref = store.commit("brief", 1, {"topic": "A"}, [], "tx_1")

    artifact_path = workspace / "artifacts" / "brief" / "v00000001.json"
    envelope = json.loads(artifact_path.read_text(encoding="utf-8"))
    envelope["payload"]["topic"] = "tampered"
    artifact_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(IntegrityError):
        ArtifactStore(workspace).read(ref)


def test_busy_lock_maps_to_typed_error(tmp_path: Path):
    workspace = tmp_path / "ws"
    store = ArtifactStore(workspace, lock_timeout=0.01)
    lock_path = workspace / ".workspace.lock"

    with FileLock(lock_path, timeout=0.1):
        with pytest.raises(BusyError):
            store.events()
