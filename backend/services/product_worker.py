"""Leased PostgreSQL queue; model calls happen outside ingestion transactions."""

import logging
import uuid

from pydantic import ValidationError

from backend.config import settings
from backend.database import connect
from backend.services.product_vision import PIPELINE_VERSION, extract_product, vision_configured
from backend.services.products import enqueue_products, serialized_result
from backend.services.taxonomy import product_taxonomy

logger = logging.getLogger(__name__)


def claim_product():
    token = uuid.uuid4()
    with connect() as db:
        row = db.execute(
            """WITH candidate AS (
                 SELECT id FROM products WHERE
                   (status IN ('pending','failed') AND attempts<3 AND next_attempt_at<=CURRENT_TIMESTAMP)
                   OR (status='processing' AND started_at<CURRENT_TIMESTAMP-INTERVAL '30 minutes')
                 ORDER BY next_attempt_at,id FOR UPDATE SKIP LOCKED LIMIT 1
               )
               UPDATE products p SET status='processing',attempts=p.attempts+1,
                 claim_token=%s,started_at=CURRENT_TIMESTAMP,error=NULL,updated_at=CURRENT_TIMESTAMP
               FROM candidate c WHERE p.id=c.id RETURNING p.*""",
            (token,),
        ).fetchone()
        if not row:
            return None
        images = db.execute(
            "SELECT image_blob,mime_type FROM product_images WHERE product_id=%s ORDER BY position",
            (row["id"],),
        ).fetchall()
    return row, images, token


def finish_product(row, token, result, error):
    status = "failed" if error else ("ready" if result.category_code else "not_product")
    version = product_taxonomy().taxonomy.metadata.version
    with connect() as db:
        current = db.execute(
            "SELECT source_hash,claim_token FROM products WHERE id=%s FOR UPDATE", (row["id"],)
        ).fetchone()
        if not current:
            return "deleted"
        current_claim = (
            current["source_hash"] == row["source_hash"] and current["claim_token"] == token
        )
        audit_status = status if current_claim else "superseded"
        db.execute(
            """INSERT INTO product_enrichment_runs(product_id,source_hash,model,taxonomy_version,
               pipeline_version,status,result,error) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"],
                row["source_hash"],
                settings.product_vision_model,
                version,
                PIPELINE_VERSION,
                audit_status,
                serialized_result(result),
                error,
            ),
        )
        if current_claim:
            db.execute(
                """UPDATE products SET status=%s,result=%s,error=%s,model=%s,taxonomy_version=%s,
                   pipeline_version=%s,claim_token=NULL,processed_at=CURRENT_TIMESTAMP,
                   updated_at=CURRENT_TIMESTAMP,
                   next_attempt_at=CURRENT_TIMESTAMP+(%s*INTERVAL '30 seconds') WHERE id=%s""",
                (
                    status,
                    serialized_result(result),
                    error,
                    settings.product_vision_model,
                    version,
                    PIPELINE_VERSION,
                    2 ** min(row["attempts"], 5),
                    row["id"],
                ),
            )
    return audit_status


def process_next_product():
    if not vision_configured():
        raise ValueError("Configure PRODUCT_VISION_API_URL and PRODUCT_VISION_MODEL first")
    claim = claim_product()
    if not claim:
        return None
    row, images, token = claim
    result = None
    error = None
    try:
        result = extract_product(row["caption"], images)
    except ValidationError:
        error = "Vision output failed schema validation"
    except ValueError as failure:
        error = str(failure)[:500]
    except Exception as failure:  # pylint: disable=broad-exception-caught
        # A failed model job must not stop the queue.
        error = f"Product extraction failed ({type(failure).__name__})"
    return {"id": row["id"], "status": finish_product(row, token, result, error)}


def enqueue_existing_products():
    with connect() as db:
        return enqueue_products(db)


def run_product_worker(stop, poll_seconds=5):
    """Recover pending work after restarts and retry transient failures at most three times."""
    try:
        enqueue_existing_products()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Could not backfill the product queue")
    while not stop.is_set():
        try:
            result = process_next_product()
        except Exception:  # pylint: disable=broad-exception-caught
            logger.exception("Product queue unavailable; retrying on the next poll")
            result = None
        if result is None:
            stop.wait(poll_seconds)
