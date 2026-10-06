"""Behavioral coverage for ordered explanations and autocomplete ranking."""

import unittest
from unittest.mock import patch

from backend.models.search import LexicalMatch
from backend.search.ranking import TextMatch
from backend.search.service import SearchEvidence, match_quality, match_reason, relevant_match
from backend.search.suggestions import search_suggestions


class SearchRuleTests(unittest.TestCase):
    def test_explanations_keep_priority_when_signals_overlap(self):
        post = LexicalMatch(entity_type="post", entity_id=7, score=1)
        cases = [
            ({"name", "category"}, post, "نام فروشگاه"),
            ({"category"}, post, "محصول یا پست مرتبط"),
            ({"category", "description"}, None, "دسته‌بندی مرتبط"),
            ({"metadata", "biography"}, None, "محصولات مرتبط"),
            ({"biography", "city"}, None, "بیوی فروشگاه"),
            ({"city"}, None, "موقعیت فروشگاه"),
            (set(), None, "نتیجه معنایی نزدیک"),
        ]
        for fields, lexical, reason in cases:
            with self.subTest(fields=fields, lexical=lexical):
                evidence = SearchEvidence(
                    text=TextMatch(fields=fields), lexical=lexical, semantic=0.8
                )
                self.assertEqual(reason, match_reason(evidence))
        self.assertEqual(
            "عبارت مشابه", match_reason(SearchEvidence(text=TextMatch(), lexical=None, semantic=0))
        )

    def test_weak_text_requires_document_or_semantic_evidence(self):
        text = TextMatch(score=2, matched_tokens=1, fuzzy=True)
        weak = SearchEvidence(text=text, lexical=None, semantic=0)
        self.assertFalse(relevant_match(weak, ["کفش", "زنانه", "چرمی"]))
        strong = SearchEvidence(text=text, lexical=None, semantic=0.8)
        self.assertTrue(relevant_match(strong, ["کفش", "زنانه", "چرمی"]))
        self.assertEqual("near", match_quality(strong))
        self.assertFalse(relevant_match(strong, []))
        text.fields.add("name")
        self.assertEqual("exact", match_quality(strong))

    @patch("backend.search.suggestions.connect")
    def test_autocomplete_prefers_specific_matches_and_deduplicates_normalized_text(self, connect):
        def execute(sql, _params=None):
            if "SELECT name,handle" in sql:
                return [
                    {"name": "کیف", "handle": "@exact"},
                    {"name": "كیف", "handle": "@duplicate"},
                    {"name": "کیف چرمی", "handle": "@prefix"},
                    {"name": "فروش کیف چرمی", "handle": "@word"},
                    {"name": "پارچه", "handle": "@unrelated"},
                ]
            return []

        connect.return_value.__enter__.return_value.execute.side_effect = execute
        results = search_suggestions("کیف")
        self.assertEqual(["کیف", "کیف چرمی", "فروش کیف چرمی"], [item.value for item in results])
        self.assertEqual(["کیف"], [item.value for item in search_suggestions("کیف", limit=1)])
