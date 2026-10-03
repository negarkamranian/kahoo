import json
import unittest
from unittest.mock import Mock, patch

from pydantic import ValidationError

from backend.models.media import MerchantMedia
from backend.models.merchants import AdminMerchantQuery
from backend.serialization import json_default
from backend.services.catalog import import_records
from backend.services.categories import category_tree
from backend.services.media import ensure_gallery_images
from backend.services.profiles import instagram_media_backfill_status


class ServiceContractTests(unittest.TestCase):
    def test_pagination_model_rejects_invalid_values_without_coercion(self):
        for fields in (
            {"limit": 0},
            {"limit": 101},
            {"limit": True},
            {"limit": "7"},
            {"offset": -1},
            {"offset": 1.5},
            {"offset": False},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                AdminMerchantQuery(**fields)

    @patch("backend.services.categories.connect")
    def test_category_models_preserve_hierarchy_and_deduplicate_merchant_counts(self, connect):
        connect.return_value.__enter__.return_value.execute.side_effect = [
            [
                {
                    "code": "1",
                    "parent_code": None,
                    "level": 1,
                    "label_fa": "Root",
                    "label_en": "Root",
                    "icon": None,
                },
                {
                    "code": "2",
                    "parent_code": "1",
                    "level": 2,
                    "label_fa": "Child",
                    "label_en": "Child",
                    "icon": None,
                },
            ],
            [{"merchant_id": 1, "category_code": "1"}, {"merchant_id": 1, "category_code": "2"}],
        ]
        tree = category_tree()
        self.assertEqual(1, tree[0].count)
        self.assertEqual("2", tree[0].children[0].code)
        payload = json.loads(json.dumps(tree, default=json_default))
        self.assertEqual(1, payload[0]["children"][0]["count"])
        self.assertEqual([], payload[0]["children"][0]["children"])

    @patch("backend.services.profiles.merchant_media_rows")
    def test_backfill_status_preserves_missing_media_flags(self, rows):
        rows.return_value = [MerchantMedia(id=1, handle="@shop")]
        status = instagram_media_backfill_status(handles=["@shop"])
        self.assertTrue(status[0].missing_avatar)
        self.assertTrue(status[0].missing_posts)
        self.assertEqual(0, status[0].cached_images)
        self.assertEqual([], instagram_media_backfill_status(handles=["@other"]))

    def test_empty_maintenance_reports_serialize_explicit_zero_counts(self):
        database = Mock()
        database.execute.return_value = []
        report = import_records(database, [])
        self.assertEqual(
            {"created": 0, "created_handles": [], "enriched": 0},
            json.loads(json.dumps(report, default=json_default)),
        )
        cached = ensure_gallery_images(database)
        self.assertEqual(
            {"attempted_images": 0, "cached_images": 0, "failed_images": 0},
            json.loads(json.dumps(cached, default=json_default)),
        )
