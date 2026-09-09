"""Allowlisted, atomic exports of proposal drafts; no raw abstracts or workspace dump."""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import shutil
from tempfile import mkdtemp
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from research_agent.core.paths import safe_child
from research_agent.retrieval.index import _write, _fsync_directory
from research_agent.retrieval.report import _text


def _only(value, fields):
    if not isinstance(value, dict):
        raise ValueError("Expected report object")
    return {key: deepcopy(value[key]) for key in fields if key in value}


def export_payload(result: dict) -> dict:
    if result.get("schema_version") == "research-package-v1":
        result = result.get("proposal_set", {})
    if result.get("schema_version") != "idea-proposal-set-v1" or result.get("status") != "completed":
        raise ValueError("A completed proposal set is required")
    out = _only(result, ("schema_version", "status", "generation_method", "limitations"))
    out["source_search"] = _only(result["source_search"], ("index_id", "snapshot_id", "snapshot_checksum"))
    out["evidence_cards"] = []
    for item in result["evidence_cards"]:
        card = _only(item, ("evidence_id", "record_key", "paper_id", "title", "conference", "year", "abstract_status", "abstract_excerpt", "support_relation", "lexical_themes"))
        card["abstract_excerpt"] = card.get("abstract_excerpt", "")[:320]
        card["provenance"] = _only(item["provenance"], ("shard_path", "shard_sha256", "record_number", "record_sha256"))
        out["evidence_cards"].append(card)
    evidence_ids = {c["evidence_id"] for c in out["evidence_cards"]}
    out["proposals"] = []
    for item in result["proposals"]:
        if item.get("epistemic_status") != "HYPOTHESIS" or not item.get("evidence_ids") or not set(item["evidence_ids"]) <= evidence_ids:
            raise ValueError("Proposal hypothesis or evidence references are invalid")
        proposal = _only(item, ("id", "theme", "title", "epistemic_status", "evidence_ids", "evidence_relation", "research_question", "mechanism", "predictions", "competing_explanations", "risks", "verification_steps"))
        proposal["experiment_blueprint"] = _only(item["experiment_blueprint"], ("baseline", "data_requirements", "primary_measurement", "ablations", "failure_criteria"))
        out["proposals"].append(proposal)
    if not out["proposals"]:
        raise ValueError("No proposals to export")
    return out


def markdown(result: dict) -> str:
    result = export_payload(result)
    lines = ["# 研究方向与实验方案草案", "", "以下为离线规则生成的研究假设；引用论文提供背景，尚未证明所提机制有效。", "",
             f"快照：{_text(result['source_search']['snapshot_id'])}", ""]
    labels = (("research_question", "研究问题"), ("mechanism", "机制假设"), ("predictions", "可检验预测"),
              ("competing_explanations", "竞争性解释"), ("risks", "风险"), ("verification_steps", "验证顺序"))
    def field(label, value):
        lines.extend([f"### {label}", ""])
        if isinstance(value, list):
            lines.extend("- " + _text(x) for x in value)
        else:
            lines.append(_text(value))
        lines.append("")
    for i, proposal in enumerate(result["proposals"], 1):
        lines.extend([f"## {i}. {_text(proposal['title'])}", "", "状态：HYPOTHESIS / 待验证", "",
                      "背景证据：" + ", ".join(_text(x) for x in proposal["evidence_ids"]), ""])
        for name, label in labels[:4]:
            field(label, proposal[name])
        for name, label in (("baseline", "实验：基线"), ("data_requirements", "实验：数据要求"), ("primary_measurement", "实验：主指标"), ("ablations", "实验：消融"), ("failure_criteria", "实验：证伪条件")):
            field(label, proposal["experiment_blueprint"][name])
        for name, label in labels[4:]:
            field(label, proposal[name])
    lines.extend(["## 证据卡", ""])
    for card in result["evidence_cards"]:
        p = card["provenance"]
        lines.extend([f"### {_text(card['evidence_id'])} · {_text(card['title'])}", "",
                      f"{_text(card['conference'])} / {card['year']} · 摘要：{_text(card['abstract_status'])}", "",
                      _text(card["abstract_excerpt"]) or "摘要缺失；当前只核对了标题和来源定位。", "",
                      f"来源：{_text(p['shard_path'])}，非空记录 {p['record_number']}；记录 SHA256：{_text(p['record_sha256'])}", ""])
    field("目前证据边界", result["limitations"])
    return "\n".join(lines)


def write_proposal_report(repo_root: Path, result: dict) -> dict:
    payload = export_payload(result)
    reports = safe_child(Path(repo_root), "indexes/reports")
    reports.mkdir(parents=True, exist_ok=True)
    staging = Path(mkdtemp(prefix=".proposal-writing-", dir=reports))
    run_id = "proposal_" + uuid4().hex
    destination = safe_child(reports, run_id)
    try:
        _write(staging / "proposals.json", payload)
        with (staging / "report.md").open("x", encoding="utf-8") as f:
            f.write(markdown(payload)); f.flush(); os.fsync(f.fileno())
        with ZipFile(staging / "return_bundle.zip", "x", ZIP_DEFLATED) as z:
            for name in ("proposals.json", "report.md"):
                z.write(staging / name, name)
        with (staging / "return_bundle.zip").open("rb") as f:
            os.fsync(f.fileno())
        _fsync_directory(staging)
        safe_child(Path(repo_root), "indexes/reports")
        os.rename(staging, destination)
        _fsync_directory(reports)
        return {"run_id": run_id, "json_path": str(destination / "proposals.json"), "report_path": str(destination / "report.md"), "bundle_path": str(destination / "return_bundle.zip")}
    finally:
        if staging.exists():
            shutil.rmtree(staging)
