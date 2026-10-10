"""Search intent, identity ranking, and optional Instagram facts."""

import unittest
from unittest.mock import Mock, patch

from backend.models.instagram.embed import EmbedProfile
from backend.models.instagram.meta import MetaProfile
from backend.models.media import InstagramProfile
from backend.models.merchants import Merchant
from backend.models.search import SearchSuggestion
from backend.search.normalization import query_tokens
from backend.search.ranking import term_match_strength
from backend.search.retrieval import lexical_merchant_matches
from backend.search.service import identity_match
from backend.search.suggestions import category_suggestions, rank_suggestions, suggestion_score
from backend.services.profile_facts import save_account_facts


class DiscoverySearchTests(unittest.TestCase):
    def test_suggestions_preserve_intent_and_deduplicate_by_destination(self):
        candidates = [
            (SearchSuggestion(value="کیف", label="کیف · @one", type="merchant", merchant_id=1), 8),
            (SearchSuggestion(value="کیف", label="کیف · @two", type="merchant", merchant_id=2), 8),
            (SearchSuggestion(value="کیف", label="کیف", type="category", category_code="123"), 5),
            (SearchSuggestion(value="کیف", label="کیف", type="query"), 1),
            (SearchSuggestion(value="کیف", label="کیف", type="popular"), 2),
            (
                SearchSuggestion(
                    value="کیف one", label="کیف · @one", type="merchant", merchant_id=1
                ),
                7,
            ),
        ]
        results = rank_suggestions("کیف", candidates, 8)
        self.assertEqual(4, len(results))
        self.assertEqual({1, 2}, {item.merchant_id for item in results if item.type == "merchant"})
        self.assertEqual(
            ["123"], [item.category_code for item in results if item.type == "category"]
        )

    def test_multiword_suggestions_allow_a_typo_but_require_every_concept(self):
        self.assertGreater(suggestion_score("کفش چرم", "فروش کفش چرمی"), 0)
        self.assertEqual(0, suggestion_score("کفش چرمی", "فروش کفش ورزشی"))
        self.assertEqual(["کفش", "زنانه"], query_tokens("کفش کفش زنانه"))
        self.assertEqual(1, term_match_strength("کتاب", "کتابها"))
        self.assertEqual(0, term_match_strength("موبایل", "مو"))

    def test_category_suggestions_include_populated_ancestors_and_persian_variants(self):
        db = Mock()
        db.execute.side_effect = [
            [
                {"code": "1", "parent_code": None, "label_fa": "پوشاک", "label_en": "Clothing"},
                {"code": "2", "parent_code": "1", "label_fa": "کفش", "label_en": "Shoes"},
                {"code": "3", "parent_code": None, "label_fa": "خانه", "label_en": "Home"},
            ],
            [{"merchant_id": 7, "category_code": "2"}],
        ]
        candidates = list(category_suggestions(db))
        self.assertEqual({"1", "2"}, {item.category_code for item, _ in candidates})
        results = rank_suggestions("کفش", candidates, 8)
        self.assertEqual("2", results[0].category_code)
        self.assertEqual("1", rank_suggestions("cloth", candidates, 8)[0].category_code)

    def test_document_retrieval_requires_distinct_query_concepts(self):
        db = Mock()
        db.execute.return_value = []
        lexical_merchant_matches(db, "کفش زنانه چرمی کفش")
        params = db.execute.call_args.args[1]
        self.assertEqual(2, params["minimum_matches"])
        self.assertEqual(["کفش", "زنانه", "چرمی"], params["tokens"])
        self.assertEqual("'کفش':* & 'زنانه':* & 'چرمی':*", params["prefix"])

    def test_identity_matching_accepts_handle_punctuation(self):
        merchant = Merchant(id=1, name="کیف", handle="@bag_shop.ir", category_code="1", city="")
        self.assertTrue(identity_match(merchant, "bagshopir"))
        self.assertTrue(identity_match(merchant, "bag_shop ir"))
        self.assertFalse(identity_match(merchant, "bag"))

    @patch("backend.search.service.merchant_posts", return_value=[])
    @patch("backend.search.service.semantic_merchant_scores", return_value={})
    @patch("backend.search.service.lexical_merchant_matches", return_value={})
    @patch("backend.search.service.connect")
    def test_exact_shop_identity_ranks_first_even_without_lexical_candidates(
        self, connect, *_mocks
    ):
        from backend.search.service import merchants

        rows = [
            {
                "id": 1,
                "name": "کیف",
                "handle": "@bag_shop.ir",
                "category_code": "1",
                "city": "",
                "avatar_blob": None,
            },
            {
                "id": 2,
                "name": "دیگر",
                "handle": "@other",
                "category_code": "1",
                "city": "",
                "avatar_blob": None,
            },
        ]
        db = connect.return_value.__enter__.return_value
        db.execute.side_effect = lambda sql, params=None: (
            rows if sql.startswith("SELECT m.*") else []
        )
        self.assertEqual([1], [item.id for item in merchants(query="bagshopir")])


class ProfileFactTests(unittest.TestCase):
    def test_readers_keep_website_and_distinguish_unknown_from_unverified(self):
        embed = EmbedProfile(
            username="shop", full_name="Shop", external_url="https://shop.test", is_verified=False
        )
        self.assertFalse(embed.to_profile([]).instagram_verified)
        self.assertEqual("https://shop.test", embed.to_profile([]).website_url)
        meta = MetaProfile(name="Shop", website="https://shop.test").to_profile()
        self.assertIsNone(meta.instagram_verified)
        self.assertEqual("https://shop.test", meta.website_url)

    def test_missing_facts_do_not_erase_existing_evidence(self):
        db = Mock()
        save_account_facts(db, 1, InstagramProfile(name="Shop"))
        db.execute.assert_not_called()
        save_account_facts(
            db, 1, InstagramProfile(name="Shop", instagram_verified=False, website_url="")
        )
        self.assertEqual((False, "", "instagram_public_embed", 1), db.execute.call_args.args[1])
        self.assertIn("COALESCE", db.execute.call_args.args[0])
