import json
import re
import unittest
from pathlib import Path

from backend.catalog import load_merchant_catalog, load_merchant_catalogs, merchant_catalog_paths
from scripts.catalog import catalog_records

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MerchantCatalogTests(unittest.TestCase):
    def test_default_import_combines_snapshot_data_without_duplicate_merchants(self):
        records = catalog_records()
        self.assertEqual(len(records), len({row["handle"] for row in records}))
        for row in records:
            self.assertTrue(
                {"name", "description", "category_code", "city", "source_url"} <= row.keys()
            )
            self.assertNotIn("photos", row)
        _, shards = load_merchant_catalogs(merchant_catalog_paths(PROJECT_ROOT / "data"))
        imported = {row["handle"]: row for row in records}
        for row in shards:
            self.assertEqual(row["snapshot_at"], imported[row["handle"]]["snapshot_at"])

    def test_catalog_is_valid_and_contains_the_expected_expansion(self):
        snapshot_at, merchants = load_merchant_catalog(
            PROJECT_ROOT / "data" / "merchant_catalog.json"
        )

        self.assertTrue(snapshot_at.startswith("2026-10-02"))
        self.assertEqual(64, sum(bool(item.get("is_new")) for item in merchants))
        self.assertEqual(len(merchants), len({item["handle"] for item in merchants}))

    def test_all_catalog_categories_exist_in_the_gpc_seed(self):
        paths = merchant_catalog_paths(PROJECT_ROOT / "data")
        payloads = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
        category_seed = (PROJECT_ROOT / "data" / "categories.sql").read_text(encoding="utf-8")
        codes = {
            code
            for payload in payloads
            for merchant in payload["merchants"]
            for code in ([merchant["category_code"]] if merchant.get("category_code") else [])
            + merchant.get("category_codes", [])
        }

        for code in codes:
            self.assertIn(f"('{code}',", category_seed)

    def test_high_volume_expansion_is_large_and_deduplicated(self):
        paths = merchant_catalog_paths(PROJECT_ROOT / "data")
        _, merchants = load_merchant_catalogs(paths)
        expansion_paths = sorted((PROJECT_ROOT / "data").glob("merchant_catalog_expansion_*.json"))
        expansion = [
            merchant
            for path in expansion_paths
            for merchant in json.loads(path.read_text(encoding="utf-8"))["merchants"]
        ]

        self.assertEqual(300, len(expansion))
        self.assertGreaterEqual(len(merchants), 300)
        self.assertEqual(len(merchants), len({item["handle"] for item in merchants}))
        self.assertGreaterEqual(min(item["followers_count"] for item in expansion), 100_000)
        self.assertGreaterEqual(min(item["quality_score"] for item in expansion), 4.1)

    def test_all_shared_instagram_links_are_cataloged(self):
        shared = json.loads(
            (PROJECT_ROOT / "data" / "merchant_catalog_shared.json").read_text(encoding="utf-8")
        )["merchants"]
        _, all_merchants = load_merchant_catalogs(merchant_catalog_paths(PROJECT_ROOT / "data"))
        all_handles = {merchant["handle"] for merchant in all_merchants}

        self.assertEqual(130, len(shared))
        self.assertEqual(len(shared), len({item["handle"] for item in shared}))
        self.assertTrue({item["handle"] for item in shared} <= all_handles)
        self.assertTrue(
            all(
                item["source_url"] == f"https://www.instagram.com/{item['handle'][1:]}/"
                for item in shared
            )
        )
        submitted = {
            f"@{handle.lower()}"
            for handle in re.findall(
                r"instagram\.com/([A-Za-z0-9._]+)",
                (PROJECT_ROOT / "shops.txt").read_text(encoding="utf-8"),
            )
        }
        self.assertEqual(131, len(submitted))
        self.assertTrue(submitted <= all_handles)


if __name__ == "__main__":
    unittest.main()
