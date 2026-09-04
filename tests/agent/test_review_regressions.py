from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest
import yaml

from research_agent.api import ResearchAgent
from research_agent.core.errors import IntegrityError, PathViolation
from research_agent.core.gates import gate_for
from research_agent.core.store import ArtifactStore
from research_agent.core.workspace import WorkspaceService
from research_agent.schemas.workflow import WorkspaceState


def _json_output(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.count("\n") <= 1, result.stdout
    return json.loads(result.stdout)


def test_json_mode_without_command_returns_structured_input_error() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "research_agent", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert _json_output(result)["error"]["code"] == "input_error"
    assert "usage:" not in result.stdout


def test_validate_reports_busy_instead_of_invalid_workspace(fixture_repo: Path) -> None:
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

        with FileLock(sys.argv[1], timeout=1):
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
                "validate",
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


def test_store_rejects_symlinked_commit_marker_without_reading_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    store = ArtifactStore(workspace)
    store.commit("brief", 1, {"topic": "safe"}, [], "tx_safe")
    marker = next((workspace / "commits").glob("*.json"))
    outside = tmp_path / "outside-marker.json"
    shutil.move(marker, outside)
    original = outside.read_bytes()
    marker.symlink_to(outside)

    with pytest.raises(PathViolation):
        ArtifactStore(workspace).recover()

    assert outside.read_bytes() == original


def test_workspace_rejects_symlinked_projection_without_reading_target(
    fixture_repo: Path,
    tmp_path: Path,
) -> None:
    state = WorkspaceService(fixture_repo).create(
        "二维医学图像扩散生成",
        "medical_diffusion_2d",
    )
    projection = fixture_repo / "workspaces" / state.workspace_id / "workspace.yaml"
    outside = tmp_path / "outside-workspace.yaml"
    outside.write_bytes(projection.read_bytes())
    original = outside.read_bytes()
    projection.unlink()
    projection.symlink_to(outside)

    with pytest.raises(PathViolation):
        WorkspaceService(fixture_repo).get_state(state.workspace_id)

    assert outside.read_bytes() == original


def _workspace_refs(
    fixture_repo: Path,
    state: WorkspaceState,
) -> tuple[Path, ArtifactStore, dict]:
    workspace = fixture_repo / "workspaces" / state.workspace_id
    projection = yaml.safe_load(
        (workspace / "workspace.yaml").read_text(encoding="utf-8")
    )
    return workspace, ArtifactStore(workspace), projection


def test_reopen_rejects_brief_venue_that_disagrees_with_frozen_profile(
    fixture_repo: Path,
) -> None:
    service = WorkspaceService(fixture_repo)
    created = service.create("二维医学图像扩散生成", "medical_diffusion_2d")
    assert created.pending_gate is not None
    _workspace, store, projection = _workspace_refs(fixture_repo, created)
    bad_brief = store.read(created.pending_gate.artifact)
    bad_brief["target_venue"] = "CVPR"
    bad_ref = store.commit(
        "research_brief",
        2,
        bad_brief,
        [],
        "fixture_bad_venue_brief",
    )
    bad_state = WorkspaceState(
        workspace_id=created.workspace_id,
        snapshot_id=created.snapshot_id,
        stage="G1",
        status="waiting_for_user",
        pending_gate=gate_for("G1", bad_ref),
    )
    store.commit(
        "invalid_transition",
        1,
        {"reason": "fixture-only venue inconsistency"},
        [
            {
                "type": "WorkspaceStateChanged",
                "workspace_id": created.workspace_id,
                "state": bad_state.model_dump(mode="json"),
                "effective_config": projection["effective_config"],
                "research_brief": bad_ref.model_dump(mode="json"),
            }
        ],
        "fixture_bad_venue_transition",
    )

    with pytest.raises(IntegrityError):
        WorkspaceService(fixture_repo).get_state(created.workspace_id)


def test_reopen_rejects_pending_gate_not_bound_to_current_brief(
    fixture_repo: Path,
) -> None:
    service = WorkspaceService(fixture_repo)
    created = service.create("二维医学图像扩散生成", "medical_diffusion_2d")
    assert created.pending_gate is not None
    _workspace, store, projection = _workspace_refs(fixture_repo, created)
    new_ref = store.commit(
        "research_brief",
        2,
        store.read(created.pending_gate.artifact),
        [],
        "fixture_unbound_brief",
    )
    store.commit(
        "invalid_transition",
        1,
        {"reason": "fixture-only Gate/Brief inconsistency"},
        [
            {
                "type": "WorkspaceStateChanged",
                "workspace_id": created.workspace_id,
                "state": created.model_dump(mode="json"),
                "effective_config": projection["effective_config"],
                "research_brief": new_ref.model_dump(mode="json"),
            }
        ],
        "fixture_unbound_gate_transition",
    )

    with pytest.raises(IntegrityError):
        WorkspaceService(fixture_repo).get_state(created.workspace_id)
