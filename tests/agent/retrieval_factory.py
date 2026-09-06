"""Synthetic indexed corpora; never mutate the real source snapshot."""
import json
from pathlib import Path

from tests.agent.corpus_factory import make_corpus, rehash, read_json, write_json, SHARD, RELEASE, SNAPSHOT


def make_retrieval_corpus(root: Path, papers: list[dict] | None = None) -> Path:
    make_corpus(root)
    if papers is None:
        papers = [
            dict(paper_id="reti", title="RetiDiff: Diffusion-Based Synthesis of Retinal OCT Images", abstract="", conference="MICCAI", year=2025),
            dict(paper_id="stain", title="DiffStain: Conditioned Diffusion-Based Semantic Virtual Staining", abstract="N/A", conference="MICCAI", year=2025),
            dict(paper_id="split", title="A diffusion model", abstract="Medical image synthesis for retinal training data.", conference="CVPR", year=2024),
            dict(paper_id="mixed", title="Slice-Consistent 3D Medical Synthesis with a 2D Diffusion Model", abstract="Adjacent slices are required.", conference="MICCAI", year=2024),
            dict(paper_id="seg", title="MedSegDiff: Diffusion-Based Medical Image Segmentation", abstract="A generative model for segmentation.", conference="AAAI", year=2024),
            dict(paper_id="generic", title="Fairness in language classification", abstract="An unrelated sentence.", conference="ICLR", year=2023),
            dict(paper_id="full", title="Medical diffusion image synthesis", abstract="Medical diffusion generation and image synthesis for clinical data augmentation.", conference="MICCAI", year=2025),
        ]
    records = [{"paper_id": p["paper_id"], "canonical_title": p["title"], "paper": p} for p in papers]
    (root / SHARD).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    for path in [RELEASE, SNAPSHOT]:
        data = read_json(root, path)
        data["paper_count"] = len(records)
        write_json(root, path, data)
    rehash(root)
    return root
