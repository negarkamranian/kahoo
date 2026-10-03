from pathlib import Path

from pydantic import TypeAdapter

from backend.config import PROJECT_ROOT
from backend.database import connect
from backend.instagram_urls import profile_url
from backend.models.catalog import CatalogImportResult, CatalogMerchant, MerchantCatalog
from backend.search.indexing import sync_search_index

DATA_ROOT = PROJECT_ROOT / "data"


def merchant_catalog_paths(data_root: Path):
    paths = [
        data_root / "merchant_catalog.json",
        *sorted(data_root.glob("merchant_catalog_expansion_*.json")),
    ]
    shared = data_root / "merchant_catalog_shared.json"
    if shared.exists():
        paths.append(shared)
    return paths


def load_merchant_catalog(path: Path) -> MerchantCatalog:
    return MerchantCatalog.model_validate_json(path.read_bytes())


def load_merchant_catalogs(paths) -> MerchantCatalog:
    shards = [load_merchant_catalog(path) for path in paths]
    return MerchantCatalog(
        snapshot_at=max(shard.snapshot_at for shard in shards),
        merchants=[
            merchant.model_copy(update={"snapshot_at": shard.snapshot_at})
            for shard in shards
            for merchant in shard.merchants
        ],
    )


def update_catalog_details(db, merchant_id, item):
    if not item.is_new:
        return
    db.execute(
        """UPDATE merchants SET
          name=CASE WHEN description_source='user_submitted_profile_url'
            AND biography_source IS NOT NULL THEN name ELSE %s END,
          description=CASE WHEN description_source='llm' THEN description ELSE %s END,
          description_source=CASE WHEN description_source='llm' THEN description_source ELSE %s END,
          description_source_url=CASE WHEN description_source='llm' THEN description_source_url ELSE %s END,
          category_code=%s,city=%s,source_url=%s,updated_label='داده عمومی'
          WHERE id=%s""",
        (
            item.name,
            item.description,
            item.description_source,
            item.source_url,
            item.category_code,
            item.city,
            item.source_url,
            merchant_id,
        ),
    )


def create_catalog_merchant(db, item):
    item.require_details()
    username = item.handle[1:]
    name = item.name
    source_url = item.source_url
    cursor = db.execute(
        """INSERT INTO merchants(
          instagram_id,name,handle,description,description_source,
          description_source_url,description_updated_at,source_url,
          category_code,city,instagram_url,
          updated_label,verified,followers_count,media_count,
          metrics_source,metrics_source_url,metrics_updated_at)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s, %s,%s,%s,'داده عمومی',0,%s,%s,
            %s,%s,%s) RETURNING id""",
        (
            f"catalog_{username}",
            name,
            item.handle,
            item.description,
            item.description_source,
            source_url,
            item.snapshot_at,
            source_url,
            item.category_code,
            item.city,
            profile_url(item.handle),
            item.followers_count,
            item.media_count,
            item.metrics_source,
            item.metrics_source_url,
            item.snapshot_at,
        ),
    )
    return cursor.fetchone()["id"]


def save_catalog_biography(db, merchant_id, item):
    if item.biography:
        db.execute(
            """UPDATE merchants SET biography=%s,biography_source=%s,
            biography_updated_at=CURRENT_TIMESTAMP
            WHERE id=%s AND biography_source IS NULL""",
            (item.biography, item.biography_source, merchant_id),
        )


def save_catalog_categories(db, merchant_id, item):
    if "category_codes" in item.model_fields_set:
        db.execute(
            "DELETE FROM merchant_categories WHERE merchant_id=%s AND source='curated_catalog'",
            (merchant_id,),
        )
        for code in item.category_codes:
            if code == item.category_code:
                continue
            db.execute(
                """INSERT INTO merchant_categories(merchant_id,category_code,confidence,source,source_url)
                VALUES(%s,%s,0.9,'curated_catalog',%s)
                ON CONFLICT(merchant_id,category_code) DO NOTHING""",
                (merchant_id, code, item.source_url),
            )


def save_catalog_metrics(db, merchant_id, item):
    if item.metrics_source_url:
        db.execute(
            """UPDATE merchants SET
              followers_count=COALESCE(%s,followers_count),
              media_count=COALESCE(%s,media_count),
              metrics_source=%s,
              metrics_source_url=%s,metrics_updated_at=%s
              WHERE id=%s AND (metrics_updated_at IS NULL OR metrics_updated_at<=%s)""",
            (
                item.followers_count,
                item.media_count,
                item.metrics_source,
                item.metrics_source_url,
                item.snapshot_at,
                merchant_id,
                item.snapshot_at,
            ),
        )


def save_catalog_quality(db, merchant_id, item):
    if item.quality_score is not None:
        db.execute(
            """UPDATE merchants SET directory_quality_score=%s,
              directory_review_count=%s,quality_source=%s,quality_source_url=%s,
              quality_updated_at=%s WHERE id=%s""",
            (
                item.quality_score,
                item.review_count,
                item.quality_source,
                item.quality_source_url,
                item.snapshot_at,
                merchant_id,
            ),
        )


def import_records(db, records: list[CatalogMerchant]) -> CatalogImportResult:
    """Upsert reviewed snapshots, respecting persistent merchant exclusions."""
    created_handles = []
    enriched = 0
    excluded_handles = {
        row["handle"] for row in db.execute("SELECT handle FROM merchant_exclusions")
    }
    for item in records:
        if item.handle in excluded_handles:
            continue
        existing = db.execute("SELECT id FROM merchants WHERE handle=%s", (item.handle,)).fetchone()
        if existing:
            merchant_id = existing["id"]
            update_catalog_details(db, merchant_id, item)
            enriched += 1
        else:
            merchant_id = create_catalog_merchant(db, item)
            created_handles.append(item.handle)
        save_catalog_biography(db, merchant_id, item)
        save_catalog_categories(db, merchant_id, item)
        save_catalog_metrics(db, merchant_id, item)
        save_catalog_quality(db, merchant_id, item)
    return CatalogImportResult(
        created=len(created_handles),
        created_handles=created_handles,
        enriched=enriched,
    )


def catalog_records(paths=None) -> list[CatalogMerchant]:
    """Merge only supplied snapshot fields, preserving older fields and categories."""
    records = {}
    if not paths:
        seed = TypeAdapter(list[CatalogMerchant]).validate_json(
            (DATA_ROOT / "merchant_seed.json").read_bytes()
        )
        records = {
            item.handle: item.model_copy(
                update={"is_new": True, "description_source": "curated_seed"}
            )
            for item in seed
        }
    catalog = load_merchant_catalogs(paths or merchant_catalog_paths(DATA_ROOT))
    for item in catalog.merchants:
        previous = records.get(item.handle)
        if previous:
            item = CatalogMerchant.model_validate(
                {
                    **previous.model_dump(exclude_unset=True),
                    **item.model_dump(exclude_unset=True),
                    "category_codes": list(
                        dict.fromkeys([*previous.category_codes, *item.category_codes])
                    ),
                }
            )
        records[item.handle] = item
    return list(records.values())


def import_catalog(paths=None) -> CatalogImportResult:
    records = catalog_records(paths)
    with connect() as db:
        report = import_records(db, records)
        sync_search_index(db)
    return report
