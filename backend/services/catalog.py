import json
from pathlib import Path

from backend.database import PROJECT_ROOT, connect
from backend.search.indexing import sync_search_documents
from backend.search.metadata import sync_search_metadata
from backend.services.media import cache_merchant_avatar

DATA_ROOT = PROJECT_ROOT / "data"

REQUIRED_NEW_MERCHANT_FIELDS = {
    "name",
    "description",
    "category_code",
    "city",
}


def merchant_catalog_paths(data_root: Path):
    paths = [
        data_root / "merchant_catalog.json",
        *sorted(data_root.glob("merchant_catalog_expansion_*.json")),
    ]
    shared = data_root / "merchant_catalog_shared.json"
    if shared.exists():
        paths.append(shared)
    return paths


def load_merchant_catalog(path: Path):
    """Load and validate the reproducible public merchant-data snapshot."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    snapshot_at = payload.get("snapshot_at")
    merchants = payload.get("merchants")
    if not snapshot_at or not isinstance(merchants, list):
        raise ValueError("merchant catalog needs snapshot_at and a merchants list")

    handles = set()
    for merchant in merchants:
        handle = merchant.get("handle", "")
        if not handle.startswith("@") or handle != handle.lower():
            raise ValueError(f"invalid merchant handle: {handle!r}")
        if handle in handles:
            raise ValueError(f"duplicate merchant handle: {handle}")
        handles.add(handle)
        if merchant.get("is_new"):
            missing = REQUIRED_NEW_MERCHANT_FIELDS - merchant.keys()
            if missing:
                raise ValueError(f"{handle} is missing: {', '.join(sorted(missing))}")
        categories = merchant.get("category_codes", [])
        if len(categories) != len(set(categories)):
            raise ValueError(f"duplicate category for {handle}")
        for field in ("followers_count", "media_count"):
            value = merchant.get(field)
            if value is not None and (not isinstance(value, int) or value < 0):
                raise ValueError(f"invalid {field} for {handle}")

    return snapshot_at, merchants


def load_merchant_catalogs(paths):
    """Load catalog shards and reject duplicates across shard boundaries."""
    snapshots = []
    merchants = []
    handles = set()
    for path in paths:
        snapshot_at, shard = load_merchant_catalog(path)
        snapshots.append(snapshot_at)
        for merchant in shard:
            handle = merchant["handle"]
            if handle in handles:
                raise ValueError(f"duplicate merchant handle across catalogs: {handle}")
            handles.add(handle)
            merchants.append({**merchant, "snapshot_at": snapshot_at})
    return max(snapshots), merchants


def import_records(db, records):
    """Upsert the reviewed public-directory snapshot without claiming verification."""
    created = 0
    created_handles = []
    enriched = 0
    excluded_handles = {
        row["handle"] for row in db.execute("SELECT handle FROM merchant_exclusions")
    }
    for item in records:
        snapshot_at = item.get("snapshot_at")
        handle = item["handle"]
        if handle in excluded_handles:
            continue
        description_source = item.get("description_source", "curated_public_directory")
        metrics_source = item.get("metrics_source", "curated_public_directory")
        existing = db.execute(
            "SELECT id,avatar_blob FROM merchants WHERE handle=%s", (handle,)
        ).fetchone()
        if existing:
            merchant_id = existing["id"]
            enriched += 1
            if item.get("is_new"):
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
                        item["name"],
                        item["description"],
                        description_source,
                        item["source_url"],
                        item["category_code"],
                        item["city"],
                        item["source_url"],
                        merchant_id,
                    ),
                )
        else:
            missing = {"name", "description", "category_code", "city", "source_url"} - item.keys()
            if missing:
                raise ValueError(f"{handle}: new merchant needs {', '.join(sorted(missing))}")
            username = handle[1:]
            name = item["name"]
            source_url = item["source_url"]
            cursor = db.execute(
                """INSERT INTO merchants(
                  instagram_id,name,handle,description,description_source,
                  description_source_url,description_updated_at,source_url,
                  category_code,city,avatar_initial,avatar_color,instagram_url,
                  updated_label,verified,followers_count,media_count,
                  metrics_source,metrics_source_url,metrics_updated_at)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,'داده عمومی',0,%s,%s,
                    %s,%s,%s) RETURNING id""",
                (
                    f"catalog_{username}",
                    name,
                    handle,
                    item["description"],
                    description_source,
                    source_url,
                    snapshot_at,
                    source_url,
                    item["category_code"],
                    item["city"],
                    name[0],
                    "#e3e7e1",
                    f"https://www.instagram.com/{username}/",
                    item.get("followers_count"),
                    item.get("media_count"),
                    metrics_source,
                    item.get("metrics_source_url"),
                    snapshot_at,
                ),
            )
            merchant_id = cursor.fetchone()["id"]
            created += 1
            created_handles.append(handle)
            cache_merchant_avatar(db, merchant_id, name[0], "#e3e7e1")

        if item.get("biography"):
            db.execute(
                """UPDATE merchants SET biography=%s,biography_source=%s,
                biography_updated_at=CURRENT_TIMESTAMP
                WHERE id=%s AND biography_source IS NULL""",
                (item["biography"], item["biography_source"], merchant_id),
            )
        if "category_codes" in item:
            db.execute(
                "DELETE FROM merchant_categories WHERE merchant_id=%s AND source='curated_catalog'",
                (merchant_id,),
            )
            for code in item["category_codes"]:
                if code == item.get("category_code"):
                    continue
                db.execute(
                    """INSERT INTO merchant_categories(merchant_id,category_code,confidence,source,source_url)
                    VALUES(%s,%s,0.9,'curated_catalog',%s)
                    ON CONFLICT(merchant_id,category_code) DO NOTHING""",
                    (merchant_id, code, item.get("source_url")),
                )

        if item.get("metrics_source_url"):
            db.execute(
                """UPDATE merchants SET
                  followers_count=COALESCE(%s,followers_count),
                  media_count=COALESCE(%s,media_count),
                  metrics_source=%s,
                  metrics_source_url=%s,metrics_updated_at=%s
                  WHERE id=%s AND (metrics_updated_at IS NULL OR metrics_updated_at<=%s)""",
                (
                    item.get("followers_count"),
                    item.get("media_count"),
                    metrics_source,
                    item["metrics_source_url"],
                    snapshot_at,
                    merchant_id,
                    snapshot_at,
                ),
            )
        if item.get("quality_score") is not None:
            db.execute(
                """UPDATE merchants SET directory_quality_score=%s,
                  directory_review_count=%s,quality_source=%s,quality_source_url=%s,
                  quality_updated_at=%s WHERE id=%s""",
                (
                    item["quality_score"],
                    item.get("review_count", 0),
                    item.get("quality_source", "curated_public_directory"),
                    item.get("quality_source_url", item.get("source_url")),
                    snapshot_at,
                    merchant_id,
                ),
            )
    return {
        "created": created,
        "created_handles": created_handles,
        "enriched": enriched,
    }


def catalog_records(paths=None):
    """Load supplied catalogs, or combine the checked-in snapshots for an explicit seed."""
    records = {}
    if not paths:
        for item in json.loads((DATA_ROOT / "merchant_seed.json").read_text(encoding="utf-8")):
            records[item["handle"]] = {**item, "is_new": True, "description_source": "curated_seed"}
    _, catalog = load_merchant_catalogs(paths or merchant_catalog_paths(DATA_ROOT))
    for item in catalog:
        previous = records.get(item["handle"], {})
        categories = list(
            dict.fromkeys([*previous.get("category_codes", []), *item.get("category_codes", [])])
        )
        records[item["handle"]] = {**previous, **item, "category_codes": categories}
    return list(records.values())


def import_catalog(paths=None):
    records = catalog_records(paths)
    with connect() as db:
        report = import_records(db, records)
        sync_search_metadata(db)
        sync_search_documents(db)
    return report
