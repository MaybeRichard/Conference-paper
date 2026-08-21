#!/usr/bin/env python3
"""Fetch Semantic Scholar bulk-search enrichment for MICCAI/ISBI updates.

Produces <out>/<venue>_<year>.json (keys: venue, year, total, fetched_at, data)
in the raw-fetch layout expected by `scripts/medical-import.py --stage-from`.

Usage:
  python3 scripts/medical/fetch_s2.py --out RAW --venue MICCAI --year 2026
  python3 scripts/medical/fetch_s2.py --out RAW --venue ISBI --year 2026

Notes:
- S2 is ENRICHMENT ONLY (abstract, citationCount, openAccessPdf). It is NOT
  reliable for enumerating accepted papers (it mixes adjacent years and
  non-proceedings LNCS books) -- use Crossref for enumeration.
- Unauthenticated bulk search rate-limits aggressively; this script backs off
  on HTTP 429. Expect long runtimes for large venues/years.
- S2 API data is licensed CC BY-NC 4.0 (non-commercial, attribution required).
"""
import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
FIELDS = "title,abstract,authors,externalIds,citationCount,venue,year,openAccessPdf,url"
UA = {"User-Agent": "corpus-research/1.0 (mailto:research@example.com)"}


def get(url: str, tries: int = 8):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 60 * (i + 1)
                print(f"  429, sleeping {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("giving up on " + url)


def fetch(venue: str, year: int):
    params = {"venue": venue, "year": str(year), "fields": FIELDS}
    url = BASE + "?" + urllib.parse.urlencode(params)
    pages, token = [], None
    while True:
        u = url + ("&token=" + urllib.parse.quote(token) if token else "")
        d = get(u)
        pages.extend(d.get("data") or [])
        token = d.get("token")
        if not token:
            break
        time.sleep(15)
    return d.get("total"), pages


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, help="raw-fetch output directory")
    ap.add_argument("--venue", required=True, choices=["MICCAI", "ISBI"])
    ap.add_argument("--year", required=True, type=int)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{args.venue.lower()}_{args.year}.json"
    print(f"S2 bulk search: venue={args.venue} year={args.year}", flush=True)
    total, data = fetch(args.venue, args.year)
    path.write_text(json.dumps(
        {"venue": args.venue, "year": args.year, "total": total,
         "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
         "data": data}, ensure_ascii=False))
    print(f"{args.venue} {args.year}: total={total} got={len(data)}", flush=True)
    if len(data) != (total or 0):
        print(f"  WARNING: page count {len(data)} != total {total}", file=sys.stderr)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
