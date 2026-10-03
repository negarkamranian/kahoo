import json
import os
from functools import lru_cache
from urllib.request import Request, urlopen

from backend.search.normalization import normalize_search

DEFAULT_MODEL = "BAAI/bge-m3"


VECTOR_DIMENSIONS = 1024


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
