import unittest

from backend.search import (
    diversify_results,
    merchant_quality_score,
    normalize_search,
    query_tokens,
    reciprocal_rank_fusion,
    term_match_strength,
)


class SearchQualityTests(unittest.TestCase):
    def test_normalizes_persian_variants_digits_and_half_spaces(self):
        self.assertEqual("کیف های 123", normalize_search("كیف‌های ۱۲۳"))

    def test_query_tokens_remove_stopwords(self):
        self.assertEqual(["کفش", "زنانه"], query_tokens("برای کفش زنانه"))

    def test_typo_matching_is_conservative(self):
        self.assertEqual(1, term_match_strength("موبایل", "فروش موبایل و تبلت"))
        self.assertGreater(term_match_strength("موبایل", "فروش مبایل و تبلت"), 0)
        self.assertEqual(0, term_match_strength("مو", "فروشگاه نمونه موبایل"))

    def test_rrf_rewards_results_found_by_multiple_retrievers(self):
        fused = reciprocal_rank_fusion({1: 1.0, 2: .8}, {2: .95, 3: .9})
        self.assertGreater(fused[2], fused[1])
        self.assertGreater(fused[2], fused[3])

    def test_quality_is_a_bounded_tie_breaker(self):
        small = merchant_quality_score({"followers_count": 100, "media_count": 2})
        established = merchant_quality_score({
            "followers_count": 500_000,
            "media_count": 2_000,
            "avatar_source_url": "https://example.com/avatar.jpg",
            "biography": "فروشگاه",
        })
        self.assertGreater(established, small)
        self.assertLess(established, 9)

    def test_browse_reranking_adds_category_diversity(self):
        items = [
            {"id": 1, "category_code": "67010000", "search_score": 8},
            {"id": 2, "category_code": "67020000", "search_score": 7.9},
            {"id": 3, "category_code": "66010000", "search_score": 7.7},
        ]
        ranked = diversify_results(items)
        self.assertEqual([1, 3, 2], [item["id"] for item in ranked])


if __name__ == "__main__":
    unittest.main()
