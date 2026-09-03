from __future__ import annotations

from pathlib import Path

import pytest

from research_agent.core.errors import IntegrityError
from research_agent.core.store import ArtifactStore
from research_agent.core.tasks import TaskRunner, task_fingerprint


def _input(store: ArtifactStore, name: str, version: int, value: int):
    return store.commit(
        name,
        version,
        {"value": value},
        [{"type": "FixtureInputCommitted", "name": name, "version": version}],
        f"fixture_{name}_{version}_{value}",
    )


def test_completed_task_reused_only_after_hash_check(tmp_path: Path):
    store = ArtifactStore(tmp_path / "ws")
    calls: list[int] = []

    def producer():
        calls.append(1)
        return {"value": 7}

    runner = TaskRunner(store)
    first = runner.run("fixture_probe", (), {"version": "1"}, producer)
    second = TaskRunner(ArtifactStore(tmp_path / "ws")).run(
        "fixture_probe", (), {"version": "1"}, producer
    )

    assert first.status == second.status == "completed"
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.outputs == first.outputs
    assert len(calls) == 1
    payload = store.read(first.outputs[0])
    assert payload["result"] == {"value": 7}
    assert payload["fingerprint"] == task_fingerprint(
        "fixture_probe", (), {"version": "1"}
    )


def test_profile_key_order_and_default_version_are_canonical(tmp_path: Path):
    store = ArtifactStore(tmp_path / "ws")
    calls: list[int] = []

    def producer():
        calls.append(1)
        return {"ok": True}

    first = TaskRunner(store).run(
        "ordered_profile", (), {"alpha": 1, "nested": {"b": 2, "a": 1}}, producer
    )
    second = TaskRunner(store).run(
        "ordered_profile", (), {"nested": {"a": 1, "b": 2}, "alpha": 1}, producer
    )

    assert first.outputs == second.outputs
    assert second.cache_hit is True
    assert len(calls) == 1


def test_profile_or_exact_input_ref_change_does_not_hit_cache(tmp_path: Path):
    store = ArtifactStore(tmp_path / "ws")
    input_v1 = _input(store, "source", 1, 1)
    input_v2 = _input(store, "source", 2, 2)
    calls: list[int] = []

    def producer():
        calls.append(1)
        return {"attempt": len(calls)}

    first = TaskRunner(store).run(
        "input_sensitive", (input_v1,), {"version": "1"}, producer
    )
    changed_profile = TaskRunner(store).run(
        "input_sensitive", (input_v1,), {"version": "2"}, producer
    )
    changed_input = TaskRunner(store).run(
        "input_sensitive", (input_v2,), {"version": "1"}, producer
    )

    assert len({first.outputs[0], changed_profile.outputs[0], changed_input.outputs[0]}) == 3
    assert calls == [1, 1, 1]
    assert not first.cache_hit and not changed_profile.cache_hit and not changed_input.cache_hit


def test_missing_or_wrong_hash_input_is_rejected_before_producer(tmp_path: Path):
    store = ArtifactStore(tmp_path / "ws")
    ref = _input(store, "source", 1, 1)
    wrong = ref.model_copy(update={"sha256": "0" * 64})
    called = False

    def producer():
        nonlocal called
        called = True
        return {"unreachable": True}

    with pytest.raises(IntegrityError):
        TaskRunner(store).run("verify_input", (wrong,), {"version": "1"}, producer)
    assert called is False


def test_producer_failure_is_recorded_without_completed_result_and_can_retry(tmp_path: Path):
    store = ArtifactStore(tmp_path / "ws")
    attempts = 0

    def producer():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("private producer detail must not be persisted")
        return {"value": 9}

    first = TaskRunner(store).run("retryable_probe", (), {"version": "1"}, producer)
    second = TaskRunner(ArtifactStore(tmp_path / "ws")).run(
        "retryable_probe", (), {"version": "1"}, producer
    )

    assert first.status == "failed"
    assert first.reason == "producer_failed"
    assert first.outputs == ()
    assert second.status == "completed"
    assert second.cache_hit is False
    assert attempts == 2

    payloads = [event["payload"] for event in store.events()]
    assert sum(item.get("type") == "TaskCompleted" for item in payloads) == 1
    assert "private producer detail" not in str(payloads)


def test_corrupted_cached_output_is_rejected_not_silently_recomputed(tmp_path: Path):
    store = ArtifactStore(tmp_path / "ws")
    result = TaskRunner(store).run(
        "corruption_probe", (), {"version": "1"}, lambda: {"value": 1}
    )
    ref = result.outputs[0]
    artifact = (
        store.root
        / "artifacts"
        / ref.artifact_id
        / f"v{ref.version:08d}.json"
    )
    artifact.write_text("{}", encoding="utf-8")
    called = False

    def producer():
        nonlocal called
        called = True
        return {"value": 2}

    with pytest.raises(IntegrityError):
        TaskRunner(ArtifactStore(tmp_path / "ws")).run(
            "corruption_probe", (), {"version": "1"}, producer
        )
    assert called is False


def test_operation_and_profile_reject_noncanonical_inputs(tmp_path: Path):
    runner = TaskRunner(ArtifactStore(tmp_path / "ws"))

    with pytest.raises(ValueError):
        runner.run("contains spaces", (), {"version": "1"}, lambda: {})
    with pytest.raises(ValueError):
        runner.run("valid_name", (), {"value": float("nan")}, lambda: {})
