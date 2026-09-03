"""Read-only integrity tests; synthetic fixture results are not full-corpus results."""
import hashlib
import os
from pathlib import Path

import pytest

from tests.agent.corpus_factory import (make_corpus, read_json, write_json, rehash,
                                       REGISTRY, SNAPSHOT, RELEASE, SHARD)


def adapter(root):
    from research_agent.adapters.corpus_adapter import CorpusAdapter
    return CorpusAdapter(root)


def test_fixture_verifies_and_preserves_unicode_and_unknown_fields(tmp_path):
    repo = make_corpus(tmp_path)
    result = adapter(repo).verify()
    assert result.snapshot_id == "snapshot_test"
    assert (result.paper_count, result.release_count, result.verified_files) == (1, 1, 3)
    assert result.snapshot_checksum == hashlib.sha256((repo / SNAPSHOT).read_bytes()).hexdigest()
    records = list(adapter(repo).iter_records("snapshot_test"))
    assert len(records) == 1
    assert records[0]["paper"]["abstract"] == "a\u2028b\u0085c"
    assert records[0]["upstream_extension"] == {"preserve": True}


@pytest.mark.parametrize("relative", [SNAPSHOT, RELEASE, SHARD])
def test_any_changed_referenced_file_rejected(tmp_path, relative):
    from research_agent.core.errors import IntegrityError
    repo = make_corpus(tmp_path)
    with (repo / relative).open("ab") as stream:
        stream.write(b" ")
    with pytest.raises(IntegrityError):
        adapter(repo).verify()


def test_no_corrupt_records_yielded_without_explicit_verify(tmp_path):
    from research_agent.core.errors import IntegrityError
    repo = make_corpus(tmp_path)
    a = adapter(repo)
    a.verify()
    (repo / SHARD).write_text('{}\n', encoding="utf-8")
    with pytest.raises(IntegrityError):
        next(a.iter_records("snapshot_test"))


@pytest.mark.parametrize("change", [{"release_id": "wrong"}, {"conference": "wrong"},
    {"year": 2024}, {"year": True}, {"paper_count": 2}, {"paper_count": True}])
def test_semantic_release_mismatch_rejected_with_valid_hashes(tmp_path, change):
    from research_agent.core.errors import IntegrityError
    repo = make_corpus(tmp_path)
    write_json(repo, RELEASE, read_json(repo, RELEASE) | change)
    rehash(repo)
    with pytest.raises(IntegrityError):
        adapter(repo).verify()


@pytest.mark.parametrize("change", [{"snapshot_id": "wrong"}, {"paper_count": 2},
    {"paper_count": -1}, {"paper_count": True}, {"releases": "not-a-list"}])
def test_semantic_snapshot_mismatch_rejected(tmp_path, change):
    from research_agent.core.errors import IntegrityError
    repo = make_corpus(tmp_path)
    snapshot = read_json(repo, SNAPSHOT) | change
    checksum = write_json(repo, SNAPSHOT, snapshot)
    registry = read_json(repo, REGISTRY)
    registry["snapshots"][0]["manifest_checksum"] = checksum
    write_json(repo, REGISTRY, registry)
    with pytest.raises(IntegrityError):
        adapter(repo).verify()


@pytest.mark.parametrize("snapshot_id", ["missing", "", "../outside"])
def test_unknown_snapshot_rejected(tmp_path, snapshot_id):
    from research_agent.core.errors import IntegrityError
    repo = make_corpus(tmp_path)
    with pytest.raises(IntegrityError):
        adapter(repo).verify(snapshot_id)


def test_selected_historical_snapshot_not_current_or_registry_releases(tmp_path):
    repo = make_corpus(tmp_path)
    old = "corpus/snapshots/snapshot_old/manifest.json"
    checksum = write_json(repo, old, {"snapshot_id": "snapshot_old", "paper_count": 0, "releases": []})
    registry = read_json(repo, REGISTRY)
    registry["snapshots"].append({"snapshot_id": "snapshot_old", "manifest_path": old,
                                  "manifest_checksum": checksum})
    write_json(repo, REGISTRY, registry)
    a = adapter(repo)
    assert a.verify().paper_count == 1
    assert a.verify("snapshot_old").paper_count == 0
    assert list(a.iter_records("snapshot_old")) == []


@pytest.mark.parametrize("relative", ["README.md", "../outside.json", "corpus/../README.md",
                                     "/tmp/outside.json", "corpus/link/file.json"])
def test_registry_paths_cannot_escape_corpus(tmp_path, relative):
    from research_agent.core.errors import PathViolation
    repo = make_corpus(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "corpus/link").symlink_to(outside, target_is_directory=True)
    registry = read_json(repo, REGISTRY)
    registry["snapshots"][0]["manifest_path"] = relative
    write_json(repo, REGISTRY, registry)
    with pytest.raises(PathViolation):
        adapter(repo).verify()


