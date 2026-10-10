import hashlib

from backend.models.search import SearchEntityType
from backend.search.metadata import sync_search_metadata
from backend.search.normalization import normalize_search


def sync_search_index(database):
    """Refresh metadata before documents in the caller's transaction."""
    sync_search_metadata(database)
    return sync_search_documents(database)


def upsert_document(
    database, merchant_id, entity_type: SearchEntityType, entity_id, title, body, published_at=None
):
    content = f"{title} {body}".strip()
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    row = database.execute(
        """INSERT INTO search_documents(
             merchant_id,entity_type,entity_id,title_content,body_content,content,content_hash,published_at)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT(entity_type,entity_id) DO UPDATE SET
             merchant_id=excluded.merchant_id,title_content=excluded.title_content,
             body_content=excluded.body_content,content=excluded.content,
             content_hash=excluded.content_hash,published_at=excluded.published_at,
             embedding=CASE WHEN search_documents.content_hash=excluded.content_hash
               THEN search_documents.embedding ELSE NULL END,
             embedding_model=CASE WHEN search_documents.content_hash=excluded.content_hash
               THEN search_documents.embedding_model ELSE NULL END,
             embedded_at=CASE WHEN search_documents.content_hash=excluded.content_hash
               THEN search_documents.embedded_at ELSE NULL END,
             updated_at=CURRENT_TIMESTAMP
           RETURNING embedding IS NULL AS needs_embedding""",
        (merchant_id, entity_type, entity_id, title, body, content, digest, published_at),
    ).fetchone()
    return int(row["needs_embedding"])


def document_category_labels(database):
    category_labels = {}
    for row in database.execute(
        """SELECT mc.merchant_id, string_agg(c.label_fa, ' ') labels
           FROM merchant_categories mc
           JOIN categories c ON c.code=mc.category_code
           GROUP BY mc.merchant_id"""
    ):
        category_labels[row["merchant_id"]] = row["labels"]
    return category_labels


def document_search_terms(database):
    terms_by_merchant = {}
    for row in database.execute(
        """SELECT merchant_id,string_agg(term,' ') terms
           FROM merchant_search_terms GROUP BY merchant_id"""
    ):
        terms_by_merchant[row["merchant_id"]] = row["terms"]

    return terms_by_merchant


def normalized_content(*parts):
    return normalize_search(" ".join(part.strip() for part in parts if part and part.strip()))


def index_merchant(database, merchant, category_labels, terms_by_merchant):
    title_content = normalized_content(
        merchant["name"], merchant["handle"], category_labels.get(merchant["id"], "")
    )
    body_content = normalized_content(
        merchant["city"],
        merchant["description"],
        merchant["biography"],
        terms_by_merchant.get(merchant["id"], ""),
    )
    return upsert_document(
        database, merchant["id"], "merchant", merchant["id"], title_content, body_content
    )


def searchable_posts(database):
    return database.execute("""SELECT MIN(p.id) id,p.merchant_id,m.name,m.handle,
      m.description,COALESCE(MAX(NULLIF(p.caption,'')),'') caption,
      MAX(p.published_at) published_at
      FROM merchant_posts p JOIN merchants m ON m.id=p.merchant_id
      GROUP BY p.merchant_id,m.name,m.handle,m.description,
        p.collection_key
      HAVING COALESCE(MAX(NULLIF(p.caption,'')),'')<>''""").fetchall()


def index_post(database, post, category_labels):
    title_content = normalized_content(
        post["name"], post["handle"], category_labels.get(post["merchant_id"], "")
    )
    body_content = normalized_content(post["caption"])
    return upsert_document(
        database,
        post["merchant_id"],
        "post",
        post["id"],
        title_content,
        body_content,
        post["published_at"],
    )


def sync_search_documents(database):
    labels = document_category_labels(database)
    terms = document_search_terms(database)
    merchants = database.execute(
        "SELECT id,name,handle,city,description,biography FROM merchants ORDER BY id"
    )
    changed = sum(index_merchant(database, merchant, labels, terms) for merchant in merchants)
    posts = searchable_posts(database)
    changed += sum(index_post(database, post, labels) for post in posts)
    database.execute(
        "DELETE FROM search_documents WHERE entity_type='post' AND NOT (entity_id=ANY(%s))",
        ([post["id"] for post in posts],),
    )
    return changed
