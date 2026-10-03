import hashlib
import json
import math
import os
import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache
from urllib.request import Request, urlopen

DEFAULT_MODEL = "BAAI/bge-m3"
VECTOR_DIMENSIONS = 1024
PERSIAN_TRANSLATION = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "ؤ": "و",
        "إ": "ا",
        "أ": "ا",
        "ٱ": "ا",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
    }
)
SEARCH_STOPWORDS = {
    "از",
    "به",
    "با",
    "در",
    "برای",
    "و",
    "یا",
    "یک",
    "های",
    "این",
    "آن",
    "رو",
    "را",
    "که",
    "می",
    "shop",
    "store",
}
PERSIAN_SUFFIXES = ("ترین", "تر", "هایی", "های", "ها")
DIACRITICS = re.compile(r"[\u064b-\u065f\u0670\u06d6-\u06ed]")


def normalize_search(value):
    """Canonical form shared by indexing, retrieval, aliases, and analytics."""
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = DIACRITICS.sub("", value).translate(PERSIAN_TRANSLATION)
    value = value.replace("\u200c", " ").replace("ـ", " ")
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def query_tokens(value):
    return [
        token
        for token in normalize_search(value).split()
        if len(token) > 1 and token not in SEARCH_STOPWORDS
    ]


def token_variants(token):
    variants = {token}
    for suffix in PERSIAN_SUFFIXES:
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            variants.add(token[: -len(suffix)])
    return variants


def query_coverage(tokens, *texts):
    """Fraction of meaningful query tokens matched by any searchable field."""
    if not tokens:
        return 0.0
    return sum(
        any(term_match_strength(token, text) > 0 for text in texts) for token in tokens
    ) / len(tokens)


def phrase_proximity_bonus(phrase, text):
    """Reward exact phrases and compact ordered matches without overmatching."""
    phrase = normalize_search(phrase)
    text = normalize_search(text)
    if not phrase or not text:
        return 0.0
    if f" {phrase} " in f" {text} ":
        return 1.0
    tokens = query_tokens(phrase)
    words = text.split()
    if len(tokens) < 2:
        return 0.0
    positions = []
    start = -1
    for token in tokens:
        matches = [
            index
            for index, word in enumerate(words)
            if index > start and term_match_strength(token, word) >= 0.7
        ]
        if not matches:
            return 0.0
        start = matches[0]
        positions.append(start)
    span = positions[-1] - positions[0] + 1
    return max(0.0, 0.8 - 0.1 * max(0, span - len(tokens)))


def term_match_strength(term, text):
    """Return 0..1 for exact, prefix, or conservative typo-tolerant matching."""
    term = normalize_search(term)
    text = normalize_search(text)
    if not term or not text:
        return 0.0
    if f" {term} " in f" {text} ":
        return 1.0
    if " " in term:
        return 0.0
    words = text.split()
    variants = token_variants(term)
    if any(variant in words for variant in variants):
        return 1.0
    if len(term) >= 3 and any(
        word.startswith(term) or term.startswith(word)
        for word in words
        if min(len(word), len(term)) >= 3
    ):
        return 0.72
    if len(term) < 4:
        return 0.0
    similarity = max(
        (
            SequenceMatcher(None, term, word).ratio()
            for word in words
            if abs(len(word) - len(term)) <= 2
        ),
        default=0.0,
    )
    return 0.55 if similarity >= 0.78 else 0.0


def reciprocal_rank_fusion(*rankings, k=60):
    """Fuse score dictionaries without comparing their incompatible scales."""
    fused = {}
    for ranking in rankings:
        ordered = sorted(ranking, key=ranking.get, reverse=True)
        for rank, merchant_id in enumerate(ordered, 1):
            fused[merchant_id] = fused.get(merchant_id, 0.0) + 1 / (k + rank)
    return fused


def discounted_cumulative_gain(relevances, limit=10):
    return sum(
        (2**relevance - 1) / math.log2(rank + 2)
        for rank, relevance in enumerate(relevances[:limit])
    )


def ndcg_at_k(relevances, ideal_relevances=None, limit=10):
    ideal = sorted(ideal_relevances or relevances, reverse=True)
    denominator = discounted_cumulative_gain(ideal, limit)
    return discounted_cumulative_gain(relevances, limit) / denominator if denominator else 0.0


