from backend.search.normalization import query_tokens


def sync_search_metadata(db):
    for merchant in db.execute(
        "SELECT id,handle,category_code,description,description_source_url,biography,biography_source,instagram_url FROM merchants"
    ):
        db.execute(
            "DELETE FROM merchant_categories WHERE merchant_id=%s AND source='merchant_primary'",
            (merchant["id"],),
        )
        db.execute(
            """INSERT INTO merchant_categories(merchant_id,category_code,confidence,source,source_url)
            VALUES(%s,%s,1,'merchant_primary',%s) ON CONFLICT(merchant_id,category_code)
            DO UPDATE SET confidence=1,source='merchant_primary',source_url=excluded.source_url""",
            (merchant["id"], merchant["category_code"], merchant["description_source_url"]),
        )
        db.execute(
            "DELETE FROM merchant_search_terms WHERE merchant_id=%s AND source IN ('description','biography')",
            (merchant["id"],),
        )
        sources = (
            ("description", merchant["description"], 1.0, merchant["description_source_url"]),
            ("biography", merchant["biography"], 0.8, merchant["instagram_url"]),
        )
        for source, text, weight, source_url in sources:
            for term in set(query_tokens(text)):
                db.execute(
                    """INSERT INTO merchant_search_terms(merchant_id,term,normalized_term,weight,source,source_url,confidence)
                    VALUES(%s,%s,%s,%s,%s,%s,1) ON CONFLICT(merchant_id,normalized_term,source)
                    DO UPDATE SET term=excluded.term,weight=excluded.weight,source_url=excluded.source_url,updated_at=CURRENT_TIMESTAMP""",
                    (merchant["id"], term, term, weight, source, source_url),
                )
