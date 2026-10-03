import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

from pydantic import ValidationError

from backend.cli import main
from backend.models.media import InstagramProfile
from backend.models.merchants import ImportResult, MerchantImport
from backend.services.merchants import add_or_refresh_merchant


class AddMerchantTests(unittest.TestCase):
    def test_import_contract_rejects_overrides_and_invalid_identity(self):
        for fields in (
            {"name": "Manual"},
            {"description": "Manual"},
            {"identifier": "shop"},
            {"identifier": "@Shop"},
            {"city": "   "},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                MerchantImport.model_validate({"identifier": "@shop", **fields})

    @patch("backend.cli.initialize_database")
    @patch("backend.cli.merchants.add_or_refresh_merchant")
    def test_cli_uses_the_shared_import_workflow(self, import_merchant, migrate):
        import_merchant.return_value = ImportResult(handle="@shop", created=True)
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["merchants", "add", "@shop", "--category", "66010100"])
        self.assertEqual(0, status)
        migrate.assert_called_once()
        import_merchant.assert_called_once_with(
            MerchantImport(identifier="@shop", category_code="66010100")
        )
        self.assertIn("created=True", output.getvalue())

    @patch("backend.services.merchants.instagram_profile")
    @patch("backend.services.merchants.connect")
    def test_new_merchant_requires_category_before_contacting_instagram(self, connect, profile):
        connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = (
            None
        )
        with self.assertRaisesRegex(ValueError, "choose a GPC category"):
            add_or_refresh_merchant(MerchantImport(identifier="@shop"))
        profile.assert_not_called()

    @patch("backend.services.merchants.replace_profile_posts", return_value=0)
    @patch("backend.services.merchants.sync_search_index")
    @patch(
        "backend.services.merchants.instagram_profile", return_value=InstagramProfile(name="Shop")
    )
    @patch("backend.services.merchants.connect")
    def test_refresh_preserves_existing_category_without_keyword_rules(
        self, connect, profile, index, replace_posts
    ):
        database = connect.return_value.__enter__.return_value

        def execute(query, params=None):
            if "SELECT id,category_code" in query:
                return Mock(fetchone=lambda: {"id": 7, "category_code": "custom-code"})
            if "SELECT code" in query:
                self.assertEqual(("custom-code",), params)
                return Mock(fetchone=lambda: {"code": "custom-code", "label_fa": "دسته جدید"})
            return Mock(fetchone=lambda: {"id": 7})

        database.execute.side_effect = execute
        result = add_or_refresh_merchant(MerchantImport(identifier="@shop"))
        self.assertEqual("custom-code", result.category_code)
        self.assertFalse(result.created)
        profile.assert_called_once_with("@shop")
        replace_posts.assert_called_once_with(database, 7, profile.return_value)
        self.assertEqual(0, result.post_images_saved)
        index.assert_called_once_with(database)

    @patch("backend.services.merchants.replace_profile_posts", return_value=0)
    @patch("backend.services.merchants.sync_search_index")
    @patch("backend.services.merchants.instagram_profile")
    @patch("backend.services.merchants.connect")
    def test_import_and_refresh_take_name_and_description_only_from_instagram(
        self, connect, profile, index, replace_posts
    ):
        database = connect.return_value.__enter__.return_value
        for existing in (None, {"id": 7, "category_code": "custom-code"}):
            for biography in ("  Instagram biography  ", ""):
                with self.subTest(existing=existing, biography=biography):
                    database.reset_mock()
                    replace_posts.reset_mock()
                    profile.return_value = InstagramProfile(name="  Shop  ", biography=biography)

                    def execute(query, params=None, existing=existing):
                        if "SELECT id" in query:
                            return Mock(fetchone=lambda: existing)
                        if "SELECT code FROM categories" in query:
                            return Mock(fetchone=lambda: {"code": "custom-code"})
                        return Mock(fetchone=lambda: {"id": 7})

                    database.execute.side_effect = execute
                    result = add_or_refresh_merchant(
                        MerchantImport(
                            identifier="@shop", category_code="custom-code", city="  Tehran  "
                        )
                    )
                    self.assertEqual("Shop", result.name)
                    self.assertEqual(existing is None, result.created)
                    replace_posts.assert_called_once_with(database, 7, profile.return_value)
                    self.assertEqual(0, result.post_images_saved)
                    writes = [
                        call.args[1]
                        for call in database.execute.call_args_list
                        if "INSERT INTO merchants(" in call.args[0]
                        or "UPDATE merchants SET name=" in call.args[0]
                    ]
                    self.assertEqual(1, len(writes))
                    params = writes[0]
                    if existing:
                        self.assertEqual("Shop", params[0])
                        self.assertEqual(biography.strip(), params[1])
                        self.assertEqual("Tehran", params[6])
                        self.assertEqual(biography.strip(), params[8])
                    else:
                        self.assertEqual("Shop", params[1])
                        self.assertEqual(biography.strip(), params[3])
                        self.assertEqual(biography.strip(), params[7])
                        self.assertEqual("Tehran", params[10])
