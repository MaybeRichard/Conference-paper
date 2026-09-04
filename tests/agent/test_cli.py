from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import yaml


def run_cli(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "research_agent",
            "--repo",
            str(repo),
            "--json",
            *arguments,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def run_json_raw(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "research_agent", "--json", *arguments],
        capture_output=True,
        text=True,
        check=False,
    )


def output(result: subprocess.CompletedProcess[str]) -> dict:
    assert result.stdout.count("\n") <= 1, result.stdout
    return json.loads(result.stdout)


def test_cli_runs_create_gate_approval_reopen_and_honest_block(
    fixture_repo: Path,
    tmp_path: Path,
):
    verified = run_cli(fixture_repo, "corpus", "verify")
    assert verified.returncode == 0, verified.stderr
    assert output(verified)["paper_count"] == 1

    created = run_cli(
        fixture_repo,
        "workspace",
        "create",
        "--domain",
        "medical_diffusion_2d",
        "--topic",
        "二维医学图像扩散生成",
    )
    assert created.returncode == 0, created.stderr
    state = output(created)
    workspace_id = state["workspace_id"]
    gate = state["pending_gate"]
    assert state["stage"] == "G1"
    assert state["status"] == "waiting_for_user"

    status = run_cli(fixture_repo, "status", workspace_id)
    shown_gate = run_cli(fixture_repo, "gate", "show", workspace_id)
    assert output(status) == state
    assert output(shown_gate) == {
        "workspace_id": workspace_id,
        "pending_gate": gate,
    }

    decision = tmp_path / "decision.yaml"
    decision.write_text(
        yaml.safe_dump(
            {
                "request_id": "cli_approval_1",
                "gate_id": gate["gate_id"],
                "artifact": gate["artifact"],
                "actor": "user",
                "action": "approve",
            },
            allow_unicode=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    approved = run_cli(
        fixture_repo,
        "gate",
        "approve",
        workspace_id,
        "--decision",
        str(decision),
    )
    assert approved.returncode == 0, approved.stderr
    approved_state = output(approved)
    assert approved_state["stage"] == "S2"
    assert approved_state["status"] == "not_started"
    assert approved_state["pending_gate"] is None

    blocked = run_cli(fixture_repo, "run", workspace_id, "--until", "next-gate")
    assert blocked.returncode == 5
    blocked_result = output(blocked)
    assert blocked_result["stage"] == "S2"
    assert blocked_result["status"] == "blocked"
    assert blocked_result["reason"] == "stage_handler_not_installed"
    assert blocked_result["new_artifacts"] == []

    reopened = run_cli(fixture_repo, "status", workspace_id)
    assert reopened.returncode == 0
    assert output(reopened) == approved_state

    validated = run_cli(fixture_repo, "validate", workspace_id)
    assert validated.returncode == 0
    assert output(validated)["valid"] is True

    events = run_cli(fixture_repo, "events", workspace_id)
    assert events.returncode == 0
    event_result = output(events)
    assert event_result["workspace_id"] == workspace_id
    assert any(
        item["payload"].get("type") == "GateApproved"
        for item in event_result["events"]
    )


def test_cli_revises_brief_from_strict_yaml(fixture_repo: Path, tmp_path: Path):
    created = run_cli(
        fixture_repo,
        "workspace",
        "create",
        "--domain",
        "medical_diffusion_2d",
        "--topic",
        "二维生成",
    )
    state = output(created)
    gate = state["pending_gate"]
    revision = tmp_path / "revision.yaml"
    revision.write_text(
        yaml.safe_dump(
            {
                "expected": gate["artifact"],
                "changes": {
                    "topic": "二维病灶条件生成",
                    "scope": {"allow_independent_ct_mri_slices": False},
                },
            },
            allow_unicode=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    revised = run_cli(
        fixture_repo,
        "gate",
        "revise",
        state["workspace_id"],
        "--revision",
        str(revision),
    )

    assert revised.returncode == 0, revised.stderr
    new_state = output(revised)
    assert new_state["pending_gate"]["artifact"]["version"] == 2
    assert new_state["pending_gate"]["gate_id"] != gate["gate_id"]


def test_cli_invalid_input_gate_conflict_integrity_and_json_cleanliness(
    fixture_repo: Path,
    tmp_path: Path,
):
    created = run_cli(
        fixture_repo,
        "workspace",
        "create",
        "--domain",
        "medical_diffusion_2d",
        "--topic",
        "二维生成",
    )
    state = output(created)
    gate = state["pending_gate"]

    invalid = tmp_path / "invalid.yaml"
    invalid.write_text(
        "request_id: invalid\ngate_id: gate\nartifact: {}\nactor: agent\naction: approve\nsecret: do-not-print\n",
        encoding="utf-8",
    )
    invalid_result = run_cli(
        fixture_repo,
        "gate",
        "approve",
        state["workspace_id"],
        "--decision",
        str(invalid),
    )
    assert invalid_result.returncode == 2
    assert output(invalid_result)["error"]["code"] == "input_error"
    assert "do-not-print" not in invalid_result.stdout + invalid_result.stderr

    wrong = tmp_path / "wrong.yaml"
    wrong_payload = {
        "request_id": "wrong_hash",
        "gate_id": gate["gate_id"],
        "artifact": {**gate["artifact"], "sha256": "0" * 64},
        "actor": "user",
        "action": "approve",
    }
    wrong.write_text(
        yaml.safe_dump(wrong_payload, sort_keys=True),
        encoding="utf-8",
    )
    wrong_result = run_cli(
        fixture_repo,
        "gate",
        "approve",
        state["workspace_id"],
        "--decision",
        str(wrong),
    )
    assert wrong_result.returncode == 3
    assert output(wrong_result)["error"]["code"] == "gate_error"

    shard = fixture_repo / "corpus/releases/TEST/2025/release_test/papers.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    corrupt = run_cli(fixture_repo, "corpus", "verify")
    assert corrupt.returncode == 4
    assert output(corrupt)["error"]["code"] == "integrity_error"


def test_cli_duplicate_yaml_keys_are_input_errors(fixture_repo: Path, tmp_path: Path):
    created = run_cli(
        fixture_repo,
        "workspace",
        "create",
        "--domain",
        "medical_diffusion_2d",
        "--topic",
        "二维生成",
    )
    state = output(created)
    decision = tmp_path / "duplicate.yaml"
    decision.write_text(
        "request_id: one\nrequest_id: two\ngate_id: x\nartifact: {}\nactor: user\naction: approve\n",
        encoding="utf-8",
    )

    result = run_cli(
        fixture_repo,
        "gate",
        "approve",
        state["workspace_id"],
        "--decision",
        str(decision),
    )

    assert result.returncode == 2
    assert output(result)["error"]["code"] == "input_error"


def test_cli_parser_errors_remain_machine_readable_in_json_mode():
    result = run_json_raw("not-a-command")

    assert result.returncode == 2
    assert output(result)["error"]["code"] == "input_error"
    assert result.stderr.count("\n") == 1
    assert "usage:" not in result.stdout
