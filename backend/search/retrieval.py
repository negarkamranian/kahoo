from backend.search.normalization import normalize_search, query_tokens


def lexical_merchant_matches(database, query, limit=150):
    tokens = query_tokens(query)
    if not tokens:
        return {}
    prefix_query = " | ".join(f"'{token}':*" for token in tokens)
    normalized = normalize_search(query)
    rows = database.execute(
        """WITH matches AS (
           SELECT merchant_id,entity_type,entity_id,published_at,
             GREATEST(
               4*ts_rank_cd(ARRAY[0.1,0.2,0.6,1.0]::real[],search_vector,
                 to_tsquery('simple',%s),32),
               1.15*word_similarity(%s,title_content),
               word_similarity(%s,body_content),
               strict_word_similarity(%s,content)
             )
             + CASE WHEN STRPOS(title_content,%s)>0 THEN 0.7
                    WHEN STRPOS(body_content,%s)>0 THEN 0.35 ELSE 0 END
             + CASE WHEN entity_type='post' AND published_at IS NOT NULL
                    THEN 0.08/(1+GREATEST(0,EXTRACT(EPOCH FROM
                      (CURRENT_TIMESTAMP-published_at))/15552000)) ELSE 0 END score
           FROM search_documents
           WHERE search_vector @@ to_tsquery('simple',%s)
             OR word_similarity(%s,title_content)>=0.28
             OR word_similarity(%s,body_content)>=0.34
         ), ranked AS (
           SELECT *,ROW_NUMBER() OVER(PARTITION BY merchant_id ORDER BY score DESC) position
           FROM matches
         )
         SELECT merchant_id,entity_type,entity_id,published_at,score FROM ranked
         WHERE position=1 ORDER BY score DESC LIMIT %s""",
        (
            prefix_query,
            normalized,
            normalized,
            normalized,
            normalized,
            normalized,
            prefix_query,
            normalized,
            normalized,
            limit,
        ),
    )
    return {
        row["merchant_id"]: {
            "score": float(row["score"]),
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "published_at": row["published_at"],
        }
        for row in rows
    }
