from backend.models.search import LexicalMatch
from backend.search.normalization import normalize_search, query_tokens
from backend.search.ranking import compact_query_match

LEXICAL_MATCH_QUERY = """WITH matches AS (
           SELECT merchant_id,entity_type,entity_id,published_at,content,
             (SELECT AVG(CASE WHEN search_vector @@ to_tsquery('simple', token || ':*')
                OR (length(token)>=4 AND strict_word_similarity(token,content)>=0.65)
               THEN 1.0 ELSE 0.0 END) FROM unnest(%(tokens)s::text[]) token) coverage,
             GREATEST(
               4*ts_rank_cd(ARRAY[0.1,0.2,0.6,1.0]::real[],search_vector,
                 to_tsquery('simple',%(prefix)s),32),
               1.15*word_similarity(%(phrase)s,title_content),
               word_similarity(%(phrase)s,body_content),
               strict_word_similarity(%(phrase)s,content)
             )
             + CASE WHEN STRPOS(title_content,%(phrase)s)>0 THEN 0.7
                    WHEN STRPOS(body_content,%(phrase)s)>0 THEN 0.35 ELSE 0 END
             + CASE WHEN entity_type='post' AND published_at IS NOT NULL
                    THEN 0.08/(1+GREATEST(0,EXTRACT(EPOCH FROM
                      (CURRENT_TIMESTAMP-published_at))/15552000)) ELSE 0 END score
           FROM search_documents
           WHERE (%(merchant_ids)s::bigint[] IS NULL OR merchant_id=ANY(%(merchant_ids)s))
             AND (search_vector @@ to_tsquery('simple',%(prefix)s)
             OR word_similarity(%(phrase)s,title_content)>=0.28
             OR word_similarity(%(phrase)s,body_content)>=0.34)
         ), ranked AS (
           SELECT *,ROW_NUMBER() OVER(PARTITION BY merchant_id ORDER BY coverage DESC,score DESC) position
           FROM matches
         )
         SELECT merchant_id,entity_type,entity_id,published_at,score,coverage,content FROM ranked
         WHERE position=1 ORDER BY coverage DESC,score DESC LIMIT %(limit)s"""


def lexical_merchant_matches(
    database, query, limit=150, *, merchant_ids=None
) -> dict[int, LexicalMatch]:
    tokens = query_tokens(query)
    if not tokens:
        return {}
    params = {
        "prefix": " | ".join(f"'{token}':*" for token in tokens),
        "tokens": tokens,
        "merchant_ids": merchant_ids,
        "phrase": normalize_search(query),
        "limit": limit,
    }
    rows = database.execute(LEXICAL_MATCH_QUERY, params)
    return {
        row["merchant_id"]: LexicalMatch.model_validate(
            {**row, "coherent": compact_query_match(tokens, row["content"])}
        )
        for row in rows
    }
