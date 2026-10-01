import unittest

from scripts.add_merchant import infer_category, normalize_identifier


class AddMerchantTests(unittest.TestCase):
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
