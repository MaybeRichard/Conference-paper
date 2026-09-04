"""Synthetic metadata ONLY. Hash chain mirrors the repository's real schema."""
import hashlib
import json
from pathlib import Path

SHARD = "corpus/releases/TEST/2025/release_test/papers.jsonl"
RELEASE = "corpus/releases/TEST/2025/release_test/manifest.json"
SNAPSHOT = "corpus/snapshots/snapshot_test/manifest.json"
REGISTRY = "corpus/registry.json"


def write_bytes(root: Path, relative: str, content: bytes) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def write_json(root: Path, relative: str, value: dict) -> str:
    return write_bytes(root, relative, json.dumps(value, ensure_ascii=False).encode("utf-8"))


def read_json(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def rehash(root: Path) -> None:
    """Refresh byte hashes only, leaving semantic fields for negative tests."""
    release = read_json(root, RELEASE)
    release["paper_shard_checksum"] = hashlib.sha256((root / SHARD).read_bytes()).hexdigest()
    release_hash = write_json(root, RELEASE, release)
    snapshot = read_json(root, SNAPSHOT)
    for entry in snapshot["releases"]:
        if entry.get("manifest_path") == RELEASE:
            entry["manifest_checksum"] = release_hash
    snapshot_hash = write_json(root, SNAPSHOT, snapshot)
    registry = read_json(root, REGISTRY)
    for entry in registry["snapshots"]:
        if entry.get("manifest_path") == SNAPSHOT:
            entry["manifest_checksum"] = snapshot_hash
    write_json(root, REGISTRY, registry)


def make_corpus(root: Path) -> Path:
    record = {"paper_id": "fixture_p1", "canonical_title": "Fixture only",
              "paper": {"title": "Fixture only", "abstract": "a\u2028b\u0085c",
                        "conference": "TEST", "year": 2025},
              "upstream_extension": {"preserve": True}}
    shard_hash = write_bytes(root, SHARD, (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    release_hash = write_json(root, RELEASE, {
        "release_id": "release_test", "conference": "TEST", "year": 2025,
        "paper_count": 1, "paper_shard_path": SHARD,
        "paper_shard_checksum": shard_hash, "paper_checksum": "upstream-not-file-hash",
    })
    snapshot_hash = write_json(root, SNAPSHOT, {
        "snapshot_id": "snapshot_test", "paper_count": 1,
        "releases": [{"release_id": "release_test", "conference": "TEST", "year": 2025,
                      "manifest_path": RELEASE, "manifest_checksum": release_hash}],
    })
    write_json(root, REGISTRY, {
        "current_snapshot_id": "snapshot_test",
        "snapshots": [{"snapshot_id": "snapshot_test", "manifest_path": SNAPSHOT,
                       "manifest_checksum": snapshot_hash}],
        "releases": [{"this_top_level_list_must_not_be_used": True}],
    })
    return root
