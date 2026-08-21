#!/usr/bin/env python3
"""Import MICCAI and ISBI accepted papers (2020-2025) into the versioned conference corpus.

Source resolution (decision 2026-08-20, per RESUME option chain
"GitHub aggregation -> API -> fallback"; see corpus/sources/medical/source-info.json):
- No suitable ready-made GitHub aggregation existed (checked 2026-08-20).
- Enumeration (accepted = published in the official proceedings, per user
  criteria): Crossref publisher-registered records.
    - MICCAI: chapters of the LNCS volumes titled exactly
      "Medical Image Computing and Computer Assisted Intervention – MICCAI <year>"
      (workshop volumes excluded), enumerated per volume via filter=isbn:<isbn>.
    - ISBI: papers of the IEEE proceedings enumerated via
      filter=container-title:"<exact proceedings title>" per year.
- Enrichment (abstracts + citation counts): Semantic Scholar bulk search
  (venue=MICCAI/ISBI, year 2020-2026), matched by DOI with normalized-title
  fallback. S2 is CC BY-NC 4.0. Coverage observed at fetch time:
    MICCAI ~53% abstracts / ~98% citations; ISBI ~97% abstracts / ~97% citations.
- No full text is stored; records carry the DOI landing-page URL (and the S2
  open-access PDF URL when S2 has one).

The raw API fetches are staged into corpus/sources/medical/ (committed, so each
release stays auditable and re-importable); their SHA-256 values are pinned in
every release's source_metadata.

Usage:
    python3 scripts/medical-import.py --stage-from /path/to/raw-fetch
    python3 scripts/medical-import.py [--dry-run]

Policy:
- Year floor: 2020 (MICCAI and ISBI both 2020-2025).
- Accepted-only: enumeration is the published proceedings itself; workshop
  and other non-main-conference records are excluded.
- Existing releases are never modified; new data only enters as new releases
  and a new snapshot. Re-running is a no-op for conference-years already
  imported by medical-import-v1.

ID mechanism (deterministic, mirrors scripts/paperlists-import.py):
    paper_id          = paper_<sha1[:16] of "medical|CONF|YEAR|doi|norm_title">
    paper.paper_id    = papermed_<sha1[:16] of "CONF|YEAR|doi|norm_title">
    source_variant_id = variant_<sha1[:16] of "medical|CONF|YEAR|doi">
    release_id        = release_<sha1[:16] of "medical-import-v1|CONF|YEAR|sha256(bundle)">
"""

import argparse
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

CONFERENCE_NAMES = ("MICCAI", "ISBI")

TARGETS = {
    "MICCAI": [2020, 2021, 2022, 2023, 2024, 2025],
    "ISBI": [2020, 2021, 2022, 2023, 2024, 2025],
}

# S2 fetch files used for enrichment (year 2026 included for MICCAI: some
# 2025-proceedings papers are tagged year=2026 by Semantic Scholar)
S2_FILES = {
    "MICCAI": [f"miccai-{y}.json" for y in range(2020, 2027)],
    "ISBI": [f"isbi-{y}.json" for y in range(2020, 2026)],
}

MIGRATION = "medical-import-v1"
SOURCE_LABEL = "Crossref proceedings (publisher-registered) + Semantic Scholar enrichment"
S2_LICENSE = "CC BY-NC 4.0"


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


def clean_abstract(text: str) -> str:
    """Normalize an S2 abstract for safe JSONL storage and readability."""
    if not text:
        return ""
    s = re.sub(r"[\u2028\u2029\x85\r\x0b\x0c]", " ", text)
    s = re.sub(r"<[^>]+>", " ", s)  # strip stray JATS/HTML tags
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r" ?\n ?", "\n", s)
    return s.strip()


def crossref_authors(authors: list) -> list:
    out = []
    for a in authors or []:
        if not isinstance(a, dict):
            continue
        given = (a.get("given") or "").strip()
        family = (a.get("family") or "").strip()
        name = (a.get("name") or "").strip()
        if given or family:
            out.append(f"{given} {family}".strip())
        elif name:
            out.append(name)
    return out


def load_corpus_titles(corpus: Path):
    """Return (title set, current snapshot, registry) of the current corpus."""
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


def build_s2_enrichment(sources_dir: Path, conf: str):
    """Return (doi_map, title_map) from the staged S2 fetch files of conf."""
    doi_map, title_map = {}, {}
    for name in S2_FILES[conf]:
        path = sources_dir / "s2" / name
        if not path.exists():
            print(f"skip enrichment file {path}: missing", file=sys.stderr)
            continue
        data = json.loads(path.read_text())
        for p in data.get("data", []):
            title = (p.get("title") or "").strip()
            if not title:
                continue
            doi = ((p.get("externalIds") or {}).get("DOI") or "").lower()
            if doi and doi not in doi_map:
                doi_map[doi] = p
            key = norm_title(title)
            cur = title_map.get(key)
            if cur is None or (not cur.get("abstract") and p.get("abstract")):
                title_map[key] = p
    return doi_map, title_map


