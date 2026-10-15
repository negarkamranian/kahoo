"""Search indexing and enrichment commands."""

from backend.database import connect
from backend.models.search import (
    BatchEnrichment,
    Enrichment,
    EnrichmentResult,
    ReindexResult,
)
from backend.search.embeddings import embed_pending_documents
from backend.search.enrichment import save_batch_enrichment, save_llm_enrichment
from backend.search.indexing import sync_search_index


def reindex(args):
    with connect() as db:
        pending = sync_search_index(db)
    embedded = 0
    while True:
        with connect() as db:
            batch = embed_pending_documents(db, args.batch_size)
        embedded += batch
        if not args.all or batch < args.batch_size:
            break
    return ReindexResult(pending_documents=pending, embedded=embedded)


def enrich(args):
    enrichment = Enrichment.model_validate_json(args.source.read_bytes())
    updated = save_llm_enrichment(args.merchant_id, enrichment)
    return EnrichmentResult(merchant_id=args.merchant_id, updated=updated)


def enrich_file(args):
    batch = BatchEnrichment.model_validate_json(args.source.read_bytes())
    return save_batch_enrichment(batch)
