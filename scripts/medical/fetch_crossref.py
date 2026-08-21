#!/usr/bin/env python3
"""Fetch official-proceedings metadata from Crossref for MICCAI/ISBI updates.

Produces the raw-fetch layout expected by `scripts/medical-import.py --stage-from`:

  <out>/vols/<book_doi with '/'->'_'>.json   MICCAI: one LNCS volume (Crossref message object)
  <out>/isbi_xref_<year>.json                ISBI: one year's proceedings (Crossref message object)

A "message object" is the Crossref response `message` dict:
{"total-results": N, "items": [...]} with fields DOI, title, author, type,
page, container-title, published.

Usage:
  # MICCAI: fetch one main-conference LNCS volume by its book DOI
  python3 scripts/medical/fetch_crossref.py --out RAW --miccai-volume 10.1007/978-3-031-95387-7

  # ISBI: fetch one year by the EXACT proceedings container-title
  # (note: the ordinal may be absent in the registered title, e.g. 2024 has none)
  python3 scripts/medical/fetch_crossref.py --out RAW --isbi 2026 \
      "2026 IEEE 23rd International Symposium on Biomedical Imaging (ISBI)"

Notes:
- For MICCAI, find the main-conference volume ISBNs/DOIs on the Springer
  MICCAI proceedings page. Workshop volumes may be fetched but are dropped
  automatically at staging (title must contain " – MICCAI " and no "Workshop").
- ISBI enumeration is by exact `container-title`; a wrong guess returns 0
  results (this script fails loudly on empty results).
- Crossref is the authoritative "accepted = published in official
  proceedings" enumeration; use it, not Semantic Scholar, for enumeration.
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "corpus-research/1.0 (mailto:research@example.com)"}
SELECT = "DOI,title,author,type,page,container-title,published"


def get_json(url: str, tries: int = 10, base_wait: float = 10.0):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - retry any network error
            if i == tries - 1:
                raise
            wait = base_wait * (1 + i // 5)
            print(f"  retry {i + 1} after {wait:.0f}s ({e.__class__.__name__})", flush=True)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def crossref_message(filter_value: str) -> dict:
    """Fetch ALL items for a Crossref filter, returning a message-style dict."""
    items, offset, total = [], 0, None
    while True:
        params = urllib.parse.urlencode(
            {"filter": filter_value, "rows": 1000, "offset": offset, "select": SELECT}
        )
        d = get_json(f"https://api.crossref.org/works?{params}")
        msg = d["message"]
        if total is None:
            total = msg["total-results"]
            print(f"  total-results: {total}", flush=True)
        page = msg["items"]
        items.extend(page)
        offset += len(page)
        if not page or offset >= total:
            break
        time.sleep(2)
    if not items:
        sys.exit(f"Crossref returned 0 items for filter={filter_value!r}; check the input")
    print(f"  fetched {len(items)} items", flush=True)
    return {"total-results": total, "items": items}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="raw-fetch output directory")
    ap.add_argument("--miccai-volume", metavar="BOOK_DOI",
                    help="MICCAI LNCS volume book DOI, e.g. 10.1007/978-3-031-95387-7")
    ap.add_argument("--isbi", nargs=2, metavar=("YEAR", "CONTAINER_TITLE"),
                    help="ISBI year and exact proceedings container-title")
    args = ap.parse_args()
    if not args.miccai_volume and not args.isbi:
        ap.error("provide --miccai-volume or --isbi")

    out = Path(args.out)
    if args.miccai_volume:
        book_doi = args.miccai_volume.strip()
        isbn = book_doi.split("/", 1)[1]
        print(f"MICCAI volume {book_doi} (isbn {isbn})")
        msg = crossref_message(f"isbn:{isbn}")
        vol_dir = out / "vols"
        vol_dir.mkdir(parents=True, exist_ok=True)
        path = vol_dir / (book_doi.replace("/", "_") + ".json")
        path.write_text(json.dumps(msg, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"wrote {path}")

    if args.isbi:
        year, title = args.isbi[0], args.isbi[1].strip()
        print(f"ISBI {year}: {title}")
        # NB: do NOT quote the container-title in the filter; quoted filters
        # return 0 results for these proceedings titles.
        msg = crossref_message(f"container-title:{urllib.parse.quote(title, safe='')}")
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"isbi_xref_{year}.json"
        path.write_text(json.dumps(msg, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
