"""Real-corpus M2A smoke test; writes derived reports, never source records."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import sys
from time import monotonic

from research_agent.api import ResearchAgent


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args=p.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    api=ResearchAgent(args.repo)
    source=api.verify_corpus()
    started=monotonic()
    built=api.build_index()
    elapsed=monotonic()-started
    assert built["document_count"]==source.paper_count
    assert built["snapshot_checksum"]==source.snapshot_checksum
    assert sum(x["records"] for x in built["coverage_by_venue_year"])==source.paper_count
    result=api.search_papers("二维医学图像扩散生成",limit=50,report=True)
    assert result["workflow_advanced"] is False
    assert result["coverage"]["exhaustive"] is False
    assert len(result["candidates"])<=50
    assert all(x["scope_status"]=="unreviewed" for x in result["candidates"])
    calibration={}
    if source.snapshot_id=="snapshot_a6ef56370e3258f5":
        assert source.paper_count==113989
        assert built["missing_abstract_count"]==2276
        for token in ("RetiDiff", "DiDGen", "DiffStain"):
            hits=[r for r in result["candidates"] if token.casefold() in r["title"].casefold()]
            assert hits, token+" missing from broad candidate set"
            assert hits[0]["abstract_status"]!="present"
            calibration[token]={"rank":hits[0]["rank"], "paper_id":hits[0]["paper_id"],
                                "source_paper_id":hits[0]["source_paper_id"], "status":"retrieved_unreviewed"}
    assert api.verify_corpus()==source
    summary={"platform":platform.platform(), "python":sys.version.split()[0], "sqlite":sqlite3.sqlite_version,
             "corpus":asdict(source),"index_id":built["index_id"], "database_sha256":built["database_sha256"],
             "indexed_records":built["document_count"],"missing_abstracts":built["missing_abstract_count"],
             "build_seconds":round(elapsed,3), "coverage":result["coverage"], "calibration":calibration,
             "assertions":"passed", "not_evaluated":["semantic precision","recall@K","2D eligibility","novelty"]}
    (args.out/"smoke-summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    (args.out/"index-manifest.json").write_text(json.dumps(built,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    shutil.copyfile(result["report"]["bundle_path"],args.out/"return_bundle.zip")
    print(json.dumps(summary,ensure_ascii=False,sort_keys=True))


if __name__=="__main__": main()
