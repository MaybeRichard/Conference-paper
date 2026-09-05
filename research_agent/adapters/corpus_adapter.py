"""Verify and stream pinned corpus snapshots without rewriting source data.

Checks byte integrity and schema relationships, not scientific accuracy or
publisher authenticity. Only referenced snapshot/release/shard files are
verified; the root DATASET_MANIFEST and raw source archive need the existing
Node integrity test. No registry-level release list is used as snapshot content.
"""
from collections.abc import Iterator
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

from research_agent.core.errors import IntegrityError, PathViolation
from research_agent.core.paths import safe_child


@dataclass(frozen=True)
class CorpusVerification:
    snapshot_id: str
    snapshot_checksum: str
    paper_count: int
    release_count: int
    verified_files: int  # Files with expected hashes; excludes the registry.


@dataclass(frozen=True)
class LocatedRecord:
    """Unmodified record plus a locator in a hash-verified source shard.

    record_number is 1-based among nonempty JSONL records, NOT physical lines.
    """
    record: dict
    shard_path: str
    shard_sha256: str
    record_number: int


@dataclass(frozen=True)
class _Shard:
    relative: str
    checksum: str
    paper_count: int


@dataclass(frozen=True)
class _Snapshot:
    snapshot_id: str
    checksum: str
    paper_count: int
    shards: tuple[_Shard, ...]


def _object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("Non-finite JSON number")


def _finite_float(value: str) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite JSON number")
    return result


def _mapping(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                           parse_constant=_constant, parse_float=_finite_float)
    except (ValueError, UnicodeError, RecursionError):
        raise IntegrityError("Invalid UTF-8 JSON object; source content omitted") from None
    if not isinstance(value, dict):
        raise IntegrityError("Expected a JSON object")
    return value


