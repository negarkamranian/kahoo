from backend.models.search import LexicalMatch
from backend.search.normalization import normalize_search, query_tokens

LEXICAL_MATCH_QUERY = """WITH matches AS (
           SELECT merchant_id,entity_type,entity_id,published_at,
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
           WHERE search_vector @@ to_tsquery('simple',%(prefix)s)
             OR word_similarity(%(phrase)s,title_content)>=0.28
             OR word_similarity(%(phrase)s,body_content)>=0.34
         ), ranked AS (
           SELECT *,ROW_NUMBER() OVER(PARTITION BY merchant_id ORDER BY score DESC) position
           FROM matches
         )
         SELECT merchant_id,entity_type,entity_id,published_at,score FROM ranked
         WHERE position=1 ORDER BY score DESC LIMIT %(limit)s"""


def lexical_merchant_matches(database, query, limit=150) -> dict[int, LexicalMatch]:
    tokens = query_tokens(query)
    if not tokens:
        return {}
    params = {
        "prefix": " | ".join(f"'{token}':*" for token in tokens),
        "phrase": normalize_search(query),
        "limit": limit,
    }
    rows = database.execute(LEXICAL_MATCH_QUERY, params)
    return {row["merchant_id"]: LexicalMatch.model_validate(row) for row in rows}
