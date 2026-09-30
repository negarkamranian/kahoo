import hashlib
import json
import os
from urllib.request import Request, urlopen


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
    if any(len(vector) != VECTOR_DIMENSIONS for vector in vectors):
        raise ValueError(f"Embedding provider must return {VECTOR_DIMENSIONS} dimensions")
    return vectors


def vector_literal(vector):
    return "[" + ",".join(f"{value:.8g}" for value in vector) + "]"


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
        content = " ".join(
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
        )
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
        content=" ".join(part for part in (post["name"],post["description"],category_labels.get(post["merchant_id"],""),post["caption"]) if part)
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
    if not query:return {}
    return {row["merchant_id"]:float(row["score"]) for row in database.execute(
      """SELECT merchant_id,MAX(GREATEST(
           ts_rank_cd(search_vector,plainto_tsquery('simple',%s)),
           similarity(content,%s))) score
         FROM search_documents
         WHERE search_vector @@ plainto_tsquery('simple',%s) OR content %% %s
         GROUP BY merchant_id ORDER BY score DESC LIMIT %s""",
      (query,query,query,query,limit))}

def semantic_merchant_scores(database, query, limit=50):
    if not query or not embedding_enabled():
        return {}
    vector = vector_literal(embed_texts([query])[0])
    return {
        row["merchant_id"]: float(row["score"])
        for row in database.execute(
            """SELECT merchant_id,MAX(1-(embedding <=> %s::vector)) score
               FROM search_documents
               WHERE embedding IS NOT NULL
               GROUP BY merchant_id
               ORDER BY score DESC
               LIMIT %s""",
            (vector, limit),
        )
    }
