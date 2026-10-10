"""Regression coverage for precise retrieval and bounded model reranking."""

import json
import unittest
from unittest.mock import Mock, patch

from backend.models.merchants import Merchant
from backend.models.search import LexicalMatch, SearchEvidence, TextMatch
from backend.search.embeddings import embed_query, embed_texts, semantic_merchant_scores
from backend.search.normalization import query_tokens
from backend.search.ranking import match_content
from backend.search.reranking import rerank_merchants
from backend.search.retrieval import lexical_merchant_matches
from backend.search.service import merchant_rows, relevant_match


def shop(identifier=1, description=""):
    return Merchant(
        id=identifier,
        name="نمونه",
        handle=f"@shop{identifier}",
        category_code="1",
        description=description,
        city="",
    )


class SearchPrecisionTests(unittest.TestCase):
    def test_partial_document_does_not_bypass_whole_query(self):
        evidence = SearchEvidence(
            text=TextMatch(score=20, coverage=0.5, matched_tokens=1),
            lexical=LexicalMatch(entity_type="merchant", entity_id=1, score=2, coverage=0.5),
            semantic=0,
        )
        self.assertFalse(relevant_match(evidence, ["کفش", "زنانه"]))
        evidence.lexical.coverage = 1
        evidence.lexical.coherent = True
        self.assertTrue(relevant_match(evidence, ["کفش", "زنانه"]))

    def test_generated_repetition_cannot_inflate_product_score(self):
        merchant = shop(description="کفش زنانه")
        tokens = query_tokens("کفش زنانه")
        original = match_content(merchant, [], [], "کفش زنانه", tokens)
        merchant.biography = merchant.description
        repeated = match_content(merchant, ["کفش زنانه"], [("کفش زنانه", 1)], "کفش زنانه", tokens)
        self.assertEqual(original.score, repeated.score)

    def test_specific_attribute_must_be_present(self):
        merchant = shop(description="کفش زنانه")
        tokens = query_tokens("کفش زنانه چرمی")
        match = match_content(merchant, [], [], "کفش زنانه چرمی", tokens)
        self.assertFalse(
            relevant_match(SearchEvidence(text=match, lexical=None, semantic=0), tokens)
        )
        merchant.description += " چرمی"
        complete = match_content(merchant, [], [], "کفش زنانه چرمی", tokens)
        self.assertTrue(
            relevant_match(SearchEvidence(text=complete, lexical=None, semantic=0), tokens)
        )

    def test_unrelated_products_do_not_match_as_a_single_product(self):
        merchant = shop(description="ماگ طرح گربه با درپوش و قاشق؛ ظرف غذای محفظه‌دار")
        tokens = query_tokens("غذای گربه")
        match = match_content(
            merchant, [], [("ماگ طرح گربه", 1), ("ظرف غذا", 1)], "غذای گربه", tokens
        )
        self.assertFalse(
            relevant_match(SearchEvidence(text=match, lexical=None, semantic=0), tokens)
        )
        merchant.description = "غذای خشک گربه"
        match = match_content(merchant, [], [], "غذای گربه", tokens)
        self.assertTrue(
            relevant_match(SearchEvidence(text=match, lexical=None, semantic=0), tokens)
        )

    def test_query_repetition_does_not_create_extra_concepts(self):
        self.assertEqual(["کفش", "زنانه"], query_tokens("کفش کفش زنانه"))

    def test_category_union_is_parameterized_and_uses_descendants(self):
        db = Mock()
        merchant_rows(db, ["67000000", "73000000"])
        sql, params = db.execute.call_args.args
        self.assertIn("WITH RECURSIVE", sql)
        self.assertIn("SELECT unnest", sql)
        self.assertEqual([["67000000", "73000000"]], params)
        merchant_rows(db, "67000000")
        self.assertEqual([["67000000"]], db.execute.call_args.args[1])

    def test_lexical_filter_applies_before_candidate_limit(self):
        db = Mock()
        db.execute.return_value = []
        lexical_merchant_matches(db, "کفش زنانه", merchant_ids=[7, 9])
        sql, params = db.execute.call_args.args
        self.assertEqual([7, 9], params["merchant_ids"])
        self.assertLess(sql.index("merchant_id=ANY"), sql.index("LIMIT"))
        self.assertIn("ORDER BY coverage DESC,score DESC", sql)

    @patch.multiple(
        "backend.search.embeddings.settings",
        embedding_api_url="http://local",
        embedding_model="intfloat/multilingual-e5-large",
    )
    @patch("backend.search.embeddings.embed_query", return_value=[0.1] * 1024)
    def test_vectors_are_filtered_by_active_model_and_selected_shops(self, embed):
        db = Mock()
        db.execute.return_value = [{"merchant_id": 7, "score": 0.9}]
        self.assertEqual({7: 0.9}, semantic_merchant_scores(db, "کفش", merchant_ids=[7]))
        sql, params = db.execute.call_args.args
        self.assertIn("embedding_model=%s", sql)
        self.assertEqual("intfloat/multilingual-e5-large", params[1])
        self.assertEqual(([7], [7]), params[2:4])

    @patch.multiple(
        "backend.search.embeddings.settings",
        embedding_api_url="http://local/embeddings",
        embedding_model="intfloat/multilingual-e5-large",
    )
    @patch("backend.search.embeddings.urlopen")
    def test_e5_uses_query_and_passage_prefixes(self, urlopen):
        urlopen.return_value.__enter__.return_value = Mock(
            read=lambda: json.dumps({"data": [{"index": 0, "embedding": [0.1] * 1024}]}),
        )
        embed_texts(["کفش"])
        self.assertEqual(["passage: کفش"], json.loads(urlopen.call_args.args[0].data)["input"])
        embed_query.cache_clear()
        self.addCleanup(embed_query.cache_clear)
        embed_query("کفش")
        self.assertEqual(["query: کفش"], json.loads(urlopen.call_args.args[0].data)["input"])

    @patch.multiple(
        "backend.search.reranking.settings",
        rerank_api_url="http://local/rerank",
        rerank_min_score=0.2,
    )
    @patch("backend.search.reranking.urlopen")
    def test_cross_encoder_reorders_and_removes_irrelevant_candidates(self, urlopen):
        urlopen.return_value.__enter__.return_value = Mock(
            read=lambda: json.dumps(
                [
                    {"index": 0, "score": 0.1},
                    {"index": 1, "score": 0.95},
                    {"index": 2, "score": 0.7},
                ]
            ),
        )
        results = rerank_merchants("کفش", [shop(1), shop(2), shop(3)])
        self.assertEqual([2, 3], [item.id for item in results])
        self.assertEqual(95, results[0].search_score)

    @patch.multiple("backend.search.reranking.settings", rerank_api_url="http://local/rerank")
    @patch("backend.search.reranking.urlopen")
    def test_invalid_model_responses_and_outages_are_not_hidden(self, urlopen):
        for response in ([{"index": 0, "score": 0.5}] * 2, [{"index": 9, "score": 0.5}]):
            urlopen.return_value.__enter__.return_value = Mock(
                read=lambda response=response: json.dumps(response)
            )
            with self.assertRaisesRegex(ValueError, "one score for every candidate"):
                rerank_merchants("کفش", [shop(1), shop(2)])
        urlopen.side_effect = OSError("model unavailable")
        with self.assertRaisesRegex(OSError, "model unavailable"):
            rerank_merchants("کفش", [shop()])
