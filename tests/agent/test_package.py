"""Public entrypoint behavior for the implemented M1 command surface."""
import subprocess
import sys


def run_module(*args):
    return subprocess.run(
        [sys.executable, "-m", "research_agent", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_module_version():
    result = run_module("--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "research-agent 0.1.0"


def test_help_describes_current_m1_command_surface():
    result = run_module("--help")
    assert result.returncode == 0, result.stderr
    assert "--version" in result.stdout
    assert "M1 foundations" in result.stdout
    for command in ("corpus", "workspace", "status", "gate", "run", "events", "validate"):
        assert command in result.stdout


def test_repository_command_requires_explicit_repo_root():
    result = run_module("run", "example-workspace")
    assert result.returncode == 2
    assert "input_error" in result.stdout
    assert "input_error" in result.stderr