def test_shard_cannot_point_to_protected_repo_files(tmp_path):
    from research_agent.core.errors import PathViolation
    repo = make_corpus(tmp_path)
    write_json(repo, RELEASE, read_json(repo, RELEASE) | {"paper_shard_path": "README.md"})
    rehash(repo)
    with pytest.raises(PathViolation):
        adapter(repo).verify()


def test_duplicate_snapshot_reference_rejected(tmp_path):
    from research_agent.core.errors import IntegrityError
    repo = make_corpus(tmp_path)
    registry = read_json(repo, REGISTRY)
    registry["snapshots"] *= 2
    write_json(repo, REGISTRY, registry)
    with pytest.raises(IntegrityError):
        adapter(repo).verify()


def test_duplicate_release_reference_rejected(tmp_path):
    from research_agent.core.errors import IntegrityError
    repo = make_corpus(tmp_path)
    snapshot = read_json(repo, SNAPSHOT)
    snapshot["releases"] *= 2
    snapshot["paper_count"] = 2
    write_json(repo, SNAPSHOT, snapshot)
    rehash(repo)
    with pytest.raises(IntegrityError):
        adapter(repo).verify()


@pytest.mark.parametrize("content", [b"{broken}\n", b"[]\n", b"null\n", b"\xff\n",
    b'{"x":NaN}\n', b'{"x":1,"x":2}\n'])
def test_malformed_jsonl_rejected_even_with_matching_checksum(tmp_path, content):
    from research_agent.core.errors import IntegrityError
    repo = make_corpus(tmp_path)
    (repo / SHARD).write_bytes(content)
    rehash(repo)
    with pytest.raises(IntegrityError):
        adapter(repo).verify()


@pytest.mark.parametrize("change", [{"manifest_checksum": "bad"}, {"manifest_checksum": True},
                                    {"manifest_path": None}])
def test_bad_reference_fields_rejected(tmp_path, change):
    from research_agent.core.errors import ResearchAgentError
    repo = make_corpus(tmp_path)
    registry = read_json(repo, REGISTRY)
    registry["snapshots"][0].update(change)
    write_json(repo, REGISTRY, registry)
    with pytest.raises(ResearchAgentError):
        adapter(repo).verify()


def test_missing_file_is_safe_integrity_error(tmp_path):
    from research_agent.core.errors import IntegrityError
    repo = make_corpus(tmp_path)
    (repo / SHARD).unlink()
    with pytest.raises(IntegrityError):
        adapter(repo).verify()


def test_source_content_not_echoed_in_parse_error(tmp_path):
    from research_agent.core.errors import IntegrityError
    repo = make_corpus(tmp_path)
    (repo / SHARD).write_text("private_patient_note\n", encoding="utf-8")
    rehash(repo)
    with pytest.raises(IntegrityError) as error:
        adapter(repo).verify()
    assert "private_patient_note" not in str(error.value)


def test_empty_lines_and_no_final_newline_supported(tmp_path):
    repo = make_corpus(tmp_path)
    data = (repo / SHARD).read_bytes().rstrip(b"\n")
    (repo / SHARD).write_bytes(b"\n" + data)
    rehash(repo)
    assert adapter(repo).verify().paper_count == 1


def test_file_names_bytes_and_mtimes_unchanged(tmp_path):
    repo = make_corpus(tmp_path)
    def inventory():
        return {str(p.relative_to(repo)): (hashlib.sha256(p.read_bytes()).hexdigest(),
                p.stat().st_mtime_ns) for p in repo.rglob("*") if p.is_file()}
    before = inventory()
    a = adapter(repo)
    a.verify()
    list(a.iter_records("snapshot_test"))
    assert inventory() == before


@pytest.mark.real_corpus
def test_real_corpus_integrity():
    configured = os.environ.get("RESEARCH_AGENT_CORPUS_ROOT")
    repo = Path(configured) if configured else Path(__file__).resolve().parents[2]
    if not (repo / REGISTRY).is_file() and configured is None:
        pytest.skip("Complete real corpus is not mounted; fixture tests do not replace this check")
    # An explicitly configured missing/broken corpus must fail, never silently skip.
    result = adapter(repo).verify()
    snapshot = read_json(repo, REGISTRY)
    assert result.snapshot_id == snapshot["current_snapshot_id"]
    assert result.paper_count >= 0
    inventory = read_json(repo, "DATASET_MANIFEST.json")
    assert result.paper_count == inventory["paper_count"]
    assert result.release_count == inventory["release_count"]
