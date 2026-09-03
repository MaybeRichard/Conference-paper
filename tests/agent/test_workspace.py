from __future__ import annotations

from datetime import date
import json
from pathlib import Path
import shutil

import pytest
import yaml

from research_agent.core.errors import GateError, IntegrityError
from research_agent.core.store import ArtifactStore
from research_agent.core.workspace import WorkspaceService
from research_agent.schemas.base import ArtifactRef
from tests.agent.corpus_factory import make_corpus


DOMAIN_RELATIVE = Path("domains/medical_diffusion_2d/domain.yaml")


def prepare_repo(tmp_path: Path) -> Path:
    repo = make_corpus(tmp_path / "repo")
    source = Path(__file__).resolve().parents[2] / DOMAIN_RELATIVE
    destination = repo / DOMAIN_RELATIVE
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return repo


def state_events(repo: Path, workspace_id: str) -> list[dict]:
    store = ArtifactStore(repo / "workspaces" / workspace_id)
    return [
        item["payload"]
        for item in store.events()
        if item["payload"]["type"] == "WorkspaceStateChanged"
    ]


def test_create_verifies_snapshot_freezes_config_and_opens_g1(tmp_path: Path, monkeypatch):
    repo = prepare_repo(tmp_path)
    monkeypatch.setattr(
        "research_agent.core.workspace._utc_today",
        lambda: date(2026, 9, 3),
    )

    service = WorkspaceService(repo)
    state = service.create("二维医学图像扩散生成", "medical_diffusion_2d")

    assert state.snapshot_id == "snapshot_test"
    assert state.stage == "G1"
    assert state.status == "waiting_for_user"
    assert state.pending_gate is not None
    assert state.pending_gate.kind == "G1"
    assert (repo / "workspaces" / state.workspace_id / "workspace.yaml").is_file()
    assert not list((repo / "workspaces").glob("_creating_*"))

    store = ArtifactStore(repo / "workspaces" / state.workspace_id)
    brief = store.read(state.pending_gate.artifact)
    assert brief["topic"] == "二维医学图像扩散生成"
    assert brief["target_venue"] == "MICCAI"
    assert brief["start_date"] == "2021-09-03"
    assert brief["end_date"] == "2026-09-03"
    assert brief["scope"]["allow_independent_ct_mri_slices"] is True
    assert brief["scope"]["allow_2_5d"] is False
    assert brief["scope"]["allow_3d"] is False

    projection = yaml.safe_load(
        (repo / "workspaces" / state.workspace_id / "workspace.yaml").read_text(
            encoding="utf-8"
        )
    )
    config_ref = ArtifactRef.model_validate(projection["effective_config"])
    frozen = store.read(config_ref)
    assert frozen["domain"] == "medical_diffusion_2d"
    assert frozen["policies"]["fulltext_mode"] == "hybrid"


