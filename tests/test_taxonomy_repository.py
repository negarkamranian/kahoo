import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.cli.taxonomy import normalize
from backend.server.app import app
from backend.services.taxonomy import product_taxonomy, taxonomy_store
from backend.services.taxonomy_repository import (
    TaxonomyNotInitializedError,
    active_taxonomy_id,
    persist_taxonomy,
)
from tests.factories import upstream_fixture


class TaxonomyRepositoryTests(unittest.TestCase):
    @patch("backend.services.taxonomy_repository.connect")
    def test_missing_taxonomy_is_an_error_without_a_file_fallback(self, connect):
        connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (
            None
        )
        with self.assertRaises(TaxonomyNotInitializedError):
            active_taxonomy_id()
        with patch(
            "backend.server.taxonomy_routes.product_taxonomy",
            side_effect=TaxonomyNotInitializedError,
        ):
            with TestClient(app) as client:
                response = client.get("/api/taxonomy")
        self.assertEqual(503, response.status_code)
        self.assertEqual({"error": "taxonomy_not_initialized"}, response.json())

    @patch("backend.services.taxonomy_repository.connect")
    def test_taxonomy_archive_checksum_is_verified_before_any_write(self, connect):
        source = json.dumps(upstream_fixture()).encode()
        taxonomy = normalize(source)
        with self.assertRaisesRegex(ValueError, "checksum"):
            persist_taxonomy(taxonomy, b"different source", "License")
        connect.assert_not_called()

    @patch("backend.services.taxonomy_repository.connect")
    def test_partial_taxonomy_import_never_activates_a_release(self, connect):
        source = json.dumps(upstream_fixture()).encode()
        taxonomy = normalize(source)
        db = connect.return_value.__enter__.return_value
        db.execute.return_value.fetchone.side_effect = [None, {"id": 12}]
        db.cursor.return_value.__enter__.return_value.executemany.side_effect = RuntimeError(
            "insert failed"
        )
        with self.assertRaisesRegex(RuntimeError, "insert failed"):
            persist_taxonomy(taxonomy, source, "License")
        self.assertFalse(
            any(
                "INSERT INTO taxonomy_active_release" in call.args[0]
                for call in db.execute.call_args_list
            )
        )
        self.assertIs(RuntimeError, connect.return_value.__exit__.call_args.args[0])

    @patch("backend.services.taxonomy.active_taxonomy_id", side_effect=[1, 2])
    @patch("backend.services.taxonomy.load_taxonomy")
    def test_active_release_changes_are_observed_without_restarting(self, load, _active):
        first = normalize(json.dumps(upstream_fixture()).encode())
        second = first.model_copy(deep=True)
        second.categories[0].name = "Updated category"
        load.side_effect = [first, second]
        taxonomy_store.cache_clear()
        self.addCleanup(taxonomy_store.cache_clear)
        self.assertNotEqual("Updated category", product_taxonomy().category("aa").name)
        self.assertEqual("Updated category", product_taxonomy().category("aa").name)
