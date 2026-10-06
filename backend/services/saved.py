"""Private guest collections backed by stable canonical catalog identities."""

from urllib.parse import quote

from backend.database import connect
from backend.models.saved import (
    SavedCollections,
    SavedImport,
    SavedImportResult,
    SavedMerchantView,
    SavedPostReference,
    SavedPostView,
)

MERCHANT_VIEWS = """SELECT m.id::text AS key,m.id,m.name,m.handle,m.description,
  CASE WHEN m.avatar_blob IS NOT NULL THEN '/api/avatars/' || m.id::text END AS avatar_url,
  m.instagram_url,m.city FROM saved_merchants s JOIN merchants m ON m.id=s.merchant_id
  WHERE s.owner_id=%s ORDER BY s.created_at DESC,m.id"""

POST_VIEWS = """SELECT s.collection_key AS key,s.merchant_id,m.name AS merchant_name,
  COALESCE(current.permalink,snapshot.permalink) AS permalink,
  COALESCE(current.image_url,snapshot.image_url) AS media_url,
  COALESCE(current.image_count,snapshot.image_count) AS image_count,
  (COALESCE(current.has_image,false) OR snapshot.image_blob IS NOT NULL) AS has_image
  FROM saved_posts s JOIN merchants m ON m.id=s.merchant_id
  JOIN saved_post_snapshots snapshot USING(merchant_id,collection_key)
  LEFT JOIN LATERAL (
    SELECT p.permalink,p.image_url,p.image_blob IS NOT NULL AS has_image,
      COUNT(*) OVER() AS image_count FROM merchant_posts p
    WHERE p.merchant_id=s.merchant_id AND p.collection_key=s.collection_key
    ORDER BY p.media_position,p.position,p.id LIMIT 1
  ) current ON true WHERE s.owner_id=%s
  ORDER BY s.created_at DESC,s.merchant_id,s.collection_key"""

CANONICAL_SNAPSHOT = """INSERT INTO saved_post_snapshots
  (merchant_id,collection_key,permalink,image_url,image_blob,mime_type,image_count)
  SELECT p.merchant_id,p.collection_key,p.permalink,p.image_url,p.image_blob,p.mime_type,
    COUNT(*) OVER() FROM merchant_posts p WHERE p.merchant_id=%s AND p.collection_key=%s
  ORDER BY p.media_position,p.position,p.id LIMIT 1
  ON CONFLICT(merchant_id,collection_key) DO NOTHING"""


def collection_media_url(merchant_id: int, key: str) -> str:
    return f"/api/saved/media/{merchant_id}/{quote(key, safe='')}"


def read_collections(db, owner_id: int) -> SavedCollections:
    merchants = [SavedMerchantView(**row) for row in db.execute(MERCHANT_VIEWS, (owner_id,))]
    posts = []
    for row in db.execute(POST_VIEWS, (owner_id,)):
        item = dict(row)
        if item.pop("has_image"):
            item["media_url"] = collection_media_url(item["merchant_id"], item["key"])
        posts.append(SavedPostView(**item))
    return SavedCollections(merchants=merchants, posts=posts)


def saved_collections(owner_id: int) -> SavedCollections:
    with connect() as db:
        return read_collections(db, owner_id)


def insert_saved_merchant(db, owner_id: int, merchant_id: int) -> bool:
    row = db.execute(
        """INSERT INTO saved_merchants(owner_id,merchant_id)
          SELECT %s,id FROM merchants WHERE id=%s ON CONFLICT DO NOTHING
          RETURNING merchant_id""",
        (owner_id, merchant_id),
    ).fetchone()
    if row:
        return True
    return bool(db.execute("SELECT id FROM merchants WHERE id=%s", (merchant_id,)).fetchone())


def save_merchant(owner_id: int, merchant_id: int) -> SavedCollections | None:
    with connect() as db:
        if not insert_saved_merchant(db, owner_id, merchant_id):
            return None
        return read_collections(db, owner_id)


