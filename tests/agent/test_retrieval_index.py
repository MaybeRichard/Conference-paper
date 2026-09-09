from pathlib import Path
import hashlib
import json
import sqlite3

import pytest

from research_agent.adapters.corpus_adapter import CorpusAdapter
from research_agent.core.errors import IntegrityError, PathViolation, UnsupportedStage
from research_agent.retrieval.index import LexicalIndex
from tests.agent.retrieval_factory import make_retrieval_corpus
from tests.agent.corpus_factory import SHARD


def corpus_bytes(repo):
    return {str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (repo / "corpus").rglob("*") if p.is_file()}


def test_build_counts_coverage_provenance_and_readonly_source(tmp_path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    before = corpus_bytes(repo)
    index = LexicalIndex(repo)
    built = index.build()
    assert built["document_count"] == 7
    assert built["missing_abstract_count"] == 2
    assert built["snapshot_id"] == "snapshot_test"
    assert built["engine"] == "sqlite_fts5"
    assert sum(r["records"] for r in built["coverage_by_venue_year"]) == 7
    assert index.verify(built["index_id"])["valid"] is True
    assert corpus_bytes(repo) == before
    with index.connect(built["index_id"]) as db:
        row = db.execute("SELECT paper_id,shard_path,record_number,abstract_status FROM documents WHERE paper_id='reti'").fetchone()
        assert tuple(row) == ("reti", SHARD, 1, "missing")
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM documents")


def test_located_records_preserve_upstream_objects_and_exact_shard(tmp_path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    adapter = CorpusAdapter(repo)
    plain = list(adapter.iter_records("snapshot_test"))
    located = list(adapter.iter_located_records("snapshot_test"))
    assert [x.record for x in located] == plain
    assert [x.record_number for x in located] == list(range(1, 8))
    assert all(x.shard_path == SHARD for x in located)
    assert all(x.shard_sha256 == hashlib.sha256((repo/SHARD).read_bytes()).hexdigest() for x in located)


def test_rebuild_reuses_verified_immutable_index(tmp_path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    index = LexicalIndex(repo)
    first = index.build()
    dbfile = index.directory(first["index_id"]) / "catalog.sqlite"
    before = dbfile.read_bytes()
    second = index.build()
    assert first["index_id"] == second["index_id"]
    assert second["reused"] is True
    assert dbfile.read_bytes() == before


def test_corrupt_db_not_silently_rebuilt(tmp_path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    index = LexicalIndex(repo)
    result = index.build()
    (index.directory(result["index_id"]) / "catalog.sqlite").write_bytes(b"broken")
    with pytest.raises(IntegrityError): index.verify(result["index_id"])
    with pytest.raises(IntegrityError): index.build()


def test_bad_source_creates_no_published_index(tmp_path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    (repo / SHARD).write_bytes(b"modified source\n")
    with pytest.raises(IntegrityError): LexicalIndex(repo).build()
    assert not list((repo / "indexes").glob("lexical_*"))


def test_stream_failure_does_not_publish_partial_db(tmp_path, monkeypatch):
    repo = make_retrieval_corpus(tmp_path / "repo")
    original = CorpusAdapter.iter_located_records
    def broken(self, snapshot_id):
        source = original(self, snapshot_id)
        try:
            yield next(source)
            raise IntegrityError("injected incomplete stream")
        finally: source.close()
    monkeypatch.setattr(CorpusAdapter, "iter_located_records", broken)
    with pytest.raises(IntegrityError): LexicalIndex(repo).build()
    assert not list((repo / "indexes").glob("lexical_*"))


def test_status_before_build_does_not_create_database(tmp_path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    status = LexicalIndex(repo).status()
    assert status["status"] == "not_built"
    assert not (repo / "indexes").exists()
    with pytest.raises(UnsupportedStage):
        with LexicalIndex(repo).connect(): pass


@pytest.mark.parametrize("component", ["indexes", "catalog.sqlite", "manifest.json"])
def test_symlinked_index_component_rejected(tmp_path, component):
    repo = make_retrieval_corpus(tmp_path / "repo")
    index = LexicalIndex(repo)
    result = index.build()
    target = tmp_path / "external"
    if component == "indexes":
        target.mkdir()
        import shutil
        shutil.rmtree(repo / "indexes")
        (repo / "indexes").symlink_to(target, target_is_directory=True)
    else:
        target.write_bytes(b"external remains unchanged")
        p = index.directory(result["index_id"]) / component
        p.unlink(); p.symlink_to(target)
    with pytest.raises(PathViolation): index.verify(result["index_id"])


@pytest.mark.parametrize("identifier", ["../escape", "/tmp/db", "x:y", "x\\y"])
def test_index_identifier_rejects_traversal(tmp_path, identifier):
    repo = make_retrieval_corpus(tmp_path / "repo")
    with pytest.raises((ValueError, PathViolation)): LexicalIndex(repo).directory(identifier)


def test_canonical_and_source_paper_ids_remain_distinct(tmp_path):
    from tests.agent.corpus_factory import rehash
    repo = make_retrieval_corpus(tmp_path / "repo")
    rows = [json.loads(x) for x in (repo/SHARD).read_text().splitlines()]
    rows[0]["paper_id"] = "canonical_reti"
    (repo/SHARD).write_text("".join(json.dumps(r) + "\n" for r in rows))
    rehash(repo)
    index = LexicalIndex(repo); result=index.build()
    with index.connect(result["index_id"]) as db:
        row = db.execute("SELECT paper_id,source_paper_id FROM documents WHERE paper_id='canonical_reti'").fetchone()
        assert tuple(row) == ("canonical_reti", "reti")


def test_unavailable_fts_runtime_is_a_capability_block(tmp_path, monkeypatch):
    repo=make_retrieval_corpus(tmp_path/"repo")
    index=LexicalIndex(repo);index.build()
    original=sqlite3.connect
    class MissingFTS(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            if statement == "PRAGMA quick_check":
                raise sqlite3.OperationalError("no such module: fts5")
            return super().execute(statement,*args,**kwargs)
    def connect(*args,**kwargs):
        return original(*args,**kwargs,factory=MissingFTS)
    monkeypatch.setattr(sqlite3,"connect",connect)
    with pytest.raises(UnsupportedStage) as error:
        index.verify()
    assert error.value.code == "fts5_unavailable"