def _text(value: dict, key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise IntegrityError(f"Missing or invalid {key}")
    return result


def _number(value: dict, key: str) -> int:
    result = value.get(key)
    if type(result) is not int or result < 0:
        raise IntegrityError(f"Missing or invalid {key}")
    return result


def _entries(value: dict, key: str) -> list[dict]:
    result = value.get(key)
    if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
        raise IntegrityError(f"Missing or invalid {key}")
    return result


def _checksum(value: dict, key: str) -> str:
    result = _text(value, key)
    if re.fullmatch(r"[0-9a-f]{64}", result) is None:
        raise IntegrityError(f"Invalid {key}")
    return result


class CorpusAdapter:
    """Read-only adapter. Its input must be a trusted, immutable local checkout.

    The path checks reject static links/traversal, not hostile concurrent file
    replacement. Iteration preflights the entire snapshot, then rechecks each
    shard while streaming. Consumers should publish only after exhausting the
    iterator; there is no OS-level snapshot isolation during concurrent writes.
    """

    def __init__(self, repo_root: Path) -> None:
        self._corpus_root = safe_child(Path(repo_root), "corpus")

    def _path(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative.startswith("corpus/"):
            raise PathViolation("Corpus references must stay under corpus/")
        return safe_child(self._corpus_root, relative[len("corpus/"):])

    def _read_mapping(self, relative: str, expected: str | None = None) -> tuple[dict, str]:
        path = self._path(relative)
        try:
            if not path.is_file():
                raise IntegrityError("Required corpus file is missing or not a regular file")
            raw = path.read_bytes()
        except OSError:
            raise IntegrityError("Cannot read a required corpus file") from None
        checksum = hashlib.sha256(raw).hexdigest()
        if expected is not None and checksum != expected:
            raise IntegrityError("Referenced manifest checksum mismatch")
        return _mapping(raw), checksum

    def _load_snapshot(self, snapshot_id: str | None) -> _Snapshot:
        registry, _ = self._read_mapping("corpus/registry.json")
        selected = _text(registry, "current_snapshot_id") if snapshot_id is None else snapshot_id
        if not isinstance(selected, str) or not selected:
            raise IntegrityError("Unknown or invalid snapshot ID")
        snapshot_entries = _entries(registry, "snapshots")
        ids = [_text(entry, "snapshot_id") for entry in snapshot_entries]
        if len(set(ids)) != len(ids):
            raise IntegrityError("Duplicate snapshot reference")
        matches = [entry for entry in snapshot_entries if entry["snapshot_id"] == selected]
        if len(matches) != 1:
            raise IntegrityError("Unknown snapshot ID")
        entry = matches[0]
        snapshot, checksum = self._read_mapping(
            _text(entry, "manifest_path"), _checksum(entry, "manifest_checksum"),
        )
        if _text(snapshot, "snapshot_id") != selected:
            raise IntegrityError("Snapshot identity mismatch")
        paper_count = _number(snapshot, "paper_count")
        shards = []
        release_ids: set[str] = set()
        manifest_paths: set[str] = set()
        shard_paths: set[str] = set()
        for ref in _entries(snapshot, "releases"):
            release_id = _text(ref, "release_id")
            manifest_path = _text(ref, "manifest_path")
            if release_id in release_ids or manifest_path in manifest_paths:
                raise IntegrityError("Duplicate release reference")
            release_ids.add(release_id)
            manifest_paths.add(manifest_path)
            release, _ = self._read_mapping(manifest_path, _checksum(ref, "manifest_checksum"))
            if (_text(release, "release_id") != release_id
                    or _text(release, "conference") != _text(ref, "conference")
                    or _number(release, "year") != _number(ref, "year")):
                raise IntegrityError("Release identity, conference or year mismatch")
            relative = _text(release, "paper_shard_path")
            self._path(relative)  # Validate before any source file is opened.
            if relative in shard_paths:
                raise IntegrityError("Multiple releases reference the same shard")
            shard_paths.add(relative)
            shards.append(_Shard(relative, _checksum(release, "paper_shard_checksum"),
                                 _number(release, "paper_count")))
        return _Snapshot(selected, checksum, paper_count, tuple(shards))

    def _scan_shard(self, shard: _Shard) -> Iterator[dict]:
        path = self._path(shard.relative)
        digest = hashlib.sha256()
        count = 0
        try:
            if not path.is_file():
                raise IntegrityError("Required shard is missing or not a regular file")
            with path.open("rb") as stream:
                # Binary iteration splits only on LF, never U+2028 or U+0085.
                for line_number, line in enumerate(stream, 1):
                    digest.update(line)
                    if not line.strip():
                        continue
                    try:
                        record = _mapping(line)
                    except IntegrityError:
                        raise IntegrityError(f"Invalid JSONL object at line {line_number}") from None
                    count += 1
                    yield record
        except OSError:
            raise IntegrityError("Cannot read a required shard") from None
        if digest.hexdigest() != shard.checksum:
            raise IntegrityError("Paper shard checksum mismatch")
        if count != shard.paper_count:
            raise IntegrityError("Paper shard record count mismatch")

    def _verify(self, snapshot: _Snapshot) -> CorpusVerification:
        count = 0
        for shard in snapshot.shards:
            for _ in self._scan_shard(shard):
                count += 1
        if count != snapshot.paper_count:
            raise IntegrityError("Snapshot total record count mismatch")
        return CorpusVerification(snapshot.snapshot_id, snapshot.checksum, count,
                                  len(snapshot.shards), 1 + 2 * len(snapshot.shards))

    def verify(self, snapshot_id: str | None = None) -> CorpusVerification:
        """Verify the selected manifest chain, raw byte hashes and record counts."""
        return self._verify(self._load_snapshot(snapshot_id))

    def iter_records(self, snapshot_id: str) -> Iterator[dict]:
        """Preflight the pinned snapshot and stream unchanged upstream objects.

        A consumer abandoning the iterator early forgoes the final streaming
        recheck. Do not interpret partial iteration as a new verification report.
        """
        snapshot = self._load_snapshot(snapshot_id)
        self._verify(snapshot)
        for shard in snapshot.shards:
            yield from self._scan_shard(shard)

    def iter_located_records(self, snapshot_id: str) -> Iterator[LocatedRecord]:
        """Stream verified records with provenance; publish only after exhaustion."""
        snapshot = self._load_snapshot(snapshot_id)
        self._verify(snapshot)
        for shard in snapshot.shards:
            for number, record in enumerate(self._scan_shard(shard), 1):
                yield LocatedRecord(record, shard.relative, shard.checksum, number)