def test_external_domain_changes_do_not_change_existing_workspace(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    service = WorkspaceService(repo)
    created = service.create("二维生成", "medical_diffusion_2d")
    before = (repo / "workspaces" / created.workspace_id / "workspace.yaml").read_bytes()

    (repo / DOMAIN_RELATIVE).write_text("domain: changed\n", encoding="utf-8")
    reopened = WorkspaceService(repo).get_state(created.workspace_id)

    assert reopened == created
    after = (repo / "workspaces" / created.workspace_id / "workspace.yaml").read_bytes()
    assert after == before


def test_create_failure_does_not_publish_half_workspace(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    shard = repo / "corpus/releases/TEST/2025/release_test/papers.jsonl"
    shard.write_text("{}\n", encoding="utf-8")

    with pytest.raises(IntegrityError):
        WorkspaceService(repo).create("二维生成", "medical_diffusion_2d")

    workspaces = repo / "workspaces"
    assert not workspaces.exists() or list(workspaces.iterdir()) == []


def test_unknown_or_malformed_domain_is_rejected(tmp_path: Path):
    repo = make_corpus(tmp_path / "repo")
    service = WorkspaceService(repo)

    with pytest.raises(IntegrityError):
        service.create("二维生成", "unknown_domain")

    destination = repo / DOMAIN_RELATIVE
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        """domain: medical_diffusion_2d
target_venue: MICCAI
"
        "scope: {dimensionality: 2d, allow_independent_ct_mri_slices: true, allow_2_5d: false, allow_3d: false, primary_tasks: [generation]}
"
        "policies: {fulltext_mode: hybrid, local_corpus_first: true, external_search_allowed: true, contribution_style: method_primary, data_resource_levels: [L1], compute_hard_limit: null}
"
        "unexpected: true
""",
        encoding="utf-8",
    )
    with pytest.raises(IntegrityError):
        service.create("二维生成", "medical_diffusion_2d")


def test_domain_yaml_duplicate_keys_and_implicit_boolean_words_are_rejected(tmp_path: Path):
    repo = make_corpus(tmp_path / "repo")
    destination = repo / DOMAIN_RELATIVE
    destination.parent.mkdir(parents=True, exist_ok=True)
    valid = (Path(__file__).resolve().parents[2] / DOMAIN_RELATIVE).read_text(
        encoding="utf-8"
    )

    destination.write_text(
        valid.replace(
            "target_venue: MICCAI",
            "target_venue: MICCAI\ntarget_venue: Other",
        ),
        encoding="utf-8",
    )
    with pytest.raises(IntegrityError):
        WorkspaceService(repo).create("二维生成", "medical_diffusion_2d")

    destination.write_text(
        valid.replace("allow_3d: false", "allow_3d: no"),
        encoding="utf-8",
    )
    with pytest.raises(IntegrityError):
        WorkspaceService(repo).create("二维生成", "medical_diffusion_2d")


def test_leap_day_start_date_is_clamped_to_last_valid_day(tmp_path: Path, monkeypatch):
    repo = prepare_repo(tmp_path)
    monkeypatch.setattr(
        "research_agent.core.workspace._utc_today",
        lambda: date(2024, 2, 29),
    )

    state = WorkspaceService(repo).create("二维生成", "medical_diffusion_2d")
    store = ArtifactStore(repo / "workspaces" / state.workspace_id)
    brief = store.read(state.pending_gate.artifact)

    assert brief["start_date"] == "2019-02-28"
    assert brief["end_date"] == "2024-02-29"


def test_revise_brief_creates_new_bound_gate_and_keeps_history(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    service = WorkspaceService(repo)
    created = service.create("二维医学图像扩散生成", "medical_diffusion_2d")
    old_gate = service.get_gate(created.workspace_id)
    assert old_gate is not None

    revised = service.revise_brief(
        created.workspace_id,
        old_gate.artifact,
        {"topic": "二维病灶条件生成", "scope": {"focus": "lesion_conditioned"}},
    )

    assert revised.stage == "G1" and revised.status == "waiting_for_user"
    assert revised.pending_gate is not None
    assert revised.pending_gate.gate_id != old_gate.gate_id
    assert revised.pending_gate.artifact.version == old_gate.artifact.version + 1
    store = ArtifactStore(repo / "workspaces" / created.workspace_id)
    old = store.read(old_gate.artifact)
    new = store.read(revised.pending_gate.artifact)
    assert old["topic"] == "二维医学图像扩散生成"
    assert new["topic"] == "二维病灶条件生成"
    assert new["scope"]["focus"] == "lesion_conditioned"
    assert new["supersedes"] == old_gate.artifact.model_dump(mode="json")
    assert len(state_events(repo, created.workspace_id)) == 2


def test_revise_rejects_immutable_fields_and_3d_scope(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    service = WorkspaceService(repo)
    state = service.create("二维生成", "medical_diffusion_2d")
    gate = service.get_gate(state.workspace_id)
    assert gate is not None

    with pytest.raises(GateError):
        service.revise_brief(state.workspace_id, gate.artifact, {"domain": "other"})
    with pytest.raises(GateError):
        service.revise_brief(
            state.workspace_id,
            gate.artifact,
            {"scope": {"allow_3d": True}},
        )


def test_workspace_projection_is_derived_and_repaired_on_reopen(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    created = WorkspaceService(repo).create("二维生成", "medical_diffusion_2d")
    projection = repo / "workspaces" / created.workspace_id / "workspace.yaml"
    projection.write_text("tampered: true\n", encoding="utf-8")

    reopened = WorkspaceService(repo).get_state(created.workspace_id)
    repaired = yaml.safe_load(projection.read_text(encoding="utf-8"))

    assert reopened == created
    assert repaired["state"]["workspace_id"] == created.workspace_id
    assert repaired["schema_version"] == "workspace-projection-v1"


def test_revision_may_narrow_slice_scope_but_cannot_change_venue_profile(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    service = WorkspaceService(repo)
    created = service.create("二维生成", "medical_diffusion_2d")
    gate = created.pending_gate
    assert gate is not None

    narrowed = service.revise_brief(
        created.workspace_id,
        gate.artifact,
        {"scope": {"allow_independent_ct_mri_slices": False}},
    )
    assert narrowed.pending_gate is not None
    store = ArtifactStore(repo / "workspaces" / created.workspace_id)
    brief = store.read(narrowed.pending_gate.artifact)
    assert brief["scope"]["allow_independent_ct_mri_slices"] is False

    with pytest.raises(GateError):
        service.revise_brief(
            created.workspace_id,
            narrowed.pending_gate.artifact,
            {"target_venue": "CVPR"},
        )


def test_reopen_rejects_state_that_disagrees_with_frozen_config_and_brief(tmp_path: Path):
    repo = prepare_repo(tmp_path)
    created = WorkspaceService(repo).create("二维生成", "medical_diffusion_2d")
    workspace = repo / "workspaces" / created.workspace_id
    projection = yaml.safe_load((workspace / "workspace.yaml").read_text(encoding="utf-8"))
    store = ArtifactStore(workspace)
    inconsistent = created.model_copy(update={"snapshot_id": "snapshot_other"})
    store.commit(
        "invalid_transition",
        1,
        {"reason": "fixture-only internal inconsistency"},
        [
            {
                "type": "WorkspaceStateChanged",
                "workspace_id": created.workspace_id,
                "state": inconsistent.model_dump(mode="json"),
                "effective_config": projection["effective_config"],
                "research_brief": projection["research_brief"],
            }
        ],
        "fixture_invalid_transition",
    )

    with pytest.raises(IntegrityError):
        WorkspaceService(repo).get_state(created.workspace_id)
