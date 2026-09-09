"""Bounded BM25 channel fusion with explicit missing-abstract protection."""
from __future__ import annotations

from collections import Counter
import sqlite3

from research_agent.core.errors import IntegrityError
from research_agent.retrieval.index import LexicalIndex
from research_agent.retrieval.query import plan_query, expression
from research_agent.retrieval.records import clean_text, review_hints


def search(index: LexicalIndex, query: str, *, index_id=None, limit=50, per_channel=500,
           conference=None, year_from=None, year_to=None) -> dict:
    if type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError("limit must be an integer between 1 and 1000")
    if type(per_channel) is not int or not 1 <= per_channel <= 5000:
        raise ValueError("per_channel must be an integer between 1 and 5000")
    for year in (year_from, year_to):
        if year is not None and (type(year) is not int or not 1800 <= year <= 2200):
            raise ValueError("Invalid year filter")
    if year_from is not None and year_to is not None and year_from > year_to:
        raise ValueError("Invalid year range")
    if conference is not None and (not isinstance(conference, str) or not conference.strip() or len(conference)>80):
        raise ValueError("Invalid conference filter")
    conference = clean_text(conference).upper() if conference else None
    plan = plan_query(query)
    filters = dict(conference=conference, year_from=year_from, year_to=year_to)
    where = []
    params = []
    for clause, value in [("d.conference=?", conference), ("d.year>=?", year_from), ("d.year<=?", year_to)]:
        if value is not None: where.append(clause); params.append(value)
    lanes = [(name, name, plan["fts_expression"], []) for name in ["title", "abstract", "combined"]]
    lanes.append(("missing_title", "title", plan["fts_expression"], ["d.abstract_status!='present'"]))
    nonmedical = [x for x in plan["groups"] if x["concept"] != "medical"]
    if nonmedical and len(nonmedical) < len(plan["groups"]):
        venue_prior = "d.conference IN ('MICCAI','ISBI')"
        lanes.extend([
            ("medical_venue_title", "title", expression(nonmedical), [venue_prior]),
            ("medical_venue_missing_title", "title", expression(nonmedical), [venue_prior, "d.abstract_status!='present'"]),
        ])
        plan["warnings"].append("Medical-venue title lanes relax only the medical-word clause; venue is not an eligibility verdict.")
    pool = {}
    audits = []
    try:
        db, manifest = index._open_verified(index_id)
        try:
            for lane, channel, terms, extra in lanes:
                table = channel + "_fts"  # channel names are internal constants, not user input.
                conditions = " AND ".join([f"{table} MATCH ?"] + where + extra)
                sql_from = f" FROM {table} JOIN documents d ON d.id={table}.rowid WHERE {conditions}"
                count = db.execute("SELECT COUNT(*)" + sql_from, [terms, *params]).fetchone()[0]
                rows = db.execute(f"SELECT d.*,bm25({table}) AS bm25_score" + sql_from +
                                  " ORDER BY bm25_score ASC,d.record_key ASC LIMIT ?", [terms, *params, per_channel]).fetchall()
                audits.append({"channel": lane, "fts_expression": terms, "matched_records": count,
                               "retrieved_records": len(rows), "truncated": count > len(rows)})
                for rank, row in enumerate(rows, 1):
                    key = row["record_key"]
                    if key not in pool:
                        doc = dict(row)
                        abstract = doc.pop("abstract")
                        doc.pop("bm25_score", None); doc.pop("id", None)
                        hints = review_hints(doc["title"], abstract)
                        same_title = db.execute("SELECT COUNT(*) FROM documents WHERE normalized_title=?", [doc["normalized_title"]]).fetchone()[0] if doc["normalized_title"] else 1
                        doc.pop("normalized_title")
                        provenance = {k: doc.pop(k) for k in ["shard_path", "shard_sha256", "record_number", "record_sha256"]}
                        provenance.update(snapshot_id=manifest["snapshot_id"], snapshot_checksum=manifest["snapshot_checksum"],
                                          locator_kind="one_based_nonempty_record")
                        pool[key] = {**doc, "provenance": provenance, "scope_status": "unreviewed",
                                     "review_hints": hints, "same_title_records": same_title,
                                     "fusion_score": 0.0, "retrieval_evidence": [], "selection_reasons": []}
                    pool[key]["fusion_score"] += 1.0/(60 + rank)
                    pool[key]["retrieval_evidence"].append({"channel": lane, "rank": rank, "bm25": row["bm25_score"]})
        finally: db.close()
    except sqlite3.Error:
        raise IntegrityError("Lexical query/index failed; source content omitted") from None

    ordered = sorted(pool.values(), key=lambda x: (-x["fusion_score"], x["record_key"]))
    # Quota is a transparent retrieval safeguard, not a relevance judgment.
    reserve = min(max(1, limit//5), limit)
    missing_title = [r for r in ordered if any(e["channel"] in ("missing_title", "medical_venue_missing_title") for e in r["retrieval_evidence"])]
    reserved = missing_title[:reserve]
    selected_keys = {r["record_key"] for r in reserved}
    for row in ordered:
        if len(selected_keys) >= limit: break
        selected_keys.add(row["record_key"])
    selected = [r for r in ordered if r["record_key"] in selected_keys]
    reserved_keys = {r["record_key"] for r in reserved}
    for rank, row in enumerate(selected, 1):
        row["rank"] = rank
        row["selection_reasons"].append("reciprocal_rank_fusion")
        if row["record_key"] in reserved_keys: row["selection_reasons"].append("missing_abstract_reserved")
    queue = []
    for row in ordered:
        if row["abstract_status"] != "present":
            queue.append({"record_key": row["record_key"], "paper_id": row["paper_id"], "source_paper_id": row["source_paper_id"], "title": row["title"],
                          "conference": row["conference"], "year": row["year"], "doi": row["doi"],
                          "paper_url": row["paper_url"], "pdf_url": row["pdf_url"],
                          "provenance": row["provenance"], "selected": row["record_key"] in selected_keys,
                          "reason": row["abstract_status"], "enrichment_status": "not_attempted"})
    coverage = {"exhaustive": False, "known_recall": None, "retrieved_union_records": len(pool),
                "returned_records": len(selected), "missing_abstract_in_union": len(queue),
                "queue_scope": "bounded_query_matching_union_not_all_corpus_missing_records",
                "returned_by_conference": dict(sorted(Counter(x["conference"] for x in selected).items())),
                "proceedings_completeness": "not_determined"}
    return {"schema_version": "lexical-search-v1", "status": "completed", "mode": "exploratory_local_lexical",
            "workflow_advanced": False, "index_id": manifest["index_id"], "database_sha256": manifest["database_sha256"],
            "snapshot_id": manifest["snapshot_id"], "snapshot_checksum": manifest["snapshot_checksum"],
            "source_corpus_reverified_at_search": False,
            "query_plan": plan, "filters": filters, "limit": limit, "per_channel": per_channel,
            "fusion": {"method": "rrf", "k": 60, "missing_title_reserved_slots": len(reserved)},
            "channel_audit": audits, "coverage": coverage,
            "warnings": ["No online search, semantic screening, abstract enrichment or fulltext reading performed.",
                         "No Gate was created or approved; S2/S3 completion is not claimed.",
                         "Index bytes verified. Source corpus was verified at build, not re-read for this search.",
                         "Duplicate title variants retained; metadata identifiers and links are not independently authenticated."],
            "candidates": selected, "missing_abstract_queue": queue}
