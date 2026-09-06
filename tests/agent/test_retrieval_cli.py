import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest

from research_agent.api import ResearchAgent
from research_agent.retrieval.index import LexicalIndex
from research_agent.retrieval.report import write_report
from research_agent.retrieval.search import search
from tests.agent.retrieval_factory import make_retrieval_corpus


def cli(repo, *args):
    p = subprocess.run([sys.executable, "-m", "research_agent", "--repo", str(repo), "--json", *args],
                       capture_output=True, text=True, timeout=20)
    assert len(p.stdout.splitlines()) == 1, (p.stdout,p.stderr)
    return p.returncode, json.loads(p.stdout)


def test_api_and_cli_build_search_report_roundtrip(tmp_path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    before = {str(p):p.read_bytes() for p in (repo/"corpus").rglob("*") if p.is_file()}
    rc, missing = cli(repo, "index", "status")
    assert rc == 0 and missing["status"] == "not_built"
    rc, built = cli(repo, "index", "build")
    assert rc == 0 and built["document_count"] == 7
    rc, result = cli(repo, "search", "--query", "二维医学图像扩散生成", "--limit", "20", "--report")
    assert rc == 0 and result["candidates"]
    assert result["workflow_advanced"] is False
    bundle = Path(result["report"]["bundle_path"])
    with ZipFile(bundle) as z:
        assert z.testzip() is None
        assert set(z.namelist()) == {"search.json","candidates.jsonl","missing_abstract_queue.jsonl","report.md"}
        assert json.loads(z.read("search.json"))["index_id"] == built["index_id"]
        assert len(z.read("candidates.jsonl").splitlines()) == len(result["candidates"])
    assert before == {str(p):p.read_bytes() for p in (repo/"corpus").rglob("*") if p.is_file()}
    assert not (repo/"workspaces").exists()
    assert ResearchAgent(repo).verify_index(built["index_id"])["valid"] is True


def test_no_index_is_typed_block_not_empty_success(tmp_path):
    repo = make_retrieval_corpus(tmp_path/"repo")
    rc,p = cli(repo,"search","--query","diffusion")
    assert rc == 5 and p["error"]["code"] == "index_not_built"


def test_corrupt_index_rejected_by_cli(tmp_path):
    repo = make_retrieval_corpus(tmp_path/"repo")
    obj=LexicalIndex(repo);built=obj.build()
    (obj.directory(built["index_id"])/"catalog.sqlite").write_bytes(b"bad bytes")
    rc,p = cli(repo,"search","--query","diffusion")
    assert rc == 4 and p["error"]["code"] == "integrity_error"


@pytest.mark.parametrize("args", [("search","--query","医学扩散火星"), ("search","--query","diffusion","--limit","0"), ("index","build","--snapshot-id","../bad")])
def test_cli_bad_arguments_safe_json(tmp_path,args):
    repo=make_retrieval_corpus(tmp_path/"repo")
    rc,p=cli(repo,*args)
    assert rc in (2,4)
    assert "error" in p
    assert "fire" not in p["error"]["message"]


def test_search_does_not_approve_gate_or_replace_s2(fixture_repo):
    api=ResearchAgent(fixture_repo)
    state=api.create_workspace("二维医学图像扩散生成","medical_diffusion_2d")
    api.build_index()
    api.search_papers("diffusion",report=True)
    assert api.get_status(state.workspace_id)==state
    assert api.advance(state.workspace_id).status=="waiting_for_user"


def test_report_escapes_markdown_html_and_unsafe_links(tmp_path):
    papers=[dict(paper_id="unsafe",title='Diffusion ![remote](https://example.org/x) <script>alert(1)</script>',
                 abstract="secret full abstract must not be exported",paper_url="javascript:alert(1)",
                 conference="MICCAI",year=2025)]
    repo=make_retrieval_corpus(tmp_path/"repo",papers);obj=LexicalIndex(repo);obj.build()
    result=search(obj,"diffusion")
    paths=write_report(repo,result)
    text=Path(paths["report_path"]).read_text()
    assert "<script>" not in text and "![remote]" not in text and "](javascript:" not in text
    with ZipFile(paths["bundle_path"]) as z:
        assert all(b"secret full abstract" not in z.read(n) for n in z.namelist())


def test_symlinked_report_root_is_rejected(tmp_path):
    from research_agent.core.errors import PathViolation
    repo=make_retrieval_corpus(tmp_path/"repo");obj=LexicalIndex(repo);obj.build()
    outside=tmp_path/"outside";outside.mkdir()
    (repo/"indexes"/"reports").symlink_to(outside,target_is_directory=True)
    with pytest.raises(PathViolation): write_report(repo,search(obj,"diffusion"))
    assert not list(outside.iterdir())


def test_reports_are_new_immutable_runs(tmp_path):
    repo=make_retrieval_corpus(tmp_path/"repo");obj=LexicalIndex(repo);obj.build()
    result=search(obj,"diffusion")
    first=write_report(repo,result)
    before=Path(first["report_path"]).read_bytes()
    second=write_report(repo,result)
    assert first["report_path"]!=second["report_path"]
    assert Path(first["report_path"]).read_bytes()==before


def test_api_report_flag_must_be_boolean(tmp_path):
    repo=make_retrieval_corpus(tmp_path/"repo")
    api=ResearchAgent(repo);api.build_index()
    with pytest.raises(ValueError): api.search_papers("diffusion",report="false")
    assert not (repo/"indexes"/"reports").exists()
