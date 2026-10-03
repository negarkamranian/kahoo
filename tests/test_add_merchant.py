import unittest
from unittest.mock import patch

from backend.merchant_import import infer_category, normalize_identifier


class AddMerchantTests(unittest.TestCase):
    @patch("scripts.add_merchant.print")
    @patch("scripts.add_merchant.add_or_refresh_merchant")
    @patch("scripts.add_merchant.run_category_seed")
    @patch("scripts.add_merchant.run_migrations")
    def test_cli_uses_the_shared_import_service(self, migrations, seed, import_merchant, output):
        from scripts.add_merchant import main

        import_merchant.return_value = {"handle": "@shop", "created": True}
        with patch("sys.argv", ["add_merchant.py", "@shop", "--category", "66010100"]):
            main()
        migrations.assert_called_once()
        seed.assert_called_once()
        import_merchant.assert_called_once_with(
            "@shop", category_code="66010100", name=None, description=None, city="ایران"
        )
        self.assertIn('"created": true', output.call_args.args[0])

    def test_normalizes_handle_and_profile_url(self):
        self.assertEqual("@example.shop", normalize_identifier("@Example.Shop"))
        self.assertEqual(
            "@example.shop",
            normalize_identifier("https://www.instagram.com/example.shop/?hl=fa"),
        )

    def test_rejects_non_instagram_url(self):
        with self.assertRaises(ValueError):
            normalize_identifier("https://example.com/shop")

    def test_infers_category_from_recent_post_captions(self):
        profile = {
            "name": "فروشگاه نمونه",
            "biography": "",
            "posts": [{"caption": "قاب و کاور جدید موبایل"}],
        }
        code, description = infer_category(profile)
        self.assertEqual("66010100", code)
        self.assertIn("موبایل", description)


if __name__ == "__main__":
    unittest.main()
