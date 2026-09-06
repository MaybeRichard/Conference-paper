"""Small auditable concept expansion, not LLM translation or eligibility screening."""
from __future__ import annotations
import re

from research_agent.retrieval.records import clean_text

GLOSSARY_VERSION = "medical-generation-query-v1"
CONCEPTS = (
    ("medical", r"\b(?:medical|biomedical|clinical)\b|医学|医疗",
     ["medical", "biomedical", "clinical", "radiology", "mri", "ct", "oct", "x ray", "xray", "ultrasound", "retinal", "retina", "fundus", "pathology", "histopathology", "dermoscopy", "dermoscopic", "endoscopy", "endoscopic", "colonoscopy", "colonoscopic", "mammography", "mammogram", "lesion", "anatomical", "staining"]),
    ("diffusion", r"\b(?:diffusion|ddpm)\b|扩散", ["diffusion", "ddpm", "score based"]),
    ("generation", r"\b(?:generation|generative|synthesis|synthetic)\b|生成|合成",
     ["generation", "generative", "generate", "generating", "synthesis", "synthetic", "synthesize", "synthesizing", "translation", "editing", "inpainting", "staining", "augmentation"]),
    ("retinal", r"眼底|视网膜", ["retinal", "retina", "fundus", "oct"]),
    ("lesion", r"病灶", ["lesion", "pathology", "abnormality"]),
    ("pathology", r"病理", ["pathology", "histopathology", "histology"]),
    ("ultrasound", r"超声", ["ultrasound", "sonography"]),
    ("dermoscopy", r"皮肤镜", ["dermoscopy", "dermoscopic"]),
    ("endoscopy", r"内镜|结肠镜", ["endoscopy", "endoscopic", "colonoscopy", "colonoscopic"]),
    ("augmentation", r"数据增强", ["augmentation", "synthetic data"]),
    ("editing", r"局部编辑|编辑", ["editing", "inpainting", "insertion"]),
    ("staining", r"虚拟染色|染色", ["staining", "virtual staining"]),
    ("translation", r"跨模态|图像转换|转换", ["translation", "modality synthesis", "cross modality"]),
    ("flow_matching", r"流匹配", ["flow matching"]),
    ("efficiency", r"高效|加速|速度", ["efficient", "efficiency", "fast", "acceleration"]),
)


def expression(groups: list[dict]) -> str:
    def quote(term): return '"' + term.replace('"', '""') + '"'
    return " AND ".join("(" + " OR ".join(quote(x) for x in g["terms"]) + ")" for g in groups)


def plan_query(text: str) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 2000 or "\x00" in text:
        raise ValueError("Query must be nonempty plain text of at most 2000 characters")
    original = text
    remaining = clean_text(text).casefold()
    groups = []
    warnings = ["Lexical retrieval only; relevance and dimensionality are unreviewed."]
    dimension = None
    for label, pattern in [("2.5d", r"\b2\.5[ -]?d\b|二点五维"), ("3d", r"\b3[ -]?d\b|三维"), ("2d", r"\b2[ -]?d\b|二维")]:
        if re.search(pattern, remaining):
            dimension = label if dimension is None else "mixed"
            remaining = re.sub(pattern, " ", remaining)
    for key, pattern, terms in CONCEPTS:
        if re.search(pattern, remaining):
            groups.append({"concept": key, "terms": terms, "origin": "curated_glossary"})
            remaining = re.sub(pattern, " ", remaining)
    remaining = re.sub(r"图像|图象|影像|模型|研究|方向|用于|基于|的|与|和", " ", remaining)
    if re.search(r"[\u3400-\u9fff]", remaining):
        raise ValueError("Unsupported Chinese modifier; use supported concepts or English terms")
    ignored = {"image", "images", "model", "models", "the", "of", "for", "and", "in", "with"} if groups else set()
    tokens = re.findall(r"[^\W_]+", remaining, flags=re.UNICODE)
    for token in dict.fromkeys(tokens):
        if token not in ignored:
            groups.append({"concept": "literal", "terms": [token], "origin": "user_text"})
    if not groups or len(groups) > 24:
        raise ValueError("Query has no searchable concept or too many literal terms")
    if dimension:
        warnings.append("Dimension is recorded as intent only, never an automatic 2D/3D filter.")
    return {"original_query": original, "glossary_version": GLOSSARY_VERSION, "groups": groups,
            "fts_expression": expression(groups), "dimension_intent": dimension,
            "warnings": warnings}
