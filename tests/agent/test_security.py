from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest

from research_agent.api import ResearchAgent
from research_agent.core.errors import PathViolation
from research_agent.core.store import ArtifactStore
from research_agent.core.tasks import TaskRunner


def _json_output(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.count("\n") <= 1, result.stdout
    return json.loads(result.stdout)


@pytest.mark.parametrize("relative", ["artifacts", "commits", "recovery"])
def test_store_rejects_symlinked_control_directory(
    tmp_path: Path,
    relative: str,
):
    workspace = tmp_path / "workspace"
    ArtifactStore(workspace)
    controlled = workspace / relative
    if controlled.is_dir():
        shutil.rmtree(controlled)
    outside = tmp_path / f"outside-{relative}"
    outside.mkdir()
    controlled.symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathViolation):
        ArtifactStore(workspace)

    assert list(outside.iterdir()) == []


def test_store_rejects_symlinked_artifact_namespace(tmp_path: Path):
    workspace = tmp_path / "workspace"
    store = ArtifactStore(workspace)
    outside = tmp_path / "outside-artifact"
    outside.mkdir()
    (workspace / "artifacts" / "brief").symlink_to(
        outside,
        target_is_directory=True,
    )

    with pytest.raises(PathViolation):
        store.commit("brief", 1, {"topic": "safe"}, [], "tx_safe")

    assert list(outside.iterdir()) == []


def test_two_processes_cannot_enter_the_same_workspace(
    fixture_repo: Path,
):
    state = ResearchAgent(fixture_repo).create_workspace(
        "二维医学图像扩散生成",
        "medical_diffusion_2d",
    )
    lock_path = fixture_repo / "workspaces" / state.workspace_id / ".workspace.lock"
    holder_source = textwrap.dedent(
        """
        import sys
        import time
        from filelock import FileLock

        lock = FileLock(sys.argv[1], timeout=1)
        with lock:
            print("locked", flush=True)
            time.sleep(5)
        """
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_source, str(lock_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "research_agent",
                "--repo",
                str(fixture_repo),
                "--json",
                "status",
                state.workspace_id,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        assert result.returncode == 6
        assert _json_output(result)["error"]["code"] == "busy"
    finally:
        holder.terminate()
        try:
            holder.wait(timeout=5)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait(timeout=5)


def test_decision_symlink_is_rejected_without_disclosing_target(
    fixture_repo: Path,
    tmp_path: Path,
):
    state = ResearchAgent(fixture_repo).create_workspace(
        "二维医学图像扩散生成",
        "medical_diffusion_2d",
    )
    secret = "PRIVATE-DECISION-CONTENT-MUST-NOT-LEAK"
    target = tmp_path / "private.yaml"
    target.write_text(secret, encoding="utf-8")
    link = tmp_path / "decision.yaml"
    link.symlink_to(target)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "research_agent",
            "--repo",
            str(fixture_repo),
            "--json",
            "gate",
            "approve",
            state.workspace_id,
            "--decision",
            str(link),
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert _json_output(result)["error"]["code"] == "input_error"
    assert secret not in result.stdout + result.stderr


def test_private_producer_error_is_not_persisted(tmp_path: Path):
    store = ArtifactStore(tmp_path / "workspace")
    private_message = "PRIVATE-PRODUCER-DETAIL-MUST-NOT-LEAK"

    def producer() -> dict:
        raise RuntimeError(private_message)

    result = TaskRunner(store).run(
        "private_failure_probe",
        (),
        {"version": "1"},
        producer,
    )

    assert result.status == "failed"
    persisted = "\n".join(
        path.read_text(encoding="utf-8")
        for path in store.root.rglob("*")
        if path.is_file() and path.name != ".workspace.lock"
    )
    assert private_message not in persisted
    assert "RuntimeError" in persisted
