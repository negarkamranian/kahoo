import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from backend.cli import main
from backend.instagram import normalize_identifier
from backend.services.merchants import add_or_refresh_merchant


class AddMerchantTests(unittest.TestCase):
    @patch("backend.cli.initialize_database")
    @patch("backend.cli.merchants.add_or_refresh_merchant")
    def test_cli_uses_the_shared_import_workflow(self, import_merchant, migrate):
        import_merchant.return_value = {"handle": "@shop", "created": True}
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["merchants", "add", "@shop", "--category", "66010100"])
        self.assertEqual(0, status)
        migrate.assert_called_once()
        import_merchant.assert_called_once_with("@shop", "66010100", None, None, "ایران")
        self.assertIn('"created": true', output.getvalue())

    def test_normalizes_handle_and_profile_url(self):
        self.assertEqual("@example.shop", normalize_identifier("@Example.Shop"))
        self.assertEqual(
            "@example.shop", normalize_identifier("https://www.instagram.com/example.shop/?hl=fa")
        )

    def test_rejects_non_instagram_url(self):
        with self.assertRaises(ValueError):
            normalize_identifier("https://example.com/shop")

    @patch("backend.services.merchants.instagram_profile")
    @patch("backend.services.merchants.connect")
    def test_new_merchant_requires_category_before_contacting_instagram(self, connect, profile):
        connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (
            None
        )
        with self.assertRaisesRegex(ValueError, "choose a GPC category"):
            add_or_refresh_merchant("@shop")
        profile.assert_not_called()

    @patch("backend.services.merchants.sync_search_documents")
    @patch("backend.services.merchants.sync_search_metadata")
    @patch(
        "backend.services.merchants.instagram_profile", return_value={"name": "Shop", "posts": []}
    )
    @patch("backend.services.merchants.connect")
    def test_refresh_preserves_existing_category_without_keyword_rules(
        self, connect, profile, metadata, index
    ):
        database = connect.return_value.__enter__.return_value

        def execute(query, params=None):
            if "SELECT id,category_code" in query:
                return Mock(fetchone=lambda: {"id": 7, "category_code": "custom-code"})
            if "SELECT code,label_fa" in query:
                self.assertEqual(("custom-code",), params)
                return Mock(fetchone=lambda: {"code": "custom-code", "label_fa": "دسته جدید"})
            return Mock(fetchone=lambda: {"id": 7})

        database.execute.side_effect = execute
        result = add_or_refresh_merchant("@shop")
        self.assertEqual("custom-code", result["category_code"])
        self.assertFalse(result["created"])
        profile.assert_called_once_with("@shop")
        metadata.assert_called_once_with(database)
        index.assert_called_once_with(database)
