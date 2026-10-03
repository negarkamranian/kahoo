import unittest
from unittest.mock import Mock, patch

from backend.search import (
    diversify_results,
    embed_texts,
    merchant_quality_score,
    ndcg_at_k,
    normalize_search,
    phrase_proximity_bonus,
    query_coverage,
    query_tokens,
    reciprocal_rank_fusion,
    term_match_strength,
)


class SearchQualityTests(unittest.TestCase):
    @patch.dict("os.environ", {"EMBEDDING_API_URL": "https://example.test/embeddings"})
    @patch("backend.search.urlopen")
    def test_incomplete_embedding_response_is_rejected(self, urlopen):
        urlopen.return_value.__enter__.return_value = Mock(
            read=lambda: '{"data": [{"index": 0, "embedding": [0]}]}'
        )
        with self.assertRaisesRegex(ValueError, "one vector per input"):
            embed_texts(["first", "second"])

    def test_normalizes_persian_variants_digits_and_half_spaces(self):
        self.assertEqual("کیف های 123", normalize_search("كیف‌های ۱۲۳"))

    def test_query_tokens_remove_stopwords(self):
        self.assertEqual(["کفش", "زنانه"], query_tokens("برای کفش زنانه"))

    def test_typo_matching_is_conservative(self):
        self.assertEqual(1, term_match_strength("موبایل", "فروش موبایل و تبلت"))
        self.assertGreater(term_match_strength("موبایل", "فروش مبایل و تبلت"), 0)
        self.assertEqual(0, term_match_strength("مو", "فروشگاه نمونه موبایل"))

    def test_rrf_rewards_results_found_by_multiple_retrievers(self):
        fused = reciprocal_rank_fusion({1: 1.0, 2: 0.8}, {2: 0.95, 3: 0.9})
        self.assertGreater(fused[2], fused[1])
        self.assertGreater(fused[2], fused[3])

    def test_quality_is_a_bounded_tie_breaker(self):
        small = merchant_quality_score({"followers_count": 100, "media_count": 2})
        established = merchant_quality_score(
            {
                "followers_count": 500_000,
                "media_count": 2_000,
                "avatar_source_url": "https://example.com/avatar.jpg",
                "biography": "فروشگاه",
            }
        )
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

    def test_query_coverage_requires_distinct_query_concepts(self):
        tokens = query_tokens("کفش زنانه چرمی")
        self.assertEqual(1, query_coverage(tokens, "فروش کفش زنانه چرمی"))
        self.assertAlmostEqual(1 / 3, query_coverage(tokens, "فروشگاه کفش"))

    def test_phrase_proximity_rewards_exact_and_ordered_matches(self):
        exact = phrase_proximity_bonus("کفش زنانه", "خرید کفش زنانه چرمی")
        spread = phrase_proximity_bonus("کفش زنانه", "کفش چرمی بسیار راحت زنانه")
        reversed_order = phrase_proximity_bonus("کفش زنانه", "زنانه کفش")
        self.assertGreater(exact, spread)
        self.assertGreater(spread, reversed_order)

    def test_ndcg_rewards_relevant_results_near_the_top(self):
        self.assertGreater(ndcg_at_k([2, 1, 0]), ndcg_at_k([0, 1, 2]))
        self.assertEqual(1, ndcg_at_k([2, 1, 0]))


if __name__ == "__main__":
    unittest.main()
