"""Apply researched descriptions and search terms with an atomic audit trail."""

import hashlib
import json
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from backend.database import connect
from backend.models.search import BatchEnrichment, BatchEnrichmentResult, Enrichment
from backend.search.indexing import sync_search_index
from backend.search.normalization import normalize_search

MERCHANT_FIELDS = """id,handle,description,description_source,description_source_url,
    description_generated_by,description_updated_at"""


def normalized_search_terms(enrichment):
    return {normalize_search(term): term for term in enrichment.terms}


def enrichment_digest(enrichment):
    payload = enrichment.model_dump(mode="json")
    payload["terms"] = sorted(set(enrichment.terms))
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def enrichment_is_current(db, merchant, enrichment, normalized_terms, digest):
    history = db.execute(
        """SELECT payload_hash FROM merchant_enrichment_history
           WHERE merchant_id=%s ORDER BY id DESC LIMIT 1""",
        (merchant["id"],),
    ).fetchone()
    fields_match = (
        merchant["description"] == enrichment.description
        and merchant["description_source"] == "llm"
        and merchant["description_source_url"] == enrichment.source_url
        and merchant["description_generated_by"] == enrichment.model
    )
    if not history or history["payload_hash"] != digest or not fields_match:
        return False
    rows = db.execute(
        """SELECT normalized_term,term,source_url,generated_by,confidence,weight
           FROM merchant_search_terms WHERE merchant_id=%s AND source='llm'""",
        (merchant["id"],),
    ).fetchall()
    terms_match = {row["normalized_term"]: row["term"] for row in rows} == normalized_terms
    provenance_matches = all(
        row["source_url"] == enrichment.source_url
        and row["generated_by"] == enrichment.model
        and row["confidence"] == enrichment.confidence
        and row["weight"] == 1
        for row in rows
    )
    return terms_match and provenance_matches


def record_enrichment(db, merchant, enrichment, digest, researched_at):
    previous = {
        field: merchant[field]
        for field in ("description_source", "description_source_url", "description_generated_by")
    }
    previous["description_updated_at"] = (
        merchant["description_updated_at"].isoformat()
        if merchant["description_updated_at"]
        else None
    )
    payload = {
        "handle": merchant["handle"],
        "researched_at": researched_at.isoformat(),
        "enrichment": enrichment.model_dump(mode="json"),
    }
    db.execute(
        """INSERT INTO merchant_enrichment_history(
               merchant_id,researched_at,payload,payload_hash,previous_description,previous_provenance)
           VALUES(%s,%s,%s,%s,%s,%s)""",
        (
            merchant["id"],
            researched_at,
            Jsonb(payload),
            digest,
            merchant["description"],
            Jsonb(previous),
        ),
    )


def write_search_terms(db, merchant_id, enrichment, terms):
    db.execute(
        "DELETE FROM merchant_search_terms WHERE merchant_id=%s AND source='llm'",
        (merchant_id,),
    )
    for normalized, term in terms.items():
        db.execute(
            """INSERT INTO merchant_search_terms
              (merchant_id,term,normalized_term,weight,source,source_url,generated_by,confidence)
              VALUES(%s,%s,%s,1,'llm',%s,%s,%s)""",
            (
                merchant_id,
                term,
                normalized,
                enrichment.source_url,
                enrichment.model,
                enrichment.confidence,
            ),
        )


def apply_enrichment(db, merchant, enrichment, researched_at):
    terms = normalized_search_terms(enrichment)
    digest = enrichment_digest(enrichment)
    if enrichment_is_current(db, merchant, enrichment, terms, digest):
        return False
    record_enrichment(db, merchant, enrichment, digest, researched_at)
    db.execute(
        """UPDATE merchants SET description=%s,description_source='llm',description_source_url=%s,
          description_generated_by=%s,description_updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
        (enrichment.description, enrichment.source_url, enrichment.model, merchant["id"]),
    )
    write_search_terms(db, merchant["id"], enrichment, terms)
    return True


def save_llm_enrichment(merchant_id: int, enrichment: Enrichment):
    """Keep the single-merchant entrypoint; return whether a change was committed."""
    with connect() as db:
        merchant = db.execute(
            f"SELECT {MERCHANT_FIELDS} FROM merchants WHERE id=%s FOR UPDATE",
            (merchant_id,),
        ).fetchone()
        if merchant is None:
            raise ValueError(f"Merchant {merchant_id} does not exist")
        updated = apply_enrichment(db, merchant, enrichment, datetime.now(timezone.utc))
        if updated:
            sync_search_index(db)
    return updated


def ensure_current_research(db, merchants, researched_at):
    handles_by_id = {merchant["id"]: merchant["handle"] for merchant in merchants.values()}
    history = db.execute(
        """SELECT merchant_id,MAX(researched_at) researched_at FROM merchant_enrichment_history
           WHERE merchant_id=ANY(%s) GROUP BY merchant_id""",
        (list(handles_by_id),),
    ).fetchall()
    stale = sorted(
        handles_by_id[row["merchant_id"]] for row in history if row["researched_at"] > researched_at
    )
    if stale:
        raise ValueError(f"Stale research: newer enrichment exists for {', '.join(stale)}")


def save_batch_enrichment(batch: BatchEnrichment):
    """Resolve and lock every canonical handle before changing any merchant."""
    handles = [item.handle for item in batch.merchants]
    with connect() as db:
        rows = db.execute(
            f"SELECT {MERCHANT_FIELDS} FROM merchants WHERE handle=ANY(%s) ORDER BY id FOR UPDATE",
            (handles,),
        ).fetchall()
        merchants = {row["handle"]: row for row in rows}
        missing = sorted(set(handles) - merchants.keys())
        if missing:
            raise ValueError(f"Unknown merchant handles: {', '.join(missing)}")
        ensure_current_research(db, merchants, batch.researched_at)
        updated = sum(
            apply_enrichment(db, merchants[item.handle], item.enrichment, batch.researched_at)
            for item in batch.merchants
        )
        if updated:
            sync_search_index(db)
    return BatchEnrichmentResult(
        merchants=len(handles), updated=updated, unchanged=len(handles) - updated, handles=handles
    )
