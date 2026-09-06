"""Conservative source normalization and lexical review hints, not inference."""
from __future__ import annotations

import re
import unicodedata

from research_agent.core.errors import IntegrityError
from research_agent.core.serialization import digest

NORMALIZATION_VERSION = "source-text-v2"
MISSING = frozenset({"", "n/a", "na", "none", "null", "nan", "-", "unknown",
                     "not available", "no abstract", "no abstract available"})


def clean_text(value: object) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()) if isinstance(value, str) else ""


def abstract_status(value: object) -> str:
    text = clean_text(value)
    if not text: return "missing"
    if text.casefold().strip(" .") in MISSING: return "placeholder"
    return "present"


def normalize_record(located) -> dict:
    record = located.record
    paper = record.get("paper", record)
    if not isinstance(paper, dict):
        raise IntegrityError("Source record has an invalid paper object")
    title = clean_text(paper.get("title")) or clean_text(record.get("canonical_title"))
    status = abstract_status(paper.get("abstract"))
    year = paper.get("year")
    if type(year) is not int or not 1800 <= year <= 2200: year = None
    source_hash = digest(record)
    return dict(
        record_key=digest({"shard": located.shard_path, "record": located.record_number,
                           "sha256": source_hash}),
        paper_id=clean_text(record.get("paper_id")) or clean_text(paper.get("paper_id")),
        source_paper_id=clean_text(paper.get("paper_id")),
        source_title=paper.get("title") if isinstance(paper.get("title"), str) else title,
        source_variant_id=clean_text(record.get("source_variant_id")),
        title=title, abstract=clean_text(paper.get("abstract")) if status == "present" else "",
        abstract_status=status, conference=clean_text(paper.get("conference")).upper(),
        year=year, doi=clean_text(paper.get("doi")), paper_url=clean_text(paper.get("paper_url")),
        pdf_url=clean_text(paper.get("pdf_url")), source=clean_text(paper.get("source")),
        source_id=clean_text(paper.get("source_id")),
        normalized_title=re.sub(r"[^\w]+", " ", title.casefold()).strip(),
        shard_path=located.shard_path, shard_sha256=located.shard_sha256,
        record_number=located.record_number, record_sha256=source_hash,
    )


def review_hints(title: str, abstract: str) -> dict:
    text = (title + " " + abstract).casefold()
    patterns = {
        "2d_mentioned": r"\b2[ -]?d\b|two[ -]dimensional",
        "2_5d_mentioned": r"\b2[.]5[ -]?d\b",
        "3d_mentioned": r"\b3[ -]?d\b|three[ -]dimensional|volumetric",
        "slice_dependency_mentioned": r"adjacent[ -]slice|slice[ -]consisten|cross[ -]slice",
        "segmentation_mentioned": r"segmentat",
        "reconstruction_mentioned": r"reconstruct",
        "generation_mentioned": r"generat|synthes|synthetic|stain|image[ -]to[ -]image|translation",
        "diffusion_mentioned": r"diffusion|\bddpm\b|score[ -]based",
        "flow_matching_mentioned": r"flow[ -]matching",
        "physical_diffusion_caution": r"diffusion[ -]weighted|diffusion[ -]tensor|diffusion[ -]adapted|spatial[ -]filter",
    }
    return {"scope_status": "unreviewed", "basis": "lexical_mentions_only",
            "signals": [key for key, pattern in patterns.items() if re.search(pattern, text)]}
