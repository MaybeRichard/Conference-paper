from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_agent.core.errors import IntegrityError
from research_agent.core.store import ArtifactStore


class InjectedCrash(RuntimeError):
    pass


def crash_at(store: ArtifactStore, checkpoint: str) -> None:
    def hook(current: str) -> None:
        if current == checkpoint:
            raise InjectedCrash(current)

    store._fault_hook = hook


def event_payloads(store: ArtifactStore) -> list[dict]:
    return [entry["payload"] for entry in store.events()]


def test_crash_after_artifact_before_commit_marker_has_no_committed_result(tmp_path: Path):
    workspace = tmp_path / "ws"
    store = ArtifactStore(workspace)
    crash_at(store, "after_artifact_publish")

    with pytest.raises(InjectedCrash):
        store.commit("brief", 1, {"topic": "A"}, [{"type": "Created"}], "tx_1")

    reopened = ArtifactStore(workspace)
    reopened.recover()
    assert reopened.events() == []
    ref = reopened.commit("brief", 1, {"topic": "A"}, [{"type": "Created"}], "tx_2")
    assert reopened.read(ref)["topic"] == "A"
    assert list((workspace / "recovery" / "orphans").glob("*.json"))


def test_crash_after_commit_marker_recovers_events_exactly_once(tmp_path: Path):
    workspace = tmp_path / "ws"
    store = ArtifactStore(workspace)
    crash_at(store, "after_commit_publish")

    with pytest.raises(InjectedCrash):
        store.commit("brief", 1, {"topic": "A"}, [{"type": "Created"}], "tx_1")

    reopened = ArtifactStore(workspace)
    reopened.recover()
    assert event_payloads(reopened) == [{"type": "Created"}]
    ref = reopened.commit("brief", 1, {"topic": "A"}, [{"type": "Created"}], "tx_1")
    assert reopened.read(ref)["topic"] == "A"
    assert event_payloads(reopened) == [{"type": "Created"}]


def test_crash_after_event_sync_recovers_projection_without_duplicate(tmp_path: Path):
    workspace = tmp_path / "ws"
    store = ArtifactStore(workspace)
    crash_at(store, "after_events_sync")

    with pytest.raises(InjectedCrash):
        store.commit("brief", 1, {"topic": "A"}, [{"type": "Created"}], "tx_1")

    reopened = ArtifactStore(workspace)
    reopened.recover()
    assert event_payloads(reopened) == [{"type": "Created"}]
    projection = json.loads((workspace / "projection.json").read_text(encoding="utf-8"))
    assert projection == {"commit_count": 1, "event_count": 1, "last_sequence": 1}


def test_middle_event_log_corruption_is_never_silently_repaired(tmp_path: Path):
    workspace = tmp_path / "ws"
    store = ArtifactStore(workspace)
    store.commit("a", 1, {"v": 1}, [{"type": "A"}], "tx_1")
    store.commit("b", 1, {"v": 2}, [{"type": "B"}], "tx_2")

    log = workspace / "events.jsonl"
    lines = log.read_bytes().splitlines(keepends=True)
    log.write_bytes(b'{"broken":\n' + lines[1])

    with pytest.raises(IntegrityError):
        ArtifactStore(workspace).recover()


def test_partial_tail_is_preserved_and_rebuilt_from_commit_markers(tmp_path: Path):
    workspace = tmp_path / "ws"
    store = ArtifactStore(workspace)
    store.commit("a", 1, {"v": 1}, [{"type": "A"}], "tx_1")
    store.commit("b", 1, {"v": 2}, [{"type": "B"}], "tx_2")

    log = workspace / "events.jsonl"
    original = log.read_bytes()
    last_newline = original[:-1].rfind(b"\n") + 1
    log.write_bytes(original[:last_newline] + original[last_newline:last_newline + 11])

    reopened = ArtifactStore(workspace)
    reopened.recover()
    assert event_payloads(reopened) == [{"type": "A"}, {"type": "B"}]
    fault_copies = list((workspace / "recovery" / "faults").glob("events-*.jsonl"))
    assert len(fault_copies) == 1
    assert fault_copies[0].read_bytes().endswith(original[last_newline:last_newline + 11])


def test_commit_marker_tampering_is_detected(tmp_path: Path):
    workspace = tmp_path / "ws"
    store = ArtifactStore(workspace)
    store.commit("a", 1, {"v": 1}, [{"type": "A"}], "tx_1")

    marker = next((workspace / "commits").glob("*.json"))
    data = json.loads(marker.read_text(encoding="utf-8"))
    data["transaction_hash"] = "0" * 64
    marker.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(IntegrityError):
        ArtifactStore(workspace).recover()
