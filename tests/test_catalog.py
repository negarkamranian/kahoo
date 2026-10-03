import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.models.catalog import CatalogMerchant, MerchantCatalog
from pydantic import ValidationError

from backend.services.catalog import (
    catalog_records,
    load_merchant_catalog,
    load_merchant_catalogs,
    merchant_catalog_paths,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MerchantCatalogTests(unittest.TestCase):
    def test_invalid_catalog_metrics_and_duplicate_handles_are_rejected(self):
        for value in (-1, True, "123"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                CatalogMerchant(handle="@shop", followers_count=value)
        with self.assertRaisesRegex(ValidationError, "duplicate merchant handle"):
            MerchantCatalog(
                snapshot_at="2026-10-03",
                merchants=[
                    CatalogMerchant(handle="@shop"),
                    CatalogMerchant(handle="@shop"),
                ],
            )

    def test_merging_partial_snapshot_preserves_seed_fields_and_categories(self):
        seed = {
            "handle": "@shop",
            "name": "Shop",
            "description": "original",
            "category_code": "1",
            "city": "تهران",
            "source_url": "https://instagram.com/shop/",
            "category_codes": ["1", "2"],
        }
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "merchant_seed.json").write_text(json.dumps([seed]))
            (root / "merchant_catalog.json").write_text(
                json.dumps(
                    {
                        "snapshot_at": "2026-10-03",
                        "merchants": [
                            {
                                "handle": "@shop",
                                "followers_count": 100,
                                "category_codes": ["2", "3"],
                            },
                        ],
                    }
                )
            )
            with patch("backend.services.catalog.DATA_ROOT", root):
                (merchant,) = catalog_records()
        self.assertEqual("original", merchant.description)
        self.assertEqual("curated_seed", merchant.description_source)
        self.assertEqual(["1", "2", "3"], merchant.category_codes)
        self.assertEqual(100, merchant.followers_count)
        self.assertEqual("2026-10-03", merchant.snapshot_at)

    def test_default_import_combines_snapshot_data_without_duplicate_merchants(self):
        records = catalog_records()
        self.assertEqual(len(records), len({row.handle for row in records}))
        for row in records:
            self.assertTrue(
                {"name", "description", "category_code", "city", "source_url"}
                <= row.model_fields_set
            )
            self.assertFalse(hasattr(row, "photos"))
        shards = load_merchant_catalogs(merchant_catalog_paths(PROJECT_ROOT / "data")).merchants
        imported = {row.handle: row for row in records}
        for row in shards:
            self.assertEqual(row.snapshot_at, imported[row.handle].snapshot_at)

    def test_catalog_is_valid_and_contains_the_expected_expansion(self):
        catalog = load_merchant_catalog(PROJECT_ROOT / "data" / "merchant_catalog.json")

        self.assertTrue(catalog.snapshot_at.startswith("2026-10-02"))
        self.assertEqual(64, sum(item.is_new for item in catalog.merchants))
        self.assertEqual(len(catalog.merchants), len({item.handle for item in catalog.merchants}))

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
        merchants = load_merchant_catalogs(paths).merchants
        expansion_paths = sorted((PROJECT_ROOT / "data").glob("merchant_catalog_expansion_*.json"))
        expansion = [
            merchant
            for path in expansion_paths
            for merchant in json.loads(path.read_text(encoding="utf-8"))["merchants"]
        ]

        self.assertEqual(300, len(expansion))
        self.assertGreaterEqual(len(merchants), 300)
        self.assertEqual(len(merchants), len({item.handle for item in merchants}))
        self.assertGreaterEqual(min(item["followers_count"] for item in expansion), 100_000)
        self.assertGreaterEqual(min(item["quality_score"] for item in expansion), 4.1)

    def test_all_shared_instagram_links_are_cataloged(self):
        shared = json.loads(
            (PROJECT_ROOT / "data" / "merchant_catalog_shared.json").read_text(encoding="utf-8")
        )["merchants"]
        all_merchants = load_merchant_catalogs(
            merchant_catalog_paths(PROJECT_ROOT / "data")
        ).merchants
        all_handles = {merchant.handle for merchant in all_merchants}

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
                (PROJECT_ROOT / "docs" / "shops.txt").read_text(encoding="utf-8"),
            )
        }
        self.assertEqual(131, len(submitted))
        self.assertTrue(submitted <= all_handles)


if __name__ == "__main__":
    unittest.main()
