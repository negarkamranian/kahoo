import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from pydantic import ValidationError

from backend.models.search import BatchEnrichment, Enrichment, MerchantEnrichment
from backend.search.enrichment import enrichment_digest, save_batch_enrichment, save_llm_enrichment


def researched_enrichment(**changes):
    fields = {
        "description": "فروشگاه کتاب و لوازم تحریر با اطلاعات ثبت‌شده در معرفی فروشگاه.",
        "terms": ["کتاب", "لوازم تحریر"],
        "model": "reviewed-research",
        "source_url": "https://example.test/shop",
        "seo_title": "فروشگاه کتاب",
        "meta_description": "معرفی فروشگاه کتاب و لوازم تحریر.",
        "sources": [
            {
                "url": "https://example.test/shop",
                "kind": "website",
                "status": "reviewed",
                "note": "معرفی فروشگاه بررسی شد.",
            }
        ],
        "limitations": ["موجودی محصولات تأیید نشده است."],
    }
    return Enrichment(**{**fields, **changes})


def merchant_row(merchant_id=1, handle="@shop", enrichment=None):
    return {
        "id": merchant_id,
        "handle": handle,
        "description": enrichment.description if enrichment else "شرح قبلی",
        "description_source": "llm" if enrichment else "catalog",
        "description_source_url": enrichment.source_url if enrichment else None,
        "description_generated_by": enrichment.model if enrichment else None,
        "description_updated_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
    }


def batch_for(enrichment, *handles):
    return BatchEnrichment(
        researched_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        merchants=[MerchantEnrichment(handle=handle, enrichment=enrichment) for handle in handles],
    )


class EnrichmentModelTests(unittest.TestCase):
    def test_legacy_single_merchant_payload_remains_valid(self):
        enrichment = Enrichment(
            description=" معرفی فروشگاه کتاب ",
            terms=[" کتاب "],
            model="reviewed",
            source_url="https://example.test/shop",
        )
        self.assertEqual("معرفی فروشگاه کتاب", enrichment.description)
        self.assertEqual(["کتاب"], enrichment.terms)
        self.assertEqual([], enrichment.sources)
        self.assertEqual([], enrichment.limitations)

    def test_blank_or_unsearchable_or_unbounded_content_is_rejected(self):
        for changes in (
            {"description": " "},
            {"description": "..."},
            {"description": "a" * 6001},
            {"terms": []},
            {"terms": [" "]},
            {"terms": ["..."]},
            {"terms": ["a" * 121]},
            {"terms": ["کتاب"] * 51},
            {"seo_title": "a" * 121},
            {"meta_description": "a" * 321},
            {"confidence": 1.01},
            {"sources": [{"url": "ftp://example.test", "kind": "website", "status": "read"}]},
            {"sources": [{"url": "https://example.test", "kind": "", "status": "read"}]},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValidationError):
                researched_enrichment(**changes)

    def test_batch_requires_timezone_unique_canonical_handles_and_nonempty_list(self):
        enrichment = researched_enrichment()
        with self.assertRaises(ValidationError):
            batch_for(enrichment, "@shop", "@shop")
        with self.assertRaises(ValidationError):
            batch_for(enrichment, "@SHOP")
        with self.assertRaises(ValidationError):
            batch_for(enrichment)
        with self.assertRaises(ValidationError):
            BatchEnrichment(
                researched_at=datetime(2026, 10, 6),
                merchants=[MerchantEnrichment(handle="@shop", enrichment=enrichment)],
            )
        batch = batch_for(enrichment, "@shop")
        self.assertEqual(batch, BatchEnrichment.model_validate_json(batch.model_dump_json()))

    def test_digest_ignores_term_order_but_retains_research_changes(self):
        original = researched_enrichment()
        reordered = researched_enrichment(terms=list(reversed(original.terms)))
        changed = researched_enrichment(limitations=["اطلاعات جدید"])
        self.assertEqual(enrichment_digest(original), enrichment_digest(reordered))
        self.assertNotEqual(enrichment_digest(original), enrichment_digest(changed))


