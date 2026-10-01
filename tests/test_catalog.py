import json
import unittest
from pathlib import Path

from backend.catalog import load_merchant_catalog


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MerchantCatalogTests(unittest.TestCase):
    def test_catalog_is_valid_and_contains_the_expected_expansion(self):
        snapshot_at, merchants = load_merchant_catalog(
            PROJECT_ROOT / "data" / "merchant_catalog.json"
        )

        self.assertTrue(snapshot_at.startswith("2026-10-02"))
        self.assertEqual(64, sum(bool(item.get("is_new")) for item in merchants))
        self.assertEqual(len(merchants), len({item["handle"] for item in merchants}))

    def test_all_catalog_categories_exist_in_the_gpc_seed(self):
        payload = json.loads(
            (PROJECT_ROOT / "data" / "merchant_catalog.json").read_text(
                encoding="utf-8"
            )
        )
        category_seed = (PROJECT_ROOT / "data" / "categories.sql").read_text(
            encoding="utf-8"
        )
        codes = {
            code
            for merchant in payload["merchants"]
            for code in (
                [merchant["category_code"]] if merchant.get("category_code") else []
            )
            + merchant.get("category_codes", [])
        }

        for code in codes:
            self.assertIn(f"('{code}',", category_seed)


if __name__ == "__main__":
    unittest.main()
