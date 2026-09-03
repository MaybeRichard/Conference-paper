"""Public entrypoint behavior; no fake research commands."""
import subprocess
import sys


def run_module(*args):
    return subprocess.run(
        [sys.executable, "-m", "research_agent", *args],
        capture_output=True, text=True, check=False,
    )


def test_module_version():
    result = run_module("--version")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "research-agent 0.1.0"


def test_help_describes_current_scope():
    result = run_module("--help")
    assert result.returncode == 0, result.stderr
    assert "--version" in result.stdout
    assert "not yet implemented" in result.stdout


def test_unimplemented_command_is_not_success():
    result = run_module("run", "example-workspace")
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