class EnrichmentServiceTests(unittest.TestCase):
    def setUp(self):
        connection = patch("backend.search.enrichment.connect")
        self.connect = connection.start()
        self.addCleanup(connection.stop)
        index = patch("backend.search.enrichment.sync_search_index")
        self.index = index.start()
        self.addCleanup(index.stop)
        self.database = self.connect.return_value.__enter__.return_value

    def configure_database(self, rows, current=None, research_dates=None):
        current = current or {}
        research_dates = research_dates or {}

        def execute(statement, parameters=None):
            cursor = Mock()
            if "FROM merchants" in statement:
                cursor.fetchone.return_value = rows[0] if rows else None
                cursor.fetchall.return_value = rows
            elif "MAX(researched_at)" in statement:
                cursor.fetchall.return_value = [
                    {"merchant_id": merchant_id, "researched_at": researched_at}
                    for merchant_id, researched_at in research_dates.items()
                ]
            elif "SELECT payload_hash" in statement:
                enrichment = current.get(parameters[0])
                cursor.fetchone.return_value = (
                    {"payload_hash": enrichment_digest(enrichment)} if enrichment else None
                )
            elif "SELECT normalized_term" in statement:
                enrichment = current[parameters[0]]
                cursor.fetchall.return_value = [
                    {
                        "term": term,
                        "normalized_term": term,
                        "source_url": enrichment.source_url,
                        "generated_by": enrichment.model,
                        "confidence": enrichment.confidence,
                        "weight": 1,
                    }
                    for term in enrichment.terms
                ]
            return cursor

        self.database.execute.side_effect = execute

    def statements(self, prefix):
        return [
            (call.args[0], call.args[1])
            for call in self.database.execute.call_args_list
            if call.args[0].lstrip().startswith(prefix)
        ]

    def test_single_shop_locks_and_saves_complete_provenance_preserving_original_fields(self):
        self.configure_database([merchant_row()])
        enrichment = researched_enrichment(terms=["کتاب", "كتاب", "کتاب"])
        self.assertTrue(save_llm_enrichment(1, enrichment))
        self.assertIn("FOR UPDATE", self.database.execute.call_args_list[0].args[0])
        update, _ = self.statements("UPDATE merchants")[0]
        self.assertNotIn("name=", update)
        self.assertNotIn("biography=", update)
        self.assertEqual(1, len(self.statements("INSERT INTO merchant_search_terms")))
        _, parameters = self.statements("INSERT INTO merchant_enrichment_history")[0]
        self.assertEqual("شرح قبلی", parameters[4])
        self.assertEqual(enrichment.model_dump(mode="json"), parameters[2].obj["enrichment"])
        self.assertEqual("@shop", parameters[2].obj["handle"])
        self.assertEqual("catalog", parameters[5].obj["description_source"])
        self.index.assert_called_once_with(self.database)

    def test_missing_single_shop_never_creates_data_or_indexes(self):
        self.configure_database([])
        with self.assertRaisesRegex(ValueError, "does not exist"):
            save_llm_enrichment(999, researched_enrichment())
        self.assertEqual([], self.statements("INSERT"))
        self.index.assert_not_called()

    def test_missing_batch_handle_fails_before_any_writes(self):
        self.configure_database([merchant_row()])
        with self.assertRaisesRegex(ValueError, "@missing"):
            save_batch_enrichment(batch_for(researched_enrichment(), "@shop", "@missing"))
        self.assertEqual([], self.statements("INSERT"))
        self.assertEqual([], self.statements("UPDATE"))
        self.index.assert_not_called()
        self.assertIs(ValueError, self.connect.return_value.__exit__.call_args.args[0])

    def test_batch_updates_all_shops_with_one_index_refresh(self):
        self.configure_database([merchant_row(), merchant_row(2, "@second")])
        result = save_batch_enrichment(batch_for(researched_enrichment(), "@shop", "@second"))
        self.assertEqual((2, 2, 0), (result.merchants, result.updated, result.unchanged))
        self.assertEqual(["@shop", "@second"], result.handles)
        self.assertEqual(2, len(self.statements("INSERT INTO merchant_enrichment_history")))
        self.index.assert_called_once_with(self.database)
        statement = self.database.execute.call_args_list[0].args[0]
        self.assertIn("ORDER BY id FOR UPDATE", statement)

    def test_stale_research_fails_the_whole_batch_before_any_writes(self):
        self.configure_database(
            [merchant_row(), merchant_row(2, "@second")],
            research_dates={2: datetime(2026, 10, 7, tzinfo=timezone.utc)},
        )
        with self.assertRaisesRegex(ValueError, "Stale research.*@second"):
            save_batch_enrichment(batch_for(researched_enrichment(), "@shop", "@second"))
        self.assertEqual([], self.statements("INSERT"))
        self.assertEqual([], self.statements("UPDATE"))
        self.index.assert_not_called()

    def test_identical_existing_batch_is_unchanged_without_duplicate_audit_or_index(self):
        enrichment = researched_enrichment()
        self.configure_database(
            [merchant_row(enrichment=enrichment)],
            current={1: enrichment},
            research_dates={1: datetime(2026, 10, 6, tzinfo=timezone.utc)},
        )
        result = save_batch_enrichment(batch_for(enrichment, "@shop"))
        self.assertEqual((1, 0, 1), (result.merchants, result.updated, result.unchanged))
        self.assertEqual([], self.statements("INSERT"))
        self.assertEqual([], self.statements("UPDATE"))
        self.assertEqual([], self.statements("DELETE"))
        self.index.assert_not_called()

    def test_mixed_batch_reports_only_changed_shops(self):
        enrichment = researched_enrichment()
        self.configure_database(
            [merchant_row(enrichment=enrichment), merchant_row(2, "@second")],
            current={1: enrichment},
        )
        result = save_batch_enrichment(batch_for(enrichment, "@shop", "@second"))
        self.assertEqual((2, 1, 1), (result.merchants, result.updated, result.unchanged))
        self.assertEqual(1, len(self.statements("INSERT INTO merchant_enrichment_history")))
        self.index.assert_called_once_with(self.database)

    def test_index_failure_propagates_through_database_transaction(self):
        self.configure_database([merchant_row()])
        self.index.side_effect = RuntimeError("index failed")
        with self.assertRaisesRegex(RuntimeError, "index failed"):
            save_batch_enrichment(batch_for(researched_enrichment(), "@shop"))
        self.assertIs(RuntimeError, self.connect.return_value.__exit__.call_args.args[0])
