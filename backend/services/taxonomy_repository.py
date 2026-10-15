import gzip
import hashlib
from functools import lru_cache

from psycopg.types.json import Jsonb

from backend.database import connect
from backend.models.taxonomy import (
    ProductCategory,
    ProductTaxonomy,
    TaxonomyAttribute,
    TaxonomyMetadata,
)


class TaxonomyNotInitializedError(RuntimeError):
    pass


def persist_taxonomy(taxonomy, source, license_text):
    if hashlib.sha256(source).hexdigest() != taxonomy.metadata.source_sha256:
        raise ValueError("Taxonomy source does not match its recorded checksum")
    with connect() as db:
        db.execute("SELECT pg_advisory_xact_lock(hashtextextended('taxonomy_import',0))")
        existing = db.execute(
            """SELECT id FROM taxonomy_releases
               WHERE version=%s AND locale=%s AND source_sha256=%s""",
            (taxonomy.metadata.version, taxonomy.metadata.locale, taxonomy.metadata.source_sha256),
        ).fetchone()
        release_id = (
            existing["id"] if existing else insert_release(db, taxonomy, source, license_text)
        )
        db.execute(
            """INSERT INTO taxonomy_active_release(singleton,release_id) VALUES(true,%s)
               ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id""",
            (release_id,),
        )
    return taxonomy.metadata


def insert_release(db, taxonomy, source, license_text):
    metadata = taxonomy.metadata
    row = db.execute(
        """INSERT INTO taxonomy_releases(version,locale,source_url,download_url,source_commit,
             source_sha256,categories,attributes,value_count,source_archive,license_text)
           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
        (
            metadata.version,
            metadata.locale,
            metadata.source_url,
            metadata.download_url,
            metadata.source_commit,
            metadata.source_sha256,
            metadata.categories,
            metadata.attributes,
            metadata.values,
            gzip.compress(source, mtime=0),
            license_text,
        ),
    ).fetchone()
    release_id = row["id"]
    with db.cursor() as cursor:
        cursor.executemany(
            """INSERT INTO taxonomy_categories(release_id,id,code,level,name,full_name,parent_id,
                 position,attributes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            [
                category_row(release_id, position, item)
                for position, item in enumerate(taxonomy.categories)
            ],
        )
        cursor.executemany(
            """INSERT INTO taxonomy_attributes(release_id,id,name,handle,description,position,
                 extended_attributes,allowed_values) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            [
                attribute_row(release_id, position, item)
                for position, item in enumerate(taxonomy.attributes)
            ],
        )
    return release_id


def category_row(release_id, position, item):
    return (
        release_id,
        item.id,
        item.code,
        item.level,
        item.name,
        item.full_name,
        item.parent_id,
        position,
        Jsonb([reference.model_dump() for reference in item.attributes]),
    )


def attribute_row(release_id, position, item):
    return (
        release_id,
        item.id,
        item.name,
        item.handle,
        item.description,
        position,
        Jsonb([alias.model_dump() for alias in item.extended_attributes]),
        Jsonb([value.model_dump() for value in item.values]),
    )


def active_taxonomy_id():
    with connect() as db:
        row = db.execute(
            "SELECT release_id FROM taxonomy_active_release WHERE singleton=true"
        ).fetchone()
    if not row:
        raise TaxonomyNotInitializedError("Import the product taxonomy with catalog sync-shopify")
    return row["release_id"]


@lru_cache(maxsize=2)
def load_taxonomy(release_id):
    with connect() as db:
        row = db.execute("SELECT * FROM taxonomy_releases WHERE id=%s", (release_id,)).fetchone()
        if not row:
            raise TaxonomyNotInitializedError(f"Unknown taxonomy release: {release_id}")
        categories = [
            ProductCategory.model_validate(item)
            for item in db.execute(
                "SELECT * FROM taxonomy_categories WHERE release_id=%s ORDER BY position",
                (release_id,),
            )
        ]
        attributes = [
            TaxonomyAttribute.model_validate({**item, "values": item["allowed_values"]})
            for item in db.execute(
                "SELECT * FROM taxonomy_attributes WHERE release_id=%s ORDER BY position",
                (release_id,),
            )
        ]
    return ProductTaxonomy(
        metadata=TaxonomyMetadata.model_validate({**row, "values": row["value_count"]}),
        categories=categories,
        attributes=attributes,
    )