def stage(raw_dir: Path, corpus: Path) -> None:
    """Organize raw API fetches from raw_dir into corpus/sources/medical/."""
    dst = corpus / "corpus" / "sources" / "medical"
    (dst / "crossref").mkdir(parents=True, exist_ok=True)
    (dst / "s2").mkdir(parents=True, exist_ok=True)
    written = []

    # MICCAI: bundle per-volume Crossref chapter lists by proceedings year
    vol_files = sorted((raw_dir / "vols").glob("*.json"))
    if not vol_files:
        sys.exit(f"no Crossref volume files under {raw_dir / 'vols'}")
    by_year = {}
    for vf in vol_files:
        m = json.loads(vf.read_text())
        ct = " | ".join(m["items"][0].get("container-title") or [])
        mm = re.search(r"MICCAI (\d{4})", ct)
        if not mm or "Workshop" in ct or " – MICCAI " not in ct:
            continue  # non-MICCAI or workshop volume
        book_doi = vf.name[:-5].replace("_", "/", 1)
        by_year.setdefault(mm.group(1), []).append({
            "book_doi": book_doi,
            "isbn": book_doi.split("/")[1].replace("-", ""),
            "container_title": m["items"][0]["container-title"],
            "chapter_count": m["total-results"],
            "items": m["items"],
        })
    for year in sorted(by_year):
        volumes = sorted(by_year[year], key=lambda v: v["isbn"])
        out = dst / "crossref" / f"miccai-{year}.json"
        out.write_text(json.dumps({"conference": "MICCAI", "year": int(year),
                                   "volumes": volumes}, ensure_ascii=False, sort_keys=True) + "\n")
        written.append(out)

    # ISBI: per-year proceedings lists
    for y in range(2020, 2026):
        src = raw_dir / f"isbi_xref_{y}.json"
        if not src.exists():
            sys.exit(f"missing raw ISBI Crossref fetch {src}")
        out = dst / "crossref" / f"isbi-{y}.json"
        shutil.copyfile(src, out)
        written.append(out)

    # S2 enrichment fetches
    for conf in CONFERENCE_NAMES:
        for name in S2_FILES[conf]:
            src = raw_dir / name.replace("-", "_")
            if not src.exists():
                sys.exit(f"missing raw S2 fetch {src}")
            out = dst / "s2" / name
            shutil.copyfile(src, out)
            written.append(out)

    s2_fetched = {}
    for f in sorted((dst / "s2").glob("*.json")):
        s2_fetched[f.name] = json.loads(f.read_text()).get("fetched_at")
    info = {
        "staged_at": now_utc(),
        "crossref": {
            "api": "https://api.crossref.org",
            "miccai_method": "chapter enumeration per LNCS volume via filter=isbn:<isbn>&rows=200",
            "isbi_method": "proceedings enumeration via filter=container-title:<exact title>&rows=1000",
        },
        "semanticscholar": {
            "api": "https://api.semanticscholar.org/graph/v1/paper/search/bulk",
            "queries": [{"venue": c, "year": y} for c, years in
                        (("MICCAI", range(2020, 2027)), ("ISBI", range(2020, 2026)))
                        for y in years],
            "fetched_at_by_file": s2_fetched,
            "license": S2_LICENSE,
        },
        "notes": [
            "Accepted = published in the official proceedings (publisher-registered).",
            "MICCAI workshop volumes and non-MICCAI LNCS books are excluded.",
            "S2 enrichment matched by DOI, with normalized-title fallback.",
            "citationCount is a Semantic Scholar snapshot as of fetch time.",
        ],
    }
    (dst / "source-info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(f"staged {len(written) + 1} raw files under {dst.relative_to(corpus)}")


def make_record(conf: str, year: int, item: dict, ordinal: int,
                doi_map: dict, title_map: dict) -> dict | None:
    title = (item.get("title") or [""])[0].strip()
    doi = (item.get("DOI") or "").strip()
    if not title or not doi:
        return None
    key = norm_title(title)
    s2 = doi_map.get(doi.lower()) or title_map.get(key)
    s2_title = norm_title(s2.get("title") or "") if s2 else ""
    if s2 and s2_title and s2_title != key:
        s2 = None  # title fallback matched the wrong paper
    abstract = clean_abstract(s2.get("abstract") or "") if s2 else ""
    citations = s2.get("citationCount") if s2 else None
    oa_pdf = ((s2 or {}).get("openAccessPdf") or {}).get("url") or ""

    paper = {
        "abstract": abstract,
        "authors": crossref_authors(item.get("author")),
        "conference": conf,
        "decision": "accepted",
        "doi": doi,
        "paper_id": short_id("papermed_", conf, str(year), doi, key),
        "paper_url": f"https://doi.org/{doi}",
        "source": SOURCE_LABEL,
        "source_id": doi,
        "title": title,
        "year": year,
    }
    if isinstance(citations, int):
        paper["citations"] = citations
    if oa_pdf:
        paper["pdf_url"] = oa_pdf

    aliases = [
        {"alias_type": "source", "alias_value": f"{conf}:{year}:medical:{doi}", "strength": "strong"},
        {"alias_type": "source_id", "alias_value": doi, "strength": "lookup"},
        {"alias_type": "url", "alias_value": f"https://doi.org/{doi}", "strength": "strong"},
        {"alias_type": "title_scope", "alias_value": f"{conf}:{year}:{key}", "strength": "weak"},
        {"alias_type": "title", "alias_value": key, "strength": "lookup"},
    ]
    return {
        "aliases": aliases,
        "canonical_title": title,
        "first_seen_year": year,
        "ordinal": ordinal,
        "paper": paper,
        "paper_id": short_id("paper_", f"medical|{conf}|{year}|{doi}|{key}"),
        "source_variant_id": short_id("variant_", f"medical|{conf}|{year}|{doi}"),
    }


def enumerate_items(sources_dir: Path, conf: str, year: int):
    """Yield (bundle_path, [crossref items]) for one conference-year."""
    bundle = sources_dir / "crossref" / f"{conf.lower()}-{year}.json"
    if not bundle.exists():
        return None, None
    data = json.loads(bundle.read_text())
    items = []
    if conf == "MICCAI":
        for vol in data["volumes"]:
            # the isbn filter also returns the volume (type=book) itself
            items.extend(it for it in vol["items"] if it.get("type") != "book")
    else:
        items = data["items"]
    items = sorted(items, key=lambda it: (it.get("DOI") or "").lower())
    return bundle, items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", default=".", help="conference-Idea repo root")
    ap.add_argument("--stage-from", metavar="DIR", help="stage raw fetches from DIR and exit")
    ap.add_argument("--dry-run", action="store_true", help="report without writing")
    args = ap.parse_args()

    corpus = Path(args.corpus).resolve()
    if args.stage_from:
        stage(Path(args.stage_from).resolve(), corpus)
        return 0

    sources_dir = corpus / "corpus" / "sources" / "medical"
    if not sources_dir.exists():
        sys.exit(f"{sources_dir} missing; run --stage-from <raw dir> first")

    titles, old_snapshot, old_registry = load_corpus_titles(corpus)
    old_paper_count = old_snapshot["paper_count"]

    already = {
        (e["conference"], e["year"])
        for e in old_registry["releases"]
        if e["conference"] in TARGETS
    }

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-medical-import"
    new_releases = []

    for conf in CONFERENCE_NAMES:
        doi_map, title_map = build_s2_enrichment(sources_dir, conf)
        for year in TARGETS[conf]:
            if (conf, year) in already:
                print(f"skip {conf} {year}: medical release already present")
                continue
            bundle, items = enumerate_items(sources_dir, conf, year)
            if items is None:
                print(f"skip {conf} {year}: missing bundle {bundle}", file=sys.stderr)
                continue
            records, seen, n_no_s2 = [], set(), 0
            for item in items:
                rec = make_record(conf, year, item, 0, doi_map, title_map)
                if rec is None:
                    continue
                key = norm_title(rec["canonical_title"])
                if key in seen:
                    continue
                seen.add(key)
                if key in titles:
                    continue  # defensive: already covered by another release
                if not rec["paper"]["abstract"]:
                    n_no_s2 += 1
                records.append(rec)
            for i, rec in enumerate(records):
                rec["ordinal"] = i
            n_abs = sum(1 for r in records if r["paper"]["abstract"])
            print(f"{conf:7s} {year}: proceedings={len(items):5d} imported={len(records):5d} "
                  f"abstracts={n_abs} ({n_abs / max(len(records), 1) * 100:.0f}%)")
            if not records:
                continue
            new_releases.append({
                "conf": conf, "year": year,
                "release_id": short_id("release_", MIGRATION, conf, str(year), sha256_file(bundle)),
                "records": records,
                "bundle_path": str(bundle.relative_to(corpus)),
                "bundle_sha256": sha256_file(bundle),
            })
            titles.update(norm_title(r["canonical_title"]) for r in records)

    if not new_releases:
        print("no new records; corpus unchanged")
        return 0

    created_at = now_utc()

    # 1. write release dirs (layout mirrors scripts/paperlists-import.py)
    materialization_parts = [
        f"{entry['release_id']}|{entry['manifest_checksum']}"
        for entry in old_snapshot["releases"]
    ]
    written = []
    for rel in new_releases:
        rel_dir = corpus / "corpus" / "releases" / rel["conf"] / str(rel["year"]) / rel["release_id"]
        rel_dir.mkdir(parents=True, exist_ok=True)
        shard = rel_dir / "papers.jsonl"
        shard_bytes = "".join(
            json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rel["records"]
        ).encode("utf-8")
        if not args.dry_run:
            shard.write_bytes(shard_bytes)
        shard_checksum = sha256_bytes(shard_bytes)
        s2_names = [n for n in S2_FILES[rel["conf"]] if (sources_dir / "s2" / n).exists()]
        manifest = {
            "adapter_version": "medical-adapter-v1",
            "conference": rel["conf"],
            "created_at": created_at,
            "errors": [],
            "originating_run_id": run_id,
            "paper_checksum": rel["bundle_sha256"],
            "paper_count": len(rel["records"]),
            "paper_shard_checksum": shard_checksum,
            "paper_shard_path": f"corpus/releases/{rel['conf']}/{rel['year']}/{rel['release_id']}/papers.jsonl",
            "release_id": rel["release_id"],
            "schema_version": "corpus-release-v1",
            "source_metadata": {
                "accepted_criteria": "chapter/paper published in the official "
                                     "proceedings (publisher-registered at Crossref)",
                "delta_against_snapshot": old_snapshot["snapshot_id"],
                "enrichment": {
                    "api": "https://api.semanticscholar.org/graph/v1/paper/search/bulk",
                    "license": S2_LICENSE,
                    "matching": "DOI, with normalized-title fallback",
                    "files": [
                        {"path": str((sources_dir / "s2" / n).relative_to(corpus)),
                         "sha256": sha256_file(sources_dir / "s2" / n)}
                        for n in s2_names
                    ],
                },
                "excluded": [
                    "workshop and other non-main-conference records",
                    "LNCS volume (type=book) records themselves",
                    "records without title or DOI",
                    "duplicate titles within the proceedings (first by DOI order kept)",
                ],
                "migration": MIGRATION,
                "source_commit": None,
                "source_files": [
                    {"path": rel["bundle_path"], "sha256": rel["bundle_sha256"],
                     "role": "enumeration (Crossref)"}
                ],
                "source_kind": "api-snapshot (Crossref enumeration + Semantic Scholar enrichment)",
                "source_path": rel["bundle_path"],
                "source_repo": "https://api.crossref.org",
                "source_sha256": rel["bundle_sha256"],
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
            "conference": rel["conf"],
            "manifest_checksum": manifest_checksum,
            "manifest_path": f"corpus/releases/{rel['conf']}/{rel['year']}/{rel['release_id']}/manifest.json",
            "release_id": rel["release_id"],
            "year": rel["year"],
        })
        if not args.dry_run:
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

    # 2. updated registry (old entries preserved)
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

    # 3. DATASET_MANIFEST.json (releases + committed raw sources + registry + snapshot)
    manifest = json.loads((corpus / "DATASET_MANIFEST.json").read_text())
    file_entries = [
        {"path": "corpus/registry.json",
         "bytes": (corpus / "corpus/registry.json").stat().st_size,
         "sha256": sha256_file(corpus / "corpus/registry.json")},
        {"path": snapshot_path,
         "bytes": (corpus / snapshot_path).stat().st_size,
         "sha256": sha256_file(corpus / snapshot_path)},
    ]
    for entry in sorted(snapshot["releases"], key=lambda e: (e["conference"], e["year"], e["release_id"])):
        for name, path in (("manifest.json", entry["manifest_path"]),
                           ("papers.jsonl", entry["manifest_path"].replace("manifest.json", "papers.jsonl"))):
            p = corpus / path
            file_entries.append({"path": path, "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    for src_path in sorted((corpus / "corpus" / "sources").rglob("*")):
        if src_path.is_file():
            rel_path = str(src_path.relative_to(corpus))
            file_entries.append({"path": rel_path, "bytes": src_path.stat().st_size,
                                 "sha256": sha256_file(src_path)})
    manifest["conference_years"] = [
        {"conference": e["conference"], "year": e["year"]} for e in snapshot["releases"]
    ]
    manifest["files"] = sorted(file_entries, key=lambda f: f["path"])
    manifest["paper_count"] = snapshot["paper_count"]
    manifest["release_count"] = len(snapshot["releases"])
    manifest["snapshot_id"] = snapshot_id
    (corpus / "DATASET_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")

    print(f"\nsnapshot {snapshot_id}: {snapshot['paper_count']} papers across {len(snapshot['releases'])} releases "
          f"({old_paper_count} + {snapshot['paper_count'] - old_paper_count} imported)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
