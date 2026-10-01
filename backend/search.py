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
PERSIAN_TRANSLATION = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک", "ة": "ه", "ۀ": "ه",
    "ؤ": "و", "إ": "ا", "أ": "ا", "ٱ": "ا",
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
})
SEARCH_STOPWORDS = {
    "از", "به", "با", "در", "برای", "و", "یا", "یک", "های", "این", "آن",
    "رو", "را", "که", "می", "shop", "store",
}
DIACRITICS = re.compile(r"[\u064b-\u065f\u0670\u06d6-\u06ed]")


def normalize_search(value):
    """Canonical form shared by indexing, retrieval, aliases, and analytics."""
    value = unicodedata.normalize("NFKC", value or "").lower()
    value = DIACRITICS.sub("", value).translate(PERSIAN_TRANSLATION)
    value = value.replace("\u200c", " ").replace("ـ", " ")
    return " ".join(re.sub(r"[^\w]+", " ", value).split())


def query_tokens(value):
    return [
        token for token in normalize_search(value).split()
        if len(token) > 1 and token not in SEARCH_STOPWORDS
    ]


def token_variants(token):
    variants = {token}
    for suffix in ("هایی", "های", "ها"):
        if token.endswith(suffix) and len(token) > len(suffix) + 2:
            variants.add(token[:-len(suffix)])
    return variants


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
        for word in words if min(len(word), len(term)) >= 3
    ):
        return 0.72
    if len(term) < 4:
        return 0.0
    similarity = max(
        (SequenceMatcher(None, term, word).ratio() for word in words
         if abs(len(word) - len(term)) <= 2),
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
            key=lambda item: item.get("search_score", 0)
            - penalty * segment_counts.get(str(item.get("category_code", ""))[:2], 0),
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

    changed = 0
    merchants = database.execute(
        """SELECT id,name,handle,city,description,biography
           FROM merchants ORDER BY id"""
    ).fetchall()
    for merchant in merchants:
        content = normalize_search(" ".join(
            part.strip()
            for part in (
                merchant["name"],
                merchant["handle"],
                merchant["city"],
                merchant["description"],
                merchant["biography"],
                category_labels.get(merchant["id"], ""),
            )
            if part and part.strip()
        ))
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        row = database.execute(
            """INSERT INTO search_documents
                 (merchant_id,entity_type,entity_id,content,content_hash)
               VALUES(%s,'merchant',%s,%s,%s)
               ON CONFLICT(entity_type,entity_id) DO UPDATE SET
                 merchant_id=excluded.merchant_id,
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
            (merchant["id"], merchant["id"], content, digest),
        ).fetchone()
        changed += int(row["needs_embedding"])
    post_rows=database.execute("""SELECT MIN(p.id) id,p.merchant_id,m.name,m.description,
      COALESCE(MAX(NULLIF(p.caption,'')),'') caption
      FROM merchant_posts p JOIN merchants m ON m.id=p.merchant_id
      GROUP BY p.merchant_id,m.name,m.description,COALESCE(p.collection_key,p.id::text)
      HAVING COALESCE(MAX(NULLIF(p.caption,'')),'')<>''""").fetchall()
    current_post_ids=[]
    for post in post_rows:
        current_post_ids.append(post["id"])
        content=normalize_search(" ".join(part for part in (post["name"],post["description"],category_labels.get(post["merchant_id"],""),post["caption"]) if part))
        digest=hashlib.sha256(content.encode("utf-8")).hexdigest()
        row=database.execute("""INSERT INTO search_documents(merchant_id,entity_type,entity_id,content,content_hash)
          VALUES(%s,'post',%s,%s,%s) ON CONFLICT(entity_type,entity_id) DO UPDATE SET
          merchant_id=excluded.merchant_id,content=excluded.content,content_hash=excluded.content_hash,
          embedding=CASE WHEN search_documents.content_hash=excluded.content_hash THEN search_documents.embedding ELSE NULL END,
          embedding_model=CASE WHEN search_documents.content_hash=excluded.content_hash THEN search_documents.embedding_model ELSE NULL END,
          embedded_at=CASE WHEN search_documents.content_hash=excluded.content_hash THEN search_documents.embedded_at ELSE NULL END,
          updated_at=CURRENT_TIMESTAMP RETURNING embedding IS NULL AS needs_embedding""",
          (post["merchant_id"],post["id"],content,digest)).fetchone()
        changed+=int(row["needs_embedding"])
    if current_post_ids:
        database.execute("DELETE FROM search_documents WHERE entity_type='post' AND NOT (entity_id=ANY(%s))",(current_post_ids,))
    else:
        database.execute("DELETE FROM search_documents WHERE entity_type='post'")
    return changed


def embed_pending_documents(database, limit=100):
    if not embedding_enabled():
        return 0
    rows = database.execute(
        """SELECT id,content FROM search_documents
           WHERE embedding IS NULL ORDER BY updated_at LIMIT %s""",
        (limit,),
    ).fetchall()
    vectors = embed_texts([row["content"] for row in rows])
    model = os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL)
    for row, vector in zip(rows, vectors):
        database.execute(
            """UPDATE search_documents
               SET embedding=%s::vector,embedding_model=%s,
                   embedded_at=CURRENT_TIMESTAMP
               WHERE id=%s""",
            (vector_literal(vector), model, row["id"]),
        )
    return len(rows)


def lexical_merchant_scores(database,query,limit=100):
    tokens=query_tokens(query)
    if not tokens:return {}
    prefix_query=" | ".join(f"'{token}':*" for token in tokens)
    normalized=normalize_search(query)
    return {row["merchant_id"]:float(row["score"]) for row in database.execute(
      """SELECT merchant_id,MAX(GREATEST(
           ts_rank_cd(search_vector,to_tsquery('simple',%s),32),
           word_similarity(%s,content),
           strict_word_similarity(%s,content))) score
         FROM search_documents
         WHERE search_vector @@ to_tsquery('simple',%s)
           OR word_similarity(%s,content)>=0.35
         GROUP BY merchant_id ORDER BY score DESC LIMIT %s""",
      (prefix_query,normalized,normalized,prefix_query,normalized,limit))}

def semantic_merchant_scores(database, query, limit=50):
    if not query or not embedding_enabled():
        return {}
    vector = vector_literal(embed_query(query))
    return {
        row["merchant_id"]: float(row["score"])
        for row in database.execute(
            """WITH candidates AS (
                 SELECT merchant_id,1-(embedding <=> %s::vector) score
                 FROM search_documents WHERE embedding IS NOT NULL
                 ORDER BY embedding <=> %s::vector LIMIT %s
               )
               SELECT merchant_id,MAX(score) score FROM candidates
               GROUP BY merchant_id ORDER BY score DESC LIMIT %s""",
            (vector, vector, limit * 4, limit),
        )
    }
