"""Auditable JSON/Markdown export for standalone idea drafts."""
from __future__ import annotations

from datetime import datetime, timezone
import html
import json
from pathlib import Path
import re
from tempfile import mkdtemp
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from research_agent.core.paths import safe_child
from research_agent.core.serialization import canonical_bytes
from research_agent.retrieval.index import _fsync_directory, _write


def _text(value: object) -> str:
    value = html.escape(str(value), quote=True)
    return re.sub(r"([\\`*_{}\[\]()#!|])", r"\\\1", value)


def markdown(result: dict) -> str:
    lines = [
        "# 研究 Idea 草案",
        "",
        "**这是待验证的 HYPOTHESIS 草案，不是已验证结论、G2 选择或新颖性判断。**",
        "",
        f"主题：{_text(result['topic'])}",
        f"领域：`{_text(result['domain'])}`",
        f"快照：`{_text(result['source_search']['snapshot_id'])}`",
        "",
        "## 草案",
        "",
        f"问题：{_text(result['problem_statement'])}",
        f"待核验缺口：{_text(result['residual_gap'])}",
        f"候选机制：{_text(result['proposed_mechanism'])}",
        f"假设：{_text(result['hypothesis'])}",
        "",
        "## 预测与证伪",
        "",
    ]
    lines.extend(f"- {_text(item)}" for item in result["predictions"])
    lines.append("")
    lines.extend(f"- {_text(item)}" for item in result["falsification_tests"])
    lines += ["", "## 检索依据", ""]
    for item in result["candidates"]:
        lines += [
            f"- **{_text(item['title'])}** ({_text(item['conference'])}, {item['year']}) — "
            f"语料 ID `{_text(item['paper_id'])}`，范围 `{_text(item['scope_status'])}`。"
        ]
    lines += ["", "## 边界", ""]
    lines.extend(f"- {_text(item)}" for item in result["boundaries"])
    return "\n".join(lines) + "\n"


def write_idea_report(repo_root: Path, result: dict) -> dict:
    if result.get("status") != "completed" or result.get("mode") != "standalone_idea_draft":
        raise ValueError("Only completed idea drafts can be exported")
    reports = safe_child(Path(repo_root), "indexes/reports")
    reports.mkdir(parents=True, exist_ok=True)
    staging = Path(mkdtemp(prefix=".idea-writing-", dir=reports))
    destination = safe_child(reports, "idea_" + uuid4().hex)
    try:
        _write(staging / "idea_draft.json", result)
        with (staging / "idea_draft.md").open("x", encoding="utf-8") as stream:
            stream.write(markdown(result))
            stream.flush()
        with ZipFile(staging / "return_bundle.zip", "x", ZIP_DEFLATED) as archive:
            archive.write(staging / "idea_draft.json", "idea_draft.json")
            archive.write(staging / "idea_draft.md", "idea_draft.md")
        _fsync_directory(staging)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging.rename(destination)
        _fsync_directory(reports)
        return {
            "run_id": destination.name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "json_path": str(destination / "idea_draft.json"),
            "markdown_path": str(destination / "idea_draft.md"),
            "bundle_path": str(destination / "return_bundle.zip"),
        }
    finally:
        if staging.exists():
            import shutil
            shutil.rmtree(staging)
