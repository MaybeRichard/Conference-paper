#!/usr/bin/env python3
"""Import accepted papers from papercopilot/paperlists into the versioned conference corpus.

Reads the current registry/snapshot, filters each target paperlists file to
accepted main-conference papers, drops records whose normalized title already
exists anywhere in the corpus (delta import), and materializes one new release
per conference-year that still has remaining records. Then writes a new
snapshot, updates corpus/registry.json, and rebuilds DATASET_MANIFEST.json.

Policy (user decision 2026-08-19):
- Year floor: 2020.
- Accepted papers only: rejected, desk-rejected, withdrawn, and journal-track
  records are excluded. Empty-status records are excluded (ambiguous program
  status, matching the scope of the pre-existing releases).
- Existing releases are never modified; new data only enters as new releases
  and a new snapshot.
- Wave 2 (approved 2026-08-20): IJCAI 2020-2024, AISTATS 2020-2025,
  WACV 2020-2025, COLM 2024-2025; all main-track only (IJCAI survey/demo/
  journal/doctoral/special tracks excluded per the accepted-only policy).

Usage:
    python3 scripts/paperlists-import.py [--paperlists /tmp/paperlists] [--dry-run]
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFERENCE_NAMES = {
    "aaai": "AAAI",
    "aistats": "AISTATS",
    "colm": "COLM",
    "cvpr": "CVPR",
    "eccv": "ECCV",
    "iccv": "ICCV",
    "iclr": "ICLR",
    "icml": "ICML",
    "ijcai": "IJCAI",
    "nips": "NEURIPS",
    "wacv": "WACV",
}

# conference dir -> years to import (2020 floor, latest available upstream)
TARGETS = {
    "aaai": [2021, 2022, 2023, 2024, 2025],
    "aistats": [2020, 2021, 2022, 2023, 2024, 2025],
    "colm": [2024, 2025],
    "cvpr": [2020, 2021, 2022, 2023, 2024, 2025],
    "eccv": [2020, 2022, 2024],
    "iccv": [2021, 2023, 2025],
    "iclr": [2020, 2021, 2022, 2023, 2024, 2025, 2026],
    "icml": [2020, 2021, 2022, 2023, 2024, 2025, 2026],
    "ijcai": [2020, 2021, 2022, 2023, 2024],
    "nips": [2020, 2021, 2022, 2023, 2024, 2025],
    "wacv": [2020, 2021, 2022, 2023, 2024, 2025],
}

ACCEPTED_STATUSES = {
    "Poster", "Spotlight", "Oral", "Talk", "Highlight", "Award Candidate",
    "Technical", "Accept", "Top-25%", "Top-5%",
}

TIER_BY_STATUS = {
    "Poster": "poster",
    "Spotlight": "spotlight",
    "Oral": "oral",
    "Talk": "oral",
    "Highlight": "highlight",
    "Award Candidate": "award-candidate",
    "Technical": "technical",
    "Accept": "accepted",
    "Top-25%": "spotlight",
    "Top-5%": "oral",
    "ConditionalPoster": "poster",
    "ConditionalOral": "oral",
}


def canon_status(status: str) -> str:
    """Normalize OpenReview status variants (e.g. 'ICLR 2026 ConditionalPoster')."""
    return re.sub(r"^ICLR \d+ ", "", (status or "").strip())


# track whitelist per conference; None means no track filter
TRACK_OK = {
    "AAAI": {"main"},
    "AISTATS": {"main"},
    "COLM": {"main"},
    "CVPR": None,
    "ECCV": None,
    "ICCV": None,
    "ICLR": {"main"},
    "ICML": {"main", "Position"},
    "IJCAI": {"main"},
    "NEURIPS": {"main", "Datasets & Benchmarks", "Position"},
    "WACV": {"main"},
}

SOURCE_NAME = "paperlists (papercopilot/paperlists)"


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def short_id(prefix: str, *parts: str) -> str:
    return prefix + hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_lfs_pointer(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.readline().startswith(b"version https://git-lfs")


def split_semicolon(value: str) -> list:
    return [part.strip() for part in (value or "").split(";") if part.strip()]


def load_corpus_titles(corpus: Path):
    """Return (title set, snapshot release entries) of the current snapshot."""
    registry = json.loads((corpus / "corpus" / "registry.json").read_text())
    snapshot_path = corpus / next(
        entry["manifest_path"]
        for entry in registry["snapshots"]
        if entry["snapshot_id"] == registry["current_snapshot_id"]
    )
    snapshot = json.loads(snapshot_path.read_text())
    titles = set()
    for release_entry in snapshot["releases"]:
        release = json.loads((corpus / release_entry["manifest_path"]).read_text())
        shard = corpus / release["paper_shard_path"]
        # split on "\n" only: abstracts may contain literal U+2028/U+0085
        # line separators that str.splitlines() would split mid-record
        for line in shard.read_text().split("\n"):
            if line:
                titles.add(norm_title(json.loads(line)["canonical_title"]))
    return titles, snapshot, registry


def filter_accepted(conf: str, records: list) -> list:
    tracks = TRACK_OK[conf]
    out = []
    seen = set()
    for rec in records:
        status = canon_status(rec.get("status"))
        if status not in ACCEPTED_STATUSES | {"ConditionalPoster", "ConditionalOral"}:
            continue
        track = (rec.get("track") or "").strip()
        if tracks is not None and track not in tracks:
            continue
        title = (rec.get("title") or "").strip()
        if not title:
            continue
        key = norm_title(title)
        if key in seen:
            continue
        seen.add(key)
        out.append(rec)
    return out


def make_record(conf: str, year: int, rec: dict, ordinal: int) -> dict:
    title = rec["title"].strip()
    key = norm_title(title)
    source_id = (rec.get("id") or "").strip() or key
    paper_url = (rec.get("site") or rec.get("openreview") or rec.get("pdf") or "").strip()
    pdf_url = (rec.get("pdf") or "").strip()

    paper = {
        "abstract": (rec.get("abstract") or "").strip(),
        "authors": split_semicolon(rec.get("author")),
        "conference": conf,
        "decision": "accepted",
        "paper_id": short_id("paperpl_", conf, str(year), source_id, key),
        "source": SOURCE_NAME,
        "source_id": source_id,
        "tier": TIER_BY_STATUS[canon_status(rec.get("status"))],
        "title": title,
        "year": year,
    }
    if paper_url:
        paper["paper_url"] = paper_url
    if pdf_url:
        paper["pdf_url"] = pdf_url
    track = (rec.get("track") or "").strip()
    if track:
        paper["track"] = track
    keywords = split_semicolon(rec.get("keywords"))
    if keywords:
        paper["keywords"] = keywords
    primary_area = (rec.get("primary_area") or "").strip()
    if primary_area:
        paper["primary_area"] = primary_area
    github = [u for u in split_semicolon(rec.get("github")) if u.startswith("http")]
    if github:
        paper["github"] = github
    project = (rec.get("project") or "").strip()
    if project:
        paper["project"] = project
    citations = rec.get("gs_citation")
    if isinstance(citations, int):
        paper["citations"] = citations

    aliases = [
        {"alias_type": "source", "alias_value": f"{conf}:{year}:paperlists:{source_id}", "strength": "strong"},
        {"alias_type": "source_id", "alias_value": source_id, "strength": "lookup"},
    ]
    if paper_url:
        aliases.append({"alias_type": "url", "alias_value": paper_url, "strength": "strong"})
    aliases += [
        {"alias_type": "title_scope", "alias_value": f"{conf}:{year}:{key}", "strength": "weak"},
        {"alias_type": "title", "alias_value": key, "strength": "lookup"},
    ]

    return {
        "aliases": aliases,
        "canonical_title": title,
        "first_seen_year": year,
        "ordinal": ordinal,
        "paper": paper,
        "paper_id": short_id("paper_", f"paperlists|{conf}|{year}|{source_id}|{key}"),
        "source_variant_id": short_id("variant_", f"paperlists|{conf}|{year}|{source_id}"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default=".", help="conference-Idea repo root")
    ap.add_argument("--paperlists", default="/tmp/paperlists", help="paperlists checkout root")
    ap.add_argument("--dry-run", action="store_true", help="report deltas without writing")
    args = ap.parse_args()

    corpus = Path(args.corpus).resolve()
    paperlists = Path(args.paperlists).resolve()
    commit = subprocess.run(
        ["git", "-C", str(paperlists), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    titles, old_snapshot, old_registry = load_corpus_titles(corpus)
    old_paper_count = old_snapshot["paper_count"]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-paperlists-import"
    new_releases = []

    for conf_dir in sorted(TARGETS):
        conf = CONFERENCE_NAMES[conf_dir]
        for year in TARGETS[conf_dir]:
            src = paperlists / conf_dir / f"{conf_dir}{year}.json"
            if not src.exists():
                print(f"skip {conf_dir}{year}: missing upstream file")
                continue
            if is_lfs_pointer(src):
                print(f"skip {conf_dir}{year}: LFS object not fetched")
                continue
            data = json.loads(src.read_text())
            accepted = filter_accepted(conf, data)
            delta = [r for r in accepted if norm_title(r["title"].strip()) not in titles]
            print(f"{conf:8s} {year}: upstream={len(data):5d} accepted={len(accepted):5d} delta={len(delta):5d}")
            if not delta:
                continue
            release_id = short_id("release_", "paperlists-import", conf, str(year), commit, sha256_file(src))
            records = [make_record(conf, year, r, i) for i, r in enumerate(delta)]
            new_releases.append({
                "conf": conf, "year": year, "release_id": release_id,
                "records": records, "source_path": f"{conf_dir}/{conf_dir}{year}.json",
                "source_sha256": sha256_file(src),
            })
            for r in delta:
                titles.add(norm_title(r["title"].strip()))

    if not new_releases:
        print("no new records; corpus unchanged")
        return 0

    created_at = now_utc()
    materialization_parts = []
    for entry in old_snapshot["releases"]:
        materialization_parts.append(f"{entry['release_id']}|{entry['manifest_checksum']}")
    written = []
    for rel in new_releases:
        rel_dir = corpus / "corpus" / "releases" / rel["conf"] / str(rel["year"]) / rel["release_id"]
        rel_dir.mkdir(parents=True, exist_ok=True)
        shard = rel_dir / "papers.jsonl"
        shard_bytes = "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rel["records"]).encode("utf-8")
        if not args.dry_run:
            shard.write_bytes(shard_bytes)
        shard_checksum = sha256_bytes(shard_bytes)
        manifest = {
            "adapter_version": "paperlists-adapter-v1",
            "conference": rel["conf"],
            "created_at": created_at,
            "errors": [],
            "originating_run_id": run_id,
            "paper_checksum": rel["source_sha256"],
            "paper_count": len(rel["records"]),
            "paper_shard_checksum": shard_checksum,
            "paper_shard_path": f"corpus/releases/{rel['conf']}/{rel['year']}/{rel['release_id']}/papers.jsonl",
            "release_id": rel["release_id"],
            "schema_version": "corpus-release-v1",
            "source_metadata": {
                "delta_against_snapshot": old_snapshot["snapshot_id"],
                "excluded": ["rejected", "desk-rejected", "withdrawn", "journal-track", "empty-status"],
                "migration": "paperlists-import-v1",
                "source_commit": commit,
                "source_path": rel["source_path"],
                "source_repo": "https://github.com/papercopilot/paperlists",
                "source_sha256": rel["source_sha256"],
                "source_status": "available",
            },
            "source_status": "available",
            "warning_approved": False,
            "warnings": [],
            "year": rel["year"],
        }
        manifest_path = rel_dir / "manifest.json"
        if not args.dry_run:
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        manifest_checksum = sha256_bytes(
            (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        )
        materialization_parts.append(f"{rel['release_id']}|{shard_checksum}")
        written.append({
            "release_id": rel["release_id"],
            "manifest_path": f"corpus/releases/{rel['conf']}/{rel['year']}/{rel['release_id']}/manifest.json",
            "manifest_checksum": manifest_checksum,
            "conference": rel["conf"],
            "year": rel["year"],
        })
        print(f"new release {rel['release_id']}: {rel['conf']} {rel['year']} = {len(rel['records'])} records")

    materialization_content = "\n".join(sorted(materialization_parts))
    materialization_digest = hashlib.sha1(materialization_content.encode("utf-8")).hexdigest()
    snapshot_id = "snapshot_" + materialization_digest[:16]
    snapshot = {
        "created_at": created_at,
        "materialization_checksum": sha256_bytes(materialization_content.encode("utf-8")),
        "paper_count": old_paper_count + sum(len(r["records"]) for r in new_releases),
        "releases": sorted(
            old_snapshot["releases"] + written,
            key=lambda e: (e["conference"], e["year"], e["release_id"]),
        ),
        "schema_version": "corpus-snapshot-v1",
        "snapshot_id": snapshot_id,
    }
    if args.dry_run:
        print(f"\n[dry-run] would create {snapshot_id}: {snapshot['paper_count']} papers across "
              f"{len(snapshot['releases'])} releases (+{snapshot['paper_count'] - old_paper_count}); nothing written")
        return 0

    snapshot_path = f"corpus/snapshots/{snapshot_id}/manifest.json"
    (corpus / snapshot_path).parent.mkdir(parents=True, exist_ok=True)
    (corpus / snapshot_path).write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    registry = old_registry
    registry["releases"] = old_registry["releases"] + written
    registry["snapshots"] = old_registry["snapshots"] + [{
        "manifest_checksum": sha256_file(corpus / snapshot_path),
        "manifest_path": snapshot_path,
        "snapshot_id": snapshot_id,
    }]
    registry["current_snapshot_id"] = snapshot_id
    registry["generation"] = old_registry.get("generation", 0) + 1
    (corpus / "corpus" / "registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    )

    manifest = json.loads((corpus / "DATASET_MANIFEST.json").read_text())
    file_entries = [
        {"path": "corpus/registry.json", "bytes": (corpus / "corpus/registry.json").stat().st_size, "sha256": sha256_file(corpus / "corpus/registry.json")},
        {"path": snapshot_path, "bytes": (corpus / snapshot_path).stat().st_size, "sha256": sha256_file(corpus / snapshot_path)},
    ]
    for entry in sorted(snapshot["releases"], key=lambda e: (e["conference"], e["year"], e["release_id"])):
        for name, path in (("manifest.json", entry["manifest_path"]),
                           ("papers.jsonl", entry["manifest_path"].replace("manifest.json", "papers.jsonl"))):
            p = corpus / path
            file_entries.append({"path": path, "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    manifest["conference_years"] = [
        {"conference": e["conference"], "year": e["year"]} for e in snapshot["releases"]
    ]
    manifest["files"] = file_entries
    manifest["included_fields"] = [
        "abstract", "authors", "citations", "decision", "doi", "github", "keywords",
        "paper_url", "pdf_url", "primary_area", "project", "tier", "title", "track",
    ]
    manifest["paper_count"] = snapshot["paper_count"]
    manifest["release_count"] = len(snapshot["releases"])
    manifest["snapshot_id"] = snapshot_id
    (corpus / "DATASET_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    print(f"\nsnapshot {snapshot_id}: {snapshot['paper_count']} papers across {len(snapshot['releases'])} releases "
          f"({old_paper_count} + {snapshot['paper_count'] - old_paper_count} imported)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
