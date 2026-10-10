import gzip
import hashlib
import json
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.cli import main
from backend.cli.taxonomy import VERSION, normalize, sync
from backend.server.app import app
from backend.services.taxonomy import TAXONOMY_PATH, TaxonomyStore, product_taxonomy


def upstream_fixture():
    attribute = {
        "id": "gid://shopify/TaxonomyAttribute/1",
        "name": "Color",
        "handle": "color",
        "description": "Product color",
        "extended_attributes": [{"name": "Liner color", "handle": "liner-color"}],
        "values": [
            {"id": "gid://shopify/TaxonomyValue/1", "name": "Blue", "handle": "color__blue"}
        ],
    }
    categories = []
    for level in range(8):
        code = "aa" + "-1" * level
        categories.append(
            {
                "id": f"gid://shopify/TaxonomyCategory/{code}",
                "level": level,
                "name": f"Category {level}",
                "full_name": f"Apparel > Category {level}",
                "parent_id": categories[-1]["id"] if categories else None,
                "attributes": [
                    {
                        "id": attribute["id"],
                        "name": "Liner color",
                        "handle": "liner-color",
                        "description": "Category-specific color description",
                        "extended": True,
                    }
                ],
                "return_reasons": [{"name": "Retained only in upstream"}],
            }
        )
    return {
        "version": VERSION,
        "verticals": [{"categories": categories}],
        "attributes": [attribute],
    }


class TaxonomyTests(unittest.TestCase):
    def test_complete_tree_retains_ids_parents_and_all_eight_levels(self):
        store = TaxonomyStore(normalize(json.dumps(upstream_fixture()).encode()))
        node = store.tree()[0]
        for level in range(8):
            self.assertEqual(level, node.level)
            self.assertEqual("aa" + "-1" * level, node.code)
            if level < 7:
                self.assertEqual(node.id, node.children[0].parent_id)
                node = node.children[0]
        self.assertEqual([], node.children)

    def test_extended_attributes_preserve_category_description_and_base_values(self):
        store = TaxonomyStore(normalize(json.dumps(upstream_fixture()).encode()))
        attribute = store.category_attributes("aa")[0]
        self.assertEqual("liner-color", attribute.handle)
        self.assertEqual("Category-specific color description", attribute.description)
        self.assertTrue(attribute.extended)
        self.assertEqual("Blue", attribute.values[0].name)
        self.assertEqual("liner-color", store.attribute("liner-color").handle)
        self.assertEqual("color", store.attribute("color").handle)

    def test_invalid_version_and_broken_links_are_rejected(self):
        for change in ("version", "parent", "depth", "attribute", "duplicate"):
            upstream = upstream_fixture()
            categories = upstream["verticals"][0]["categories"]
            if change == "version":
                upstream["version"] = "2025-01"
            elif change == "parent":
                categories[1]["parent_id"] = "missing"
            elif change == "depth":
                categories[1]["level"] = 3
            elif change == "attribute":
                categories[0]["attributes"][0]["id"] = "missing"
            else:
                categories.append(categories[0])
            with self.subTest(change=change), self.assertRaises(ValueError):
                normalize(json.dumps(upstream).encode())

    @patch("backend.cli.initialize_database")
    @patch("backend.cli.taxonomy.fetch")
    def test_offline_cli_preserves_original_export_and_needs_no_database(self, fetch, database):
        source = json.dumps(upstream_fixture()).encode()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.json.gz"
            source_path.write_bytes(gzip.compress(source))
            license_path = root / "LICENSE"
            license_path.write_text("Source license")
            output = root / "output"
            main(
                [
                    "catalog",
                    "sync-shopify",
                    "--source",
                    str(source_path),
                    "--license",
                    str(license_path),
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(
                source, gzip.decompress((output / "upstream-taxonomy.json.gz").read_bytes())
            )
            self.assertEqual("Source license", (output / "LICENSE").read_text())
            self.assertEqual(
                hashlib.sha256(source).hexdigest(),
                json.loads((output / "metadata.json").read_text())["source_sha256"],
            )
            source_path.write_bytes(gzip.compress(b"not json"))
            before = (output / "taxonomy.json.gz").read_bytes()
            with self.assertRaises(ValueError):
                sync(Namespace(source=source_path, license=license_path, output=output))
            self.assertEqual(before, (output / "taxonomy.json.gz").read_bytes())
        fetch.assert_not_called()
        database.assert_not_called()

    def test_checked_in_release_matches_original_counts_and_sha256(self):
        store = product_taxonomy()
        upstream = gzip.decompress(
            TAXONOMY_PATH.with_name("upstream-taxonomy.json.gz").read_bytes()
        )
        expected = normalize(upstream)
        self.assertEqual(expected, store.taxonomy)
        metadata = store.taxonomy.metadata
        self.assertEqual(
            (14606, 8240, 74820), (metadata.categories, metadata.attributes, metadata.values)
        )
        self.assertEqual(7, max(category.level for category in store.taxonomy.categories))


class TaxonomyHttpTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        fixture = TaxonomyStore(normalize(json.dumps(upstream_fixture()).encode()))
        mocked = patch("backend.server.taxonomy_routes.product_taxonomy", return_value=fixture)
        mocked.start()
        self.addCleanup(mocked.stop)

    def test_tree_search_pagination_and_parent_queries(self):
        response = self.client.get("/api/taxonomy/tree")
        self.assertEqual(200, response.status_code)
        self.assertEqual("aa", response.json()[0]["code"])
        self.assertEqual(8, self.client.get("/api/taxonomy").json()["categories"])
        self.assertEqual(
            "aa-1", self.client.get("/api/taxonomy/categories?parent=aa").json()[0]["code"]
        )
        self.assertEqual(1, len(self.client.get("/api/taxonomy/categories?parent=root").json()))
        self.assertEqual(
            "aa-1", self.client.get("/api/taxonomy/categories?offset=1&limit=1").json()[0]["code"]
        )
        self.assertEqual([], self.client.get("/api/taxonomy/categories?q=missing").json())
        self.assertEqual(1, len(self.client.get("/api/taxonomy/categories?q=Category%207").json()))
        self.assertEqual(400, self.client.get("/api/taxonomy/categories?limit=501").status_code)

    def test_attributes_unknown_codes_and_extended_handles(self):
        response = self.client.get("/api/taxonomy/categories/aa/attributes")
        self.assertEqual("liner-color", response.json()[0]["handle"])
        self.assertEqual("Blue", response.json()[0]["values"][0]["name"])
        self.assertEqual(
            "liner-color", self.client.get("/api/taxonomy/attributes/liner-color").json()["handle"]
        )
        self.assertNotIn("values", self.client.get("/api/taxonomy/attributes").json()[0])
        self.assertEqual([], self.client.get("/api/taxonomy/attributes?q=missing").json())
        for endpoint in (
            "categories/missing",
            "categories/missing/attributes",
            "attributes/missing",
            "categories?parent=missing",
        ):
            with self.subTest(endpoint=endpoint):
                self.assertEqual(404, self.client.get(f"/api/taxonomy/{endpoint}").status_code)
