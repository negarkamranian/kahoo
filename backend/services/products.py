"""Durable product snapshots, queue operations, and admin assessment."""

import hashlib
import json
from collections import defaultdict

from psycopg.types.json import Jsonb

from backend.database import connect
from backend.models.products import AdminProduct, ProductPage
from backend.services.product_vision import vision_configured

PRODUCT_COLUMNS = "p.*,m.name merchant_name,m.handle merchant_handle"


def source_hash(caption, images):
    digest = hashlib.sha256(caption.encode())
    for image in images:
        digest.update(str(image["media_position"]).encode())
        digest.update(hashlib.sha256(bytes(image["image_blob"])).digest())
    return digest.hexdigest()


def enqueue_products(db, merchant_id=None):
    """Snapshot each collection atomically with ingestion; unchanged evidence keeps its result."""
    rows = db.execute(
        """SELECT merchant_id,collection_key,caption,permalink,media_position,
           image_url,image_blob,mime_type FROM merchant_posts
           WHERE image_blob IS NOT NULL AND mime_type IS NOT NULL
             AND (%s::bigint IS NULL OR merchant_id=%s)
           ORDER BY merchant_id,collection_key,media_position,id""",
        (merchant_id, merchant_id),
    )
    groups = defaultdict(list)
    for row in rows:
        groups[(row["merchant_id"], row["collection_key"])].append(row)
    for images in groups.values():
        snapshot_product(db, images)
    return len(groups)


def snapshot_product(db, images):
    first = images[0]
    fingerprint = source_hash(first["caption"], images)
    row = db.execute(
        """INSERT INTO products(merchant_id,collection_key,caption,permalink,source_hash)
           VALUES(%s,%s,%s,%s,%s)
           ON CONFLICT(merchant_id,collection_key) DO UPDATE SET
             caption=excluded.caption,permalink=excluded.permalink,
             source_hash=excluded.source_hash,updated_at=CURRENT_TIMESTAMP
           RETURNING id""",
        (
            first["merchant_id"],
            first["collection_key"],
            first["caption"],
            first["permalink"],
            fingerprint,
        ),
    ).fetchone()
    # The migration trigger resets stale classifications only when the evidence changes.
    db.execute("DELETE FROM product_images WHERE product_id=%s", (row["id"],))
    for position, image in enumerate(images, 1):
        db.execute(
            """INSERT INTO product_images(product_id,position,source_url,image_blob,mime_type)
               VALUES(%s,%s,%s,%s,%s)""",
            (row["id"], position, image["image_url"], image["image_blob"], image["mime_type"]),
        )


def product_images(db, product_id):
    return db.execute(
        "SELECT position FROM product_images WHERE product_id=%s ORDER BY position", (product_id,)
    ).fetchall()


def admin_product(db, row):
    images = [
        {
            "position": image["position"],
            "media_url": f"/api/admin/products/{row['id']}/images/{image['position']}",
        }
        for image in product_images(db, row["id"])
    ]
    return AdminProduct.model_validate({**row, "images": images})


def list_products(status=None, review=None, query="", limit=50, offset=0):
    filters = """(%s::text IS NULL OR p.status=%s)
        AND (%s::text IS NULL OR p.review_status=%s)
        AND (%s='' OR m.handle ILIKE %s OR m.name ILIKE %s
             OR p.caption ILIKE %s OR p.result->>'title' ILIKE %s)"""
    pattern = f"%{query}%"
    params = (status, status, review, review, query, pattern, pattern, pattern, pattern)
    with connect() as db:
        total = db.execute(
            f"SELECT COUNT(*) total FROM products p JOIN merchants m ON m.id=p.merchant_id "
            f"WHERE {filters}",
            params,
        ).fetchone()["total"]
        rows = db.execute(
            f"SELECT {PRODUCT_COLUMNS} FROM products p JOIN merchants m ON m.id=p.merchant_id "
            f"WHERE {filters} ORDER BY p.id DESC LIMIT %s OFFSET %s",
            (*params, limit, offset),
        ).fetchall()
        items = [admin_product(db, row) for row in rows]
    return ProductPage(
        items=items, total=total, limit=limit, offset=offset, configured=vision_configured()
    )


def get_product(product_id):
    with connect() as db:
        row = db.execute(
            f"SELECT {PRODUCT_COLUMNS} FROM products p JOIN merchants m ON m.id=p.merchant_id "
            "WHERE p.id=%s",
            (product_id,),
        ).fetchone()
        return admin_product(db, row) if row else None


def get_product_image(product_id, position):
    with connect() as db:
        return db.execute(
            "SELECT image_blob,mime_type FROM product_images WHERE product_id=%s AND position=%s",
            (product_id, position),
        ).fetchone()


def review_product(product_id, review):
    with connect() as db:
        row = db.execute(
            """UPDATE products SET review_status=%s,review_note=%s,
               reviewed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
               WHERE id=%s AND status IN ('ready','not_product') RETURNING id""",
            (review.status, review.note, product_id),
        ).fetchone()
    return bool(row)


def retry_product(product_id):
    with connect() as db:
        row = db.execute(
            """UPDATE products SET status='pending',attempts=0,error=NULL,claim_token=NULL,
               result=NULL,processed_at=NULL,review_status='pending',review_note='',reviewed_at=NULL,
               model=NULL,taxonomy_version=NULL,pipeline_version=NULL,started_at=NULL,
               next_attempt_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP
               WHERE id=%s AND status!='processing' RETURNING id""",
            (product_id,),
        ).fetchone()
    return bool(row)


def product_history(product_id):
    with connect() as db:
        return db.execute(
            """SELECT id,source_hash,model,taxonomy_version,pipeline_version,status,result,error,
               created_at FROM product_enrichment_runs WHERE product_id=%s ORDER BY id DESC LIMIT 50""",
            (product_id,),
        ).fetchall()


def serialized_result(result):
    return Jsonb(json.loads(result.model_dump_json())) if result else None