def merchant_quality_score(merchant, clicks=0):
    """Small, bounded tie-breaker for browse/recommendation quality."""
    followers = max(0, int(merchant.get("followers_count") or 0))
    media = max(0, int(merchant.get("media_count") or 0))
    return (
        min(math.log1p(followers) / 3.0, 4.8)
        + min(math.log1p(media) / 6.0, 1.6)
        + min(math.log1p(max(0, clicks)) / 4.0, 1.0)
        + (0.35 if merchant.get("avatar_source_url") else 0)
        + (0.25 if merchant.get("biography") else 0)
        + (0.2 if merchant.get("verified") else 0)
    )


def diversify_results(items, penalty=0.85):
    """Greedy re-rank that prevents one catalog segment monopolizing browse."""
    remaining = list(items)
    output = []
    segment_counts = {}
    while remaining:
        best = max(
            remaining,
            key=lambda item: (
                item.get("search_score", 0)
                - penalty * segment_counts.get(str(item.get("category_code", ""))[:2], 0)
            ),
        )
        remaining.remove(best)
        output.append(best)
        segment = str(best.get("category_code", ""))[:2]
        segment_counts[segment] = segment_counts.get(segment, 0) + 1
    return output


def embedding_enabled():
    return bool(os.environ.get("EMBEDDING_API_URL"))


def embed_texts(texts):
    if not texts:
        return []
    endpoint = os.environ["EMBEDDING_API_URL"]
    model = os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL)
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("EMBEDDING_API_KEY")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(endpoint, data=payload, headers=headers), timeout=60) as response:
        result = json.load(response)
    vectors = [item["embedding"] for item in sorted(result["data"], key=lambda item: item["index"])]
    if len(vectors) != len(texts):
        raise ValueError("Embedding provider must return one vector per input")
    if any(len(vector) != VECTOR_DIMENSIONS for vector in vectors):
        raise ValueError(f"Embedding provider must return {VECTOR_DIMENSIONS} dimensions")
    return vectors


def vector_literal(vector):
    return "[" + ",".join(f"{value:.8g}" for value in vector) + "]"


@lru_cache(maxsize=512)
def embed_query(query):
    """Cache repeated normalized query vectors across search-as-you-type calls."""
    return tuple(embed_texts([normalize_search(query)])[0])


