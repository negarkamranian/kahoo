import json
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from backend.cli.taxonomy import normalize
from backend.database import connect, initialize_database
from backend.models.media import InstagramProfile
from backend.models.merchants import MerchantImport
from backend.search.indexing import upsert_document
from backend.search.retrieval import lexical_merchant_matches
from backend.services.merchants import create_imported_merchant
from backend.services.product_worker import claim_product
from backend.services.taxonomy import product_taxonomy
from backend.services.taxonomy_repository import persist_taxonomy
from tests.factories import upstream_fixture


@unittest.skipUnless(
    os.environ.get("KAHOO_TEST_DATABASE_URL"),
    "Set KAHOO_TEST_DATABASE_URL for PostgreSQL integration tests",
)
class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base_url = os.environ["KAHOO_TEST_DATABASE_URL"]
        cls.schema = "kahoo_test_" + uuid4().hex
        with psycopg.connect(cls.base_url, autocommit=True) as db:
            db.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public")
            db.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public")
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(cls.schema)))
        cls.addClassCleanup(cls.drop_schema)
        dsn = make_conninfo(cls.base_url, options=f"-csearch_path={cls.schema},public")
        cls.config = patch("backend.config.settings.database_url", dsn)
        cls.config.start()
        cls.addClassCleanup(cls.config.stop)
        initialize_database()

    @classmethod
    def drop_schema(cls):
        with psycopg.connect(cls.base_url, autocommit=True) as db:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(cls.schema)))

    def test_database_setup_is_idempotent_and_migrations_have_checksums(self):
        self.assertFalse(initialize_database()["categories_seeded"])
        with connect() as db:
            rows = list(db.execute("SELECT checksum FROM schema_migrations"))
            self.assertTrue(rows)
            self.assertTrue(all(len(row["checksum"]) == 64 for row in rows))
            self.assertGreater(
                db.execute("SELECT count(*) AS count FROM categories").fetchone()["count"], 0
            )

    def test_reference_import_is_atomic_and_cache_observes_active_release_changes(self):
        for label in ("First", "Second"):
            source = upstream_fixture()
            source["verticals"][0]["categories"][0]["name"] = label
            content = json.dumps(source).encode()
            taxonomy = normalize(content)
            persist_taxonomy(taxonomy, content, "Test license")
            self.assertEqual(label, product_taxonomy().category("aa").name)
        with connect() as db:
            self.assertEqual(
                2, db.execute("SELECT count(*) AS count FROM taxonomy_releases").fetchone()["count"]
            )
            self.assertEqual(
                16,
                db.execute("SELECT count(*) AS count FROM taxonomy_categories").fetchone()["count"],
            )
        persist_taxonomy(taxonomy, content, "Test license")
        with connect() as db:
            self.assertEqual(
                2, db.execute("SELECT count(*) AS count FROM taxonomy_releases").fetchone()["count"]
            )

    def test_lexical_retrieval_matches_distinct_concepts_in_postgresql(self):
        with connect() as db:
            category = db.execute("SELECT code FROM categories LIMIT 1").fetchone()["code"]
            merchant_id = create_imported_merchant(
                db,
                MerchantImport(identifier="@lexical_test"),
                InstagramProfile(name="کیف چرمی"),
                category,
            )
            upsert_document(db, merchant_id, "merchant", merchant_id, "کیف چرمی", "کیف چرمی")
            matches = lexical_merchant_matches(db, "کیف چرمی")
            self.assertEqual(1, matches[merchant_id].coverage)
            self.assertTrue(matches[merchant_id].coherent)

    def test_stale_product_leases_stop_after_three_attempts(self):
        with connect() as db:
            category = db.execute("SELECT code FROM categories LIMIT 1").fetchone()["code"]
            merchant_id = create_imported_merchant(
                db,
                MerchantImport(identifier="@leased_test"),
                InstagramProfile(name="Lease test"),
                category,
            )
            for attempts in (3, 2):
                db.execute(
                    """INSERT INTO products(merchant_id,collection_key,caption,permalink,source_hash,
                         status,attempts,started_at) VALUES(%s,%s,'test','https://example.test/p','hash',
                         'processing',%s,CURRENT_TIMESTAMP-INTERVAL '31 minutes')""",
                    (merchant_id, str(attempts), attempts),
                )
        row, images, _token = claim_product()
        self.assertEqual("2", row["collection_key"])
        self.assertEqual(3, row["attempts"])
        self.assertEqual([], images)
        self.assertIsNone(claim_product())
        with connect() as db:
            expired = db.execute(
                "SELECT status FROM products WHERE merchant_id=%s AND collection_key='3'",
                (merchant_id,),
            ).fetchone()
            self.assertEqual("failed", expired["status"])
