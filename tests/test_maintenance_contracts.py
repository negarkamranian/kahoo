import json
import unittest
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.models.categories import GpcPublication
from backend.models.merchants import Merchant
from pydantic import ValidationError

from backend.cli.catalog import build
from backend.cli.search import evaluate


class MaintenanceContractTests(unittest.TestCase):
    def category_files(self, root):
        node = {"Code": 4, "Title": "English leaf", "Level": 4, "Active": True, "Childs": []}
        for level in (3, 2, 1):
            node = {
                "Code": level,
                "Title": f"English {level}",
                "Level": level,
                "Active": True,
                "Childs": [node],
            }
        current = root / "current.json"
        current.write_text(json.dumps({"Schema": [node]}))
        translated = json.loads(current.read_text())
        item = translated["Schema"][0]
        for level in range(1, 5):
            item["Title"] = f"ترجمه {level}"
            if item["Childs"]:
                item = item["Childs"][0]
        persian = root / "persian.json"
        persian.write_text(json.dumps(translated))
        policy = root / "policy.json"
        policy.write_text(
            json.dumps(
                {
                    "source": "Test",
                    "source_publication_id": 1,
                    "persian_publication_id": 2,
                    "allowed_segments": ["1"],
                    "excluded_terms": [],
                    "segment_labels_fa": {"1": "عنوان ریشه"},
                    "segment_excluded_terms": {},
                }
            )
        )
        return Namespace(
            current=current, persian=persian, policy=policy, output=root / "out.sql", download=False
        )

    def test_category_labels_use_the_declared_translation_map(self):
        with TemporaryDirectory() as directory:
            args = self.category_files(Path(directory))
            result = build(args)
            output = args.output.read_text()
            self.assertEqual(4, result.categories)
            self.assertIn("عنوان ریشه", output)
            self.assertIn("ترجمه ۴", output)
            self.assertNotIn("english_fallback_count", output)

    def test_missing_translation_does_not_overwrite_an_existing_seed(self):
        with TemporaryDirectory() as directory:
            args = self.category_files(Path(directory))
            args.persian.write_text('{"Schema": []}')
            args.output.write_text("existing seed")
            with self.assertRaisesRegex(ValueError, "Missing Persian category label"):
                build(args)
            self.assertEqual("existing seed", args.output.read_text())

    def test_malformed_gpc_nodes_are_not_treated_as_inactive_or_empty(self):
        for node in (
            {"Code": 1, "Title": "Category", "Active": True},
            {"Code": 1, "Title": "Category", "Level": 1},
            {"Code": 1, "Title": "Category", "Level": 1, "Active": True, "Childs": None},
        ):
            with self.subTest(node=node), self.assertRaises(ValidationError):
                GpcPublication.model_validate({"Schema": [node]})

    @patch("backend.cli.search.merchants")
    def test_evaluation_uses_canonical_graded_relevance(self, merchants):
        merchants.return_value = [
            Merchant(id=1, name="Shop", handle="@shop", category_code="1", city="Tehran")
        ]
        with TemporaryDirectory() as directory:
            benchmark = Path(directory) / "benchmark.json"
            benchmark.write_text(
                json.dumps({"queries": [{"query": "shop", "relevance": {"@shop": 3}}]})
            )
            report = evaluate(Namespace(benchmark=benchmark))
        self.assertEqual(1, report.success_at_5)
        self.assertEqual(1, report.ndcg_at_10)
        self.assertEqual(["@shop"], report.results[0].top_10)
