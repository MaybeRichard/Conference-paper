from copy import deepcopy
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from research_agent.api import ResearchAgent
from research_agent.core.errors import PathViolation
from tests.agent.retrieval_factory import make_retrieval_corpus


def make_result(tmp_path):
    repo = make_retrieval_corpus(tmp_path / "repo")
    agent = ResearchAgent(repo)
    agent.build_index()
    return repo, agent.propose_ideas("diffusion retinal synthesis")


def test_report_exports_readable_proposals_and_only_allowed_content(tmp_path):
    from research_agent.ideation.proposal_report import write_proposal_report
    repo, result = make_result(tmp_path)
    result["private_workspace"] = "secret-must-not-be-exported"
    result["evidence_cards"][0]["abstract"] = "entire-abstract-must-not-be-exported"
    result["proposals"][0]["title"] = "![load](https://example.org/a) <script>x</script>"
    paths = write_proposal_report(repo, result)
    text = Path(paths["report_path"]).read_text()
    dashboard = Path(paths["dashboard_path"])
    assert dashboard.is_file()
    dashboard_text = dashboard.read_text()
    assert "IDEA ATLAS" in dashboard_text and "证据账本" in dashboard_text
    assert dashboard_text.count("<script>") == 1
    assert "\\u003cscript\\u003e" in dashboard_text
    assert "record SHA256" not in dashboard_text
    assert "record_key" not in dashboard_text
    assert "<script>" not in text and "![load]" not in text
    assert "实验" in text and "假设" in text
    with ZipFile(paths["bundle_path"]) as z:
        assert set(z.namelist()) == {"proposals.json", "report.md"}
        assert z.testzip() is None
        for name in z.namelist():
            assert b"secret-must-not" not in z.read(name)
            assert b"entire-abstract" not in z.read(name)
        exported = json.loads(z.read("proposals.json"))
        assert exported["proposals"][0]["evidence_ids"]
    before = Path(paths["report_path"]).read_bytes()
    assert write_proposal_report(repo, result)["report_path"] != paths["report_path"]
    assert Path(paths["report_path"]).read_bytes() == before


def test_missing_evidence_reference_is_rejected_before_report_write(tmp_path):
    from research_agent.ideation.proposal_report import write_proposal_report
    repo, result = make_result(tmp_path)
    result["proposals"][0]["evidence_ids"] = ["nonexistent"]
    with pytest.raises(ValueError):
        write_proposal_report(repo, result)
    assert not (repo / "indexes/reports").exists()


def test_proposal_report_rejects_symlink_destination(tmp_path):
    from research_agent.ideation.proposal_report import write_proposal_report
    repo, result = make_result(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "indexes/reports").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathViolation):
        write_proposal_report(repo, result)
    assert not list(outside.iterdir())
