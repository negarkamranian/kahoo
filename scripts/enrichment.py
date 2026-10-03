from backend.database import connect
from backend.search.indexing import sync_search_documents
from backend.search.metadata import sync_search_metadata
from backend.search.normalization import normalize_search


def save_llm_enrichment(merchant_id, description, terms, model, source_url, confidence=0.75):
    if not model or not source_url:
        raise ValueError("LLM enrichment requires both model and source_url provenance")
    normalized_terms = {
        normalize_search(term): term.strip() for term in terms if normalize_search(term)
    }
    with connect() as db:
        db.execute(
            """UPDATE merchants SET description=%s,description_source='llm',description_source_url=%s,
          description_generated_by=%s,description_updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
            (description.strip(), source_url, model, merchant_id),
        )
        db.execute(
            "DELETE FROM merchant_search_terms WHERE merchant_id=%s AND source='llm'",
            (merchant_id,),
        )
        for normalized, term in normalized_terms.items():
            db.execute(
                """INSERT INTO merchant_search_terms
              (merchant_id,term,normalized_term,weight,source,source_url,generated_by,confidence)
              VALUES(%s,%s,%s,1,'llm',%s,%s,%s)""",
                (merchant_id, term, normalized, source_url, model, max(0, min(1, confidence))),
            )
        sync_search_metadata(db)
        sync_search_documents(db)


def apply(args):
    import json

    payload = json.loads(args.source.read_text(encoding="utf-8"))
    required = {"description", "terms", "model", "source_url"}
    if not isinstance(payload, dict) or required - payload.keys():
        raise ValueError("enrichment JSON needs description, terms, model and source_url")
    save_llm_enrichment(
        args.merchant_id,
        payload["description"],
        payload["terms"],
        payload["model"],
        payload["source_url"],
        payload.get("confidence", 0.75),
    )
    return {"merchant_id": args.merchant_id, "updated": True}