def sync_search_documents(database):
    category_labels = {}
    for row in database.execute(
        """SELECT mc.merchant_id, string_agg(c.label_fa, ' ') labels
           FROM merchant_categories mc
           JOIN categories c ON c.code=mc.category_code
           GROUP BY mc.merchant_id"""
    ):
        category_labels[row["merchant_id"]] = row["labels"]
    terms_by_merchant = {}
    for row in database.execute(
        """SELECT merchant_id,string_agg(term,' ') terms
           FROM merchant_search_terms GROUP BY merchant_id"""
    ):
        terms_by_merchant[row["merchant_id"]] = row["terms"]

    changed = 0
    merchants = database.execute(
        """SELECT id,name,handle,city,description,biography
           FROM merchants ORDER BY id"""
    ).fetchall()
    for merchant in merchants:
        title_content = normalize_search(
            " ".join(
                part.strip()
                for part in (
                    merchant["name"],
                    merchant["handle"],
                    category_labels.get(merchant["id"], ""),
                )
                if part and part.strip()
            )
        )
        body_content = normalize_search(
            " ".join(
                part.strip()
                for part in (
                    merchant["city"],
                    merchant["description"],
                    merchant["biography"],
                    terms_by_merchant.get(merchant["id"], ""),
                )
                if part and part.strip()
            )
        )
        content = f"{title_content} {body_content}".strip()
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        row = database.execute(
            """INSERT INTO search_documents
                 (merchant_id,entity_type,entity_id,title_content,body_content,content,content_hash)
               VALUES(%s,'merchant',%s,%s,%s,%s,%s)
               ON CONFLICT(entity_type,entity_id) DO UPDATE SET
                 merchant_id=excluded.merchant_id,
                 title_content=excluded.title_content,
                 body_content=excluded.body_content,
                 content=excluded.content,
                 content_hash=excluded.content_hash,
                 embedding=CASE
                   WHEN search_documents.content_hash=excluded.content_hash
                   THEN search_documents.embedding ELSE NULL END,
                 embedding_model=CASE
                   WHEN search_documents.content_hash=excluded.content_hash
                   THEN search_documents.embedding_model ELSE NULL END,
                 embedded_at=CASE
                   WHEN search_documents.content_hash=excluded.content_hash
                   THEN search_documents.embedded_at ELSE NULL END,
                 updated_at=CURRENT_TIMESTAMP
               RETURNING embedding IS NULL AS needs_embedding""",
            (merchant["id"], merchant["id"], title_content, body_content, content, digest),
        ).fetchone()
        changed += int(row["needs_embedding"])
    post_rows = database.execute("""SELECT MIN(p.id) id,p.merchant_id,m.name,m.handle,
      m.description,COALESCE(MAX(NULLIF(p.caption,'')),'') caption,
      MAX(p.published_at) published_at
      FROM merchant_posts p JOIN merchants m ON m.id=p.merchant_id
      GROUP BY p.merchant_id,m.name,m.handle,m.description,
        COALESCE(p.collection_key,p.id::text)
      HAVING COALESCE(MAX(NULLIF(p.caption,'')),'')<>''""").fetchall()
    current_post_ids = []
    for post in post_rows:
        current_post_ids.append(post["id"])
        title_content = normalize_search(
            " ".join(
                part
                for part in (
                    post["name"],
                    post["handle"],
                    category_labels.get(post["merchant_id"], ""),
                )
                if part
            )
        )
        body_content = normalize_search(
            " ".join(part for part in (post["description"], post["caption"]) if part)
        )
        content = f"{title_content} {body_content}".strip()
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        row = database.execute(
            """INSERT INTO search_documents(merchant_id,entity_type,
          entity_id,title_content,body_content,content,content_hash,published_at)
          VALUES(%s,'post',%s,%s,%s,%s,%s,%s) ON CONFLICT(entity_type,entity_id) DO UPDATE SET
          merchant_id=excluded.merchant_id,title_content=excluded.title_content,
          body_content=excluded.body_content,content=excluded.content,
          content_hash=excluded.content_hash,published_at=excluded.published_at,
          embedding=CASE WHEN search_documents.content_hash=excluded.content_hash THEN search_documents.embedding ELSE NULL END,
          embedding_model=CASE WHEN search_documents.content_hash=excluded.content_hash THEN search_documents.embedding_model ELSE NULL END,
          embedded_at=CASE WHEN search_documents.content_hash=excluded.content_hash THEN search_documents.embedded_at ELSE NULL END,
          updated_at=CURRENT_TIMESTAMP RETURNING embedding IS NULL AS needs_embedding""",
            (
                post["merchant_id"],
                post["id"],
                title_content,
                body_content,
                content,
                digest,
                post["published_at"],
            ),
        ).fetchone()
        changed += int(row["needs_embedding"])
    if current_post_ids:
        database.execute(
            "DELETE FROM search_documents WHERE entity_type='post' AND NOT (entity_id=ANY(%s))",
            (current_post_ids,),
        )
    else:
        database.execute("DELETE FROM search_documents WHERE entity_type='post'")
    return changed


def embed_pending_documents(database, limit=100):
    if not embedding_enabled():
        return 0
    model = os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL)
    rows = database.execute(
        """SELECT id,content FROM search_documents
           WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM %s
           ORDER BY updated_at LIMIT %s""",
        (model, limit),
    ).fetchall()
    vectors = embed_texts([row["content"] for row in rows])
    for row, vector in zip(rows, vectors):
        database.execute(
            """UPDATE search_documents
               SET embedding=%s::vector,embedding_model=%s,
                   embedded_at=CURRENT_TIMESTAMP
               WHERE id=%s""",
            (vector_literal(vector), model, row["id"]),
        )
    return len(rows)


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


def lexical_merchant_scores(database, query, limit=150):
    return {
        merchant_id: match["score"]
        for merchant_id, match in lexical_merchant_matches(database, query, limit).items()
    }


def semantic_merchant_scores(database, query, limit=50):
    if not query or not embedding_enabled():
        return {}
    vector = vector_literal(embed_query(query))
    return {
        row["merchant_id"]: float(row["score"])
        for row in database.execute(
            """WITH candidates AS (
                 SELECT set_config('hnsw.iterative_scan','relaxed_order',true)
               ), nearest AS (
                 SELECT merchant_id,1-(embedding <=> %s::vector) score
                 FROM search_documents,candidates WHERE embedding IS NOT NULL
                 ORDER BY embedding <=> %s::vector LIMIT %s
               )
               SELECT merchant_id,MAX(score) score FROM nearest
               GROUP BY merchant_id ORDER BY score DESC LIMIT %s""",
            (vector, vector, limit * 4, limit),
        )
    }
