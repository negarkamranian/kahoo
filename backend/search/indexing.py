import hashlib

from backend.search.normalization import normalize_search


def upsert_document(database, merchant_id, entity_type, entity_id, title, body, published_at=None):
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
        changed += upsert_document(
            database, merchant["id"], "merchant", merchant["id"], title_content, body_content
        )
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
        changed += upsert_document(
            database,
            post["merchant_id"],
            "post",
            post["id"],
            title_content,
            body_content,
            post["published_at"],
        )
    if current_post_ids:
        database.execute(
            "DELETE FROM search_documents WHERE entity_type='post' AND NOT (entity_id=ANY(%s))",
            (current_post_ids,),
        )
    else:
        database.execute("DELETE FROM search_documents WHERE entity_type='post'")
    return changed
