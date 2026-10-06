import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from backend.cli.search import enrich, enrich_file
from backend.models.search import BatchEnrichment


class EnrichmentCliTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "research.json"
        self.enrichment = {
            "description": "فروشگاه نوشت‌افزار و دفتر برنامه‌ریزی",
            "terms": ["نوشت افزار", "دفتر برنامه ریزی"],
            "model": "test-research",
            "source_url": "https://example.test/shop/",
        }

    @patch("backend.cli.search.save_llm_enrichment", return_value=False)
    def test_single_import_reports_unchanged_from_service(self, save):
        self.source.write_text(json.dumps(self.enrichment), encoding="utf-8")
        result = enrich(SimpleNamespace(source=self.source, merchant_id=7))
        self.assertFalse(result.updated)
        self.assertEqual(7, save.call_args.args[0])

    @patch("backend.cli.search.save_batch_enrichment")
    def test_batch_import_validates_handles_before_calling_persistence(self, save):
        payload = {
            "researched_at": "2026-10-06T10:00:00Z",
            "merchants": [{"handle": "@shop", "enrichment": self.enrichment}],
        }
        self.source.write_text(json.dumps(payload), encoding="utf-8")
        enrich_file(SimpleNamespace(source=self.source))
        batch = save.call_args.args[0]
        self.assertIsInstance(batch, BatchEnrichment)
        self.assertEqual("@shop", batch.merchants[0].handle)
        save.reset_mock()
        payload["merchants"].append(payload["merchants"][0])
        self.source.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(ValidationError):
            enrich_file(SimpleNamespace(source=self.source))
        save.assert_not_called()
