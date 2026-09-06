"""Immutable on-disk FTS5 indexes of verified source snapshots.

Static path checks assume a trusted, single-user checkout (same as M1).
Checksums detect corruption, not hostile replacement of both DB and manifest.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from tempfile import mkdtemp

from filelock import FileLock, Timeout

from research_agent.adapters.corpus_adapter import CorpusAdapter
from research_agent.core.errors import BusyError, ConflictError, IntegrityError, UnsupportedStage
from research_agent.core.paths import safe_child
from research_agent.core.serialization import canonical_bytes, digest
from research_agent.retrieval.records import NORMALIZATION_VERSION, normalize_record

PROFILE = {"schema": "lexical-index-v1", "normalization": NORMALIZATION_VERSION,
           "tokenizer": "porter unicode61", "channels": ["title", "abstract", "combined"]}
COLUMNS = ("record_key", "paper_id", "source_paper_id", "source_title", "source_variant_id", "title", "abstract", "abstract_status",
           "conference", "year", "doi", "paper_url", "pdf_url", "source", "source_id",
           "normalized_title", "shard_path", "shard_sha256", "record_number", "record_sha256")


class IndexNotBuilt(UnsupportedStage):
    error_code = "index_not_built"


class FTSUnavailable(UnsupportedStage):
    error_code = "fts5_unavailable"


def file_hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value: raise ValueError("duplicate key")
        value[key] = item
    return value


def _read_json(path: Path) -> dict:
    try:
        if not path.is_file() or path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_object)
        if not isinstance(value, dict): raise ValueError
        return value
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise IntegrityError("Invalid or missing index/source manifest") from None


def _write(path: Path, data: dict) -> None:
    with path.open("xb") as stream:
        stream.write(canonical_bytes(data)); stream.write(b"\n")
        stream.flush(); os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


class LexicalIndex:
    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).absolute()
        self.root = safe_child(self.repo_root, "indexes")

    def _identity(self, snapshot_id=None) -> tuple[str, str]:
        registry = _read_json(safe_child(self.repo_root, "corpus/registry.json"))
        selected = registry.get("current_snapshot_id") if snapshot_id is None else snapshot_id
        if not isinstance(selected, str) or re.fullmatch(r"[A-Za-z0-9_-]+", selected) is None:
            raise ValueError("Invalid snapshot identifier")
        entries = registry.get("snapshots")
        if not isinstance(entries, list): raise IntegrityError("Invalid snapshot registry")
        matches = [x for x in entries if isinstance(x, dict) and x.get("snapshot_id") == selected]
        if len(matches) != 1: raise IntegrityError("Snapshot identity is unknown or ambiguous")
        checksum = matches[0].get("manifest_checksum")
        if not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None:
            raise IntegrityError("Invalid snapshot checksum")
        return selected, checksum

    @staticmethod
    def _identifier(identity):
        return "lexical_" + digest({"snapshot_id": identity[0], "snapshot_sha256": identity[1],
                                    "profile": PROFILE})[:24]

    def directory(self, index_id=None) -> Path:
        selected = self._identifier(self._identity()) if index_id is None else index_id
        if not isinstance(selected, str) or re.fullmatch(r"lexical_[0-9a-f]{24}", selected) is None:
            raise ValueError("Invalid index identifier")
        return safe_child(safe_child(self.repo_root, "indexes"), selected)

    def _manifest(self, index_id=None) -> dict:
        directory = self.directory(index_id)
        if not directory.exists(): raise IndexNotBuilt("Lexical index is not built; run index build")
        manifest = _read_json(safe_child(directory, "manifest.json"))
        if manifest.get("profile") != PROFILE or manifest.get("index_id") != directory.name:
            raise IntegrityError("Index profile or identity mismatch")
        if directory.name != self._identifier((manifest.get("snapshot_id"), manifest.get("snapshot_checksum"))):
            raise IntegrityError("Index source identity mismatch")
        return manifest

    def _open_verified(self, index_id=None):
        manifest = self._manifest(index_id)
        dbpath = safe_child(self.directory(manifest["index_id"]), "catalog.sqlite")
        try:
            if not dbpath.is_file() or file_hash(dbpath) != manifest.get("database_sha256"):
                raise IntegrityError("Index database checksum mismatch")
            db = sqlite3.connect(dbpath.as_uri() + "?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise IntegrityError("SQLite index integrity check failed")
            if db.execute("SELECT COUNT(*) FROM documents").fetchone()[0] != manifest.get("document_count"):
                raise IntegrityError("Index document count mismatch")
            for name in PROFILE["channels"]:
                db.execute(f"SELECT rowid FROM {name}_fts LIMIT 1").fetchall()
            return db, manifest
        except sqlite3.OperationalError as error:
            if "db" in locals(): db.close()
            if "no such module: fts5" in str(error):
                raise FTSUnavailable("Python SQLite lacks FTS5; use an FTS5-enabled Python") from None
            raise IntegrityError("Invalid SQLite index; source details omitted") from None
        except BaseException:
            if "db" in locals(): db.close()
            raise

    @contextmanager
    def connect(self, index_id=None):
        db, _ = self._open_verified(index_id)
        try: yield db
        finally: db.close()

    def status(self, index_id=None) -> dict:
        directory = self.directory(index_id)
        if not directory.exists():
            return {"status": "not_built", "index_id": directory.name}
        return {"status": "ready", **self.verify(directory.name, verify_source=False)}

    def verify(self, index_id=None, verify_source=True) -> dict:
        try:
            db, manifest = self._open_verified(index_id)
            db.close()
            if verify_source:
                source = CorpusAdapter(self.repo_root).verify(manifest["snapshot_id"])
                if source.snapshot_checksum != manifest["snapshot_checksum"] or source.paper_count != manifest["document_count"]:
                    raise IntegrityError("Index no longer agrees with source snapshot")
            return {**manifest, "valid": True, "source_reverified": verify_source}
        except sqlite3.Error:
            raise IntegrityError("Invalid SQLite index; source details omitted") from None

    def build(self, snapshot_id=None) -> dict:
        source = CorpusAdapter(self.repo_root).verify(snapshot_id)
        identifier = self._identifier((source.snapshot_id, source.snapshot_checksum))
        self.root = safe_child(self.repo_root, "indexes")
        self.root.mkdir(parents=True, exist_ok=True)
        lockpath = safe_child(self.root, ".build.lock")
        try:
            with FileLock(lockpath, timeout=1):
                destination = self.directory(identifier)
                if destination.exists():
                    return {**self.verify(identifier), "reused": True}
                staging = Path(mkdtemp(prefix=".building-", dir=self.root))
                try:
                    self._populate(staging, source)
                    dbfile = safe_child(staging, "catalog.sqlite")
                    with dbfile.open("rb") as f: os.fsync(f.fileno())
                    stats = _read_json(staging / "stats.json")
                    (staging / "stats.json").unlink()
                    manifest = {"schema_version": "lexical-manifest-v1", "index_id": identifier,
                        "profile": PROFILE, "engine": "sqlite_fts5", "sqlite_version": sqlite3.sqlite_version,
                        "snapshot_id": source.snapshot_id, "snapshot_checksum": source.snapshot_checksum,
                        "release_count": source.release_count, "verified_files": source.verified_files,
                        "built_at": datetime.now(timezone.utc).isoformat(),
                        "database_sha256": file_hash(dbfile), **stats}
                    _write(staging / "manifest.json", manifest)
                    _fsync_directory(staging)
                    # Recheck destination immediately before publication. No force overwrite.
                    if self.directory(identifier).exists(): raise ConflictError("Index already published")
                    os.rename(staging, destination)
                    _fsync_directory(self.root)
                    return {**manifest, "valid": True, "source_reverified": True, "reused": False}
                finally:
                    if staging.exists(): shutil.rmtree(staging)
        except Timeout:
            raise BusyError("Another index build is active") from None
        except sqlite3.OperationalError as error:
            if "no such module: fts5" in str(error):
                raise FTSUnavailable("Python SQLite lacks FTS5; use an FTS5-enabled Python") from None
            raise IntegrityError("SQLite index build failed; source content omitted") from None
        except (sqlite3.Error, OSError):
            raise IntegrityError("Cannot build or publish lexical index") from None

    def _populate(self, staging, source):
        db = sqlite3.connect(staging / "catalog.sqlite")
        try:
            fields = ["id INTEGER PRIMARY KEY"] + [f"{name} {'INTEGER' if name in ('year', 'record_number') else 'TEXT'}" for name in COLUMNS]
            db.execute("CREATE TABLE documents (" + ",".join(fields) + ")")
            db.execute("CREATE UNIQUE INDEX record_identity ON documents(record_key)")
            db.execute("CREATE INDEX filters ON documents(conference,year)")
            db.execute("CREATE INDEX title_groups ON documents(normalized_title)")
            count = 0
            for located in CorpusAdapter(self.repo_root).iter_located_records(source.snapshot_id):
                data = normalize_record(located)
                db.execute("INSERT INTO documents (" + ",".join(COLUMNS) + ") VALUES (" + ",".join("?" for _ in COLUMNS) + ")",
                           tuple(data[k] for k in COLUMNS))
                count += 1
            if count != source.paper_count: raise IntegrityError("Indexed stream count mismatch")
            # If registry/manifests changed during construction, refuse to publish.
            if self._identity(source.snapshot_id) != (source.snapshot_id, source.snapshot_checksum):
                raise IntegrityError("Source snapshot changed during indexing")
            for channel in PROFILE["channels"]:
                cols = "title,abstract" if channel == "combined" else channel
                db.execute(f"CREATE VIRTUAL TABLE {channel}_fts USING fts5({cols},content='documents',content_rowid='id',tokenize='porter unicode61')")
                db.execute(f"INSERT INTO {channel}_fts({channel}_fts) VALUES ('rebuild')")
                db.execute(f"INSERT INTO {channel}_fts({channel}_fts,rank) VALUES ('integrity-check',1)")
            coverage = []
            for row in db.execute("SELECT conference,year,COUNT(*),SUM(abstract_status='present'),SUM(doi!=''),SUM(pdf_url!='') FROM documents GROUP BY conference,year ORDER BY conference,year"):
                coverage.append(dict(conference=row[0], year=row[1], records=row[2], with_abstract=row[3],
                                     missing_abstract=row[2]-row[3], with_doi=row[4], with_pdf_url=row[5],
                                     proceedings_completeness="not_determined"))
            missing = db.execute("SELECT COUNT(*) FROM documents WHERE abstract_status!='present'").fetchone()[0]
            db.commit()
            _write(staging / "stats.json", {"document_count": count, "missing_abstract_count": missing,
                                            "coverage_by_venue_year": coverage})
        finally: db.close()
