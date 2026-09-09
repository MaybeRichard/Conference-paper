import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_crossref_isbi_title_is_encoded_once(monkeypatch, tmp_path):
    module = load_script("fetch_crossref", "scripts/medical/fetch_crossref.py")
    seen = []

    def fake_message(filter_value):
        seen.append(filter_value)
        return {"total-results": 1, "items": [{"title": ["fixture"]}]}

    monkeypatch.setattr(module, "crossref_message", fake_message)
    monkeypatch.setattr(sys, "argv", ["fetch_crossref.py", "--out", str(tmp_path),
                                        "--isbi", "2024",
                                        "2024 IEEE International Symposium on Biomedical Imaging (ISBI)"])
    module.main()

    assert seen == ["container-title:2024 IEEE International Symposium on Biomedical Imaging (ISBI)"]
    assert json.loads((tmp_path / "isbi_xref_2024.json").read_text())["total-results"] == 1


def test_medical_stage_dry_run_is_rejected_before_writing(tmp_path, fixture_repo):
    result = subprocess.run([
        sys.executable, str(ROOT / "scripts/medical-import.py"),
        "--corpus", str(fixture_repo), "--stage-from", str(tmp_path), "--dry-run",
    ], capture_output=True, text=True, check=False)
    assert result.returncode != 0
    assert "cannot be combined" in result.stderr
    assert not (fixture_repo / "corpus/sources/medical").exists()


def test_paperlists_dry_run_does_not_create_release_directory(tmp_path, fixture_repo):
    upstream = tmp_path / "paperlists"
    source = upstream / "aaai" / "aaai2021.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps([{
        "title": "A new fixture paper",
        "author": "Fixture Author",
        "abstract": "fixture",
        "status": "Poster",
        "track": "main",
        "id": "fixture-1",
        "site": "https://example.test/paper",
    }]))
    subprocess.run(["git", "init", "-q", str(upstream)], check=True)
    subprocess.run(["git", "-C", str(upstream), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(upstream), "-c", "user.name=Fixture",
        "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture",
    ], check=True)

    result = subprocess.run([
        sys.executable, str(ROOT / "scripts/paperlists-import.py"),
        "--corpus", str(fixture_repo), "--paperlists", str(upstream), "--dry-run",
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert not (fixture_repo / "corpus/releases/AAAI/2021").exists()


def test_new_snapshot_materialization_uses_manifest_checksums(tmp_path, fixture_repo):
    """A newly materialized snapshot must be independently recomputable."""
    (fixture_repo / "DATASET_MANIFEST.json").write_text(json.dumps({"files": []}))
    upstream = tmp_path / "paperlists"
    source = upstream / "aaai" / "aaai2021.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps([{
        "title": "Another fixture paper", "author": "Fixture Author",
        "abstract": "fixture", "status": "Poster", "track": "main", "id": "fixture-2",
    }]))
    subprocess.run(["git", "init", "-q", str(upstream)], check=True)
    subprocess.run(["git", "-C", str(upstream), "add", "."], check=True)
    subprocess.run([
        "git", "-C", str(upstream), "-c", "user.name=Fixture",
        "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture",
    ], check=True)

    result = subprocess.run([
        sys.executable, str(ROOT / "scripts/paperlists-import.py"),
        "--corpus", str(fixture_repo), "--paperlists", str(upstream),
    ], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

    registry = json.loads((fixture_repo / "corpus/registry.json").read_text())
    snapshot = json.loads((fixture_repo / "corpus/snapshots" /
                           registry["current_snapshot_id"] / "manifest.json").read_text())
    import hashlib
    materialization = "\n".join(sorted(
        f"{entry['release_id']}|{entry['manifest_checksum']}"
        for entry in snapshot["releases"]
    ))
    assert snapshot["materialization_checksum"] == hashlib.sha256(materialization.encode()).hexdigest()