def unsave_merchant(owner_id: int, merchant_id: int) -> SavedCollections:
    with connect() as db:
        db.execute(
            "DELETE FROM saved_merchants WHERE owner_id=%s AND merchant_id=%s",
            (owner_id, merchant_id),
        )
        return read_collections(db, owner_id)


def canonical_post(db, reference: SavedPostReference):
    if reference.merchant_id is not None and reference.key is not None:
        condition, params = (
            "merchant_id=%s AND collection_key=%s",
            (
                reference.merchant_id,
                reference.key,
            ),
        )
    else:
        condition, params = "permalink=%s", (reference.permalink,)
    return db.execute(
        f"""SELECT merchant_id,collection_key FROM merchant_posts WHERE {condition}
          UNION SELECT merchant_id,collection_key FROM saved_post_snapshots WHERE {condition}
          LIMIT 1""",
        (*params, *params),
    ).fetchone()


def insert_saved_post(db, owner_id: int, reference: SavedPostReference) -> bool:
    post = canonical_post(db, reference)
    if not post:
        return False
    params = (post["merchant_id"], post["collection_key"])
    db.execute(CANONICAL_SNAPSHOT, params)
    row = db.execute(
        """INSERT INTO saved_posts(owner_id,merchant_id,collection_key)
          SELECT %s,merchant_id,collection_key FROM saved_post_snapshots
          WHERE merchant_id=%s AND collection_key=%s
          ON CONFLICT(owner_id,merchant_id,collection_key)
          DO UPDATE SET owner_id=EXCLUDED.owner_id RETURNING merchant_id""",
        (owner_id, *params),
    ).fetchone()
    return bool(row)


def save_post(owner_id: int, merchant_id: int, key: str) -> SavedCollections | None:
    with connect() as db:
        reference = SavedPostReference(merchant_id=merchant_id, key=key)
        if not insert_saved_post(db, owner_id, reference):
            return None
        return read_collections(db, owner_id)


def unsave_post(owner_id: int, merchant_id: int, key: str) -> SavedCollections:
    with connect() as db:
        db.execute(
            """DELETE FROM saved_posts WHERE owner_id=%s
              AND merchant_id=%s AND collection_key=%s""",
            (owner_id, merchant_id, key),
        )
        return read_collections(db, owner_id)


def import_saved(owner_id: int, payload: SavedImport) -> SavedImportResult:
    """Commit the whole migration together and retain references we cannot resolve."""
    with connect() as db:
        skipped_merchants = [
            item for item in payload.merchants if not insert_saved_merchant(db, owner_id, item.id)
        ]
        skipped_posts = [
            item for item in payload.posts if not insert_saved_post(db, owner_id, item)
        ]
        collections = read_collections(db, owner_id)
    return SavedImportResult(
        **collections.model_dump(),
        skipped_merchants=skipped_merchants,
        skipped_posts=skipped_posts,
    )


def saved_media(owner_id: int, merchant_id: int, key: str):
    with connect() as db:
        return db.execute(
            """SELECT COALESCE(current.image_blob,snapshot.image_blob) AS image_blob,
              CASE WHEN current.image_blob IS NOT NULL THEN current.mime_type
                ELSE snapshot.mime_type END AS mime_type
              FROM saved_posts s JOIN saved_post_snapshots snapshot USING(merchant_id,collection_key)
              LEFT JOIN LATERAL (
                SELECT p.image_blob,p.mime_type FROM merchant_posts p
                WHERE p.merchant_id=s.merchant_id AND p.collection_key=s.collection_key
                ORDER BY p.media_position,p.position,p.id LIMIT 1
              ) current ON true
              WHERE s.owner_id=%s AND s.merchant_id=%s AND s.collection_key=%s""",
            (owner_id, merchant_id, key),
        ).fetchone()
