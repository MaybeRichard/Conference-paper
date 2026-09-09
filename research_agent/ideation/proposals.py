"""Evidence-bound, deterministic research opportunity scaffolds.

The rules here are deliberately modest: they turn verified metadata and short
abstract excerpts into hypotheses and experiments. They do not decide novelty,
eligibility, or whether an author's claim is true.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re
from typing import Any

from research_agent.core.serialization import digest
from research_agent.retrieval.index import LexicalIndex
from research_agent.retrieval.records import clean_text, review_hints


def _themes(title: str, abstract: str) -> list[str]:
    text = (title + " " + abstract).casefold()
    if not re.search(r"diffusion|ddpm|flow.matching", text):
        return []
    # Physical MRI diffusion and explicitly volumetric work are background,
    # not sufficient anchors for an independent 2D generation proposal.
    if re.search(r"diffusion.weighted|diffusion.tensor|volumetric|\b3[ -]?d\b|adjacent.slices", text):
        return []
    patterns = {
        "retinal": r"retin|\boct\b|fundus",
        "staining": r"stain|histopath|histolog",
        "segmentation": r"segmentat",
        "efficiency": r"distill|few.step|fast.sampl|flow.matching",
    }
    return [name for name, pattern in patterns.items() if re.search(pattern, text)]


def _blocked(core: dict, reason: str) -> dict:
    source = core.get("source_search") if isinstance(core.get("source_search"), dict) else {}
    return {
        "schema_version": "idea-proposal-set-v1", "status": "blocked", "reason": reason,
        "generation_method": "offline_rules_v1", "source_core": {"artifact_sha256": core.get("artifact_sha256")},
        "source_search": deepcopy(source), "evidence_cards": [], "proposals": [],
        "limitations": ["Insufficient verified evidence; no research proposal was generated."],
    }


def _validate_core(core: object) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(core, dict) or core.get("schema_version") != "core-paper-set-v1" or core.get("status") != "completed":
        raise ValueError("proposal generation requires a completed core paper set")
    papers = core.get("core_papers")
    if not isinstance(papers, list):
        raise ValueError("core_papers must be a list")
    if not papers:
        return core, papers
    supplied_checksum = core.get("artifact_sha256")
    if not isinstance(supplied_checksum, str) or supplied_checksum != digest(
        {key: value for key, value in core.items() if key != "artifact_sha256"}
    ):
        raise ValueError("core artifact checksum is invalid")
    for paper in papers:
        if not isinstance(paper, dict) or not clean_text(paper.get("record_key")):
            raise ValueError("core paper candidate is malformed")
    return core, papers


def _evidence(repo_root: Path, source: dict[str, Any], papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    index_id = source.get("index_id")
    snapshot_id = source.get("snapshot_id")
    snapshot_checksum = source.get("snapshot_checksum")
    if not all(isinstance(value, str) and value for value in (index_id, snapshot_id, snapshot_checksum)):
        raise ValueError("provenance is incomplete")
    index = LexicalIndex(repo_root)
    manifest = index.verify(index_id, verify_source=True)
    if manifest.get("snapshot_id") != snapshot_id or manifest.get("snapshot_checksum") != snapshot_checksum:
        raise ValueError("provenance snapshot does not match index")
    cards: list[dict[str, Any]] = []
    with index.connect(index_id) as db:
        for paper in papers:
            key = clean_text(paper.get("record_key"))
            row = db.execute("SELECT * FROM documents WHERE record_key=?", [key]).fetchone()
            if row is None:
                raise ValueError("provenance record_key is not present in the verified index")
            provenance = paper.get("provenance")
            if not isinstance(provenance, dict):
                raise ValueError("provenance is missing")
            for field in ("shard_path", "shard_sha256", "record_number", "record_sha256"):
                if provenance.get(field) != row[field]:
                    raise ValueError("provenance does not match verified index record")
            if provenance.get("snapshot_id") != snapshot_id or provenance.get("snapshot_checksum") != snapshot_checksum:
                raise ValueError("provenance snapshot is inconsistent")
            if paper.get("paper_id") != row["paper_id"] or paper.get("title") != row["title"]:
                raise ValueError("candidate identity does not match verified index record")
            abstract = clean_text(row["abstract"])
            cards.append({
                "evidence_id": "evidence_" + digest({"index_id": index_id, "record_key": key})[:16],
                "record_key": key, "paper_id": row["paper_id"], "title": row["title"],
                "conference": row["conference"], "year": row["year"],
                "abstract_status": row["abstract_status"],
                "abstract_excerpt": abstract[:320],
                "provenance": {field: row[field] for field in ("shard_path", "shard_sha256", "record_number", "record_sha256")},
                "source": {"snapshot_id": snapshot_id, "snapshot_checksum": snapshot_checksum, "index_id": index_id},
                "signals": review_hints(row["title"], abstract)["signals"],
                "lexical_themes": _themes(row["title"], abstract),
                "support_relation": "context_only",
            })
    return cards


def _template(theme: str) -> dict[str, Any]:
    if theme == "segmentation":
        return {
            "title": "用条件一致性约束提升医学合成数据的下游分割效用",
            "research_question": "条件扩散生成的约束是否能在患者级划分下提升下游分割，而不牺牲图像保真度？",
            "mechanism": "将分割条件作为合成数据生成的显式控制变量，联合使用冻结分割器的一致性损失；这是从分割扩散工作的待验证迁移。",
            "data_requirements": "具有患者标识和像素级病灶掩码的二维图像；训练生成器和下游分割器使用互不泄漏的划分。",
            "primary_measurement": "患者级划分上的 Dice/IoU 与生成质量指标的联合报告。",
            "ablations": ["移除条件一致性约束", "只保留质量约束", "改变约束权重"],
        }
    if theme == "retinal":
        return {
            "title": "解耦视网膜生成中的病灶条件与设备风格",
            "research_question": "在固定病灶条件时分离设备风格，能否改善跨设备的合成数据效用？",
            "mechanism": "将病灶条件与设备域条件编码为独立控制通道；固定病灶表示、交换设备风格，并约束独立病灶读出器的预测一致性。",
            "data_requirements": "带患者、设备域和病灶标签的二维 OCT 或眼底图像；固定一种模态，预留未见设备作为测试域。",
            "primary_measurement": "未见设备上真实测试集的病灶识别 AUROC/敏感度、条件保持率，以及设备可预测性；按患者 bootstrap 置信区间。",
            "ablations": ["单一联合条件编码器", "移除病灶一致性损失", "不交换设备条件", "同规模真实数据/普通增强对照"],
        }
    if theme == "efficiency":
        return {
            "title": "用条件一致性约束降低医学扩散生成的采样成本",
            "research_question": "在固定质量预算下，条件一致性约束能否减少采样步数而保持下游效用？",
            "mechanism": "将条件一致性检查与少步采样策略结合，并单独报告速度与质量的权衡。",
            "data_requirements": "同一医学模态和固定测试集；锁定分辨率、批大小和硬件，在独立验证集选择步数。",
            "primary_measurement": "固定硬件和质量阈值下的采样时间、质量与下游效用。",
            "ablations": ["移除一致性检查", "改变采样步数", "未压缩条件扩散基线"],
        }
    if theme == "staining":
        return {
            "title": "将形态保持与染色风格控制分开的虚拟染色扩散",
            "research_question": "分离形态约束与染色风格条件，能否减少跨中心虚拟染色时的结构漂移？",
            "mechanism": "以源图的细胞核/组织结构为内容条件，以中心风格作为独立条件；在染色转换中约束核边界和细胞计数的一致性。",
            "data_requirements": "有中心和患者标识的二维病理图像；配对数据评估结构保持，非配对数据仅评价有依据的指标；按患者与中心隔离。",
            "primary_measurement": "配对区域核边界 F1、细胞计数误差、跨中心下游分类效用；同时报告配准误差和失败样例。",
            "ablations": ["移除形态保持损失", "不分离中心风格条件", "固定配准/不使用配准", "普通图像转换与未约束扩散基线"],
        }
    raise ValueError("Unsupported proposal theme")


def build_proposals(repo_root: Path, core_set: dict) -> dict:
    core, papers = _validate_core(core_set)
    if not papers:
        return _blocked(core, "insufficient_evidence")
    source = core.get("source_search")
    if not isinstance(source, dict):
        raise ValueError("provenance is incomplete")
    cards = _evidence(Path(repo_root), source, papers)
    if not cards:
        return _blocked(core, "insufficient_evidence")
    themes = [theme for theme in ("retinal", "staining", "segmentation", "efficiency")
              if any(theme in card["lexical_themes"] for card in cards)]
    if not themes:
        return _blocked(core, "unsupported_evidence_context")
    proposals = []
    for theme in themes[:3]:
        anchors = [card for card in cards if theme in card["lexical_themes"]]
        template = _template(theme)
        proposals.append({
            "id": "proposal_" + theme,
            "theme": theme,
            "title": template["title"],
            "epistemic_status": "HYPOTHESIS",
            "evidence_ids": [card["evidence_id"] for card in anchors],
            "evidence_relation": "context_only",
            "research_question": template["research_question"],
            "mechanism": template["mechanism"],
            "predictions": ["在预注册划分和固定计算预算下，主指标应优于未约束基线。", "收益应在真实留出患者/设备或中心的测试集上保持。"],
            "competing_explanations": ["收益可能来自额外计算、标注或预处理，而非提出的机制。", "生成器或评估器可能存在训练数据泄漏。"],
            "experiment_blueprint": {
                "baseline": "同数据、同患者级划分、同计算预算的强条件扩散模型；同时设置更简单的普通数据增强/转换基线。",
                "data_requirements": template["data_requirements"],
                "primary_measurement": template["primary_measurement"],
                "ablations": template["ablations"],
                "failure_criteria": ["预注册主指标没有达到事先定义的最小有用改善", "收益仅在随机图像级划分出现", "简单基线以更低成本达到相同效果"],
            },
            "risks": ["证据卡只提供问题背景，不支持所提机制已经有效。", "缺摘要或缺全文会影响任务和维度判断。", "数据许可、患者泄漏和指标适用性尚未审核。"],
            "verification_steps": ["核对引用论文的任务、方法、局限和实验原文", "检索最接近工作并逐项比较机制；不能用本次未检索到证明新颖", "确认数据和计算预算，预注册划分、指标及失败标准", "先跑强简单基线，再决定是否投入完整方法"],
        })
    base = {
        "schema_version": "idea-proposal-set-v1", "status": "completed", "generation_method": "offline_rules_v1",
        "source_core": {"schema_version": core["schema_version"], "artifact_sha256": core.get("artifact_sha256")},
        "source_search": deepcopy(source), "evidence_cards": cards, "proposals": proposals,
        "limitations": ["这是基于词法线索和短摘要摘录的假设草案，不是语义筛选结论。", "没有进行新颖性（novelty）、优先权、完整性或科学有效性判断。", "HYPOTHESIS 必须通过全文证据、反事实基线和预注册实验核验。"],
    }
    return {**base, "artifact_sha256": digest(base)}
