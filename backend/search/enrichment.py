from backend.database import connect
from backend.models.search import Enrichment
from backend.search.indexing import sync_search_index
from backend.search.normalization import normalize_search


def save_llm_enrichment(merchant_id: int, enrichment: Enrichment):
    normalized_terms = {
        normalize_search(term): term.strip() for term in enrichment.terms if normalize_search(term)
    }
    with connect() as db:
        db.execute(
            """UPDATE merchants SET description=%s,description_source='llm',description_source_url=%s,
          description_generated_by=%s,description_updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
            (enrichment.description.strip(), enrichment.source_url, enrichment.model, merchant_id),
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
                (
                    merchant_id,
                    term,
                    normalized,
                    enrichment.source_url,
                    enrichment.model,
                    enrichment.confidence,
                ),
            )
        sync_search_index(db)
