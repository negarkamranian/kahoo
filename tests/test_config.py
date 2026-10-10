import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dotenv import dotenv_values

from backend.config import PROJECT_ROOT, Settings, load_environment, settings


class ConfigTests(unittest.TestCase):
    def test_all_defaults_come_from_example_without_a_local_env_file(self):
        example = (PROJECT_ROOT / ".env.example").read_text()
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text(example)
            with patch("backend.config.PROJECT_ROOT", root), patch.dict(os.environ, {}, clear=True):
                load_environment()
                self.assertEqual(dict(dotenv_values(root / ".env.example")), dict(os.environ))

    def test_local_and_process_settings_override_example_defaults(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text("FIRST=example\nSECOND=example\nTHIRD=example\n")
            (root / ".env").write_text("FIRST=local\nSECOND=\n")
            with (
                patch("backend.config.PROJECT_ROOT", root),
                patch.dict(os.environ, {"FIRST": "process"}, clear=True),
            ):
                load_environment()
                self.assertEqual(
                    {"FIRST": "process", "SECOND": "", "THIRD": "example"}, dict(os.environ)
                )

    def test_missing_configuration_is_not_replaced_by_an_inline_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(KeyError):
                Settings.from_environment()

    def test_configuration_is_loaded_once_and_port_is_an_integer(self):
        self.assertIsInstance(settings.port, int)
        original = settings.host
        with patch.dict(os.environ, {"KAHOO_HOST": "changed-after-startup"}):
            self.assertEqual(original, settings.host)

    def test_secrets_are_omitted_from_configuration_repr(self):
        credentials = {
            "database_url": "secret-db",
            "admin_token": "secret-admin",
            "meta_access_token": "secret-meta",
            "embedding_api_key": "secret-embedding",
            "product_vision_api_key": "secret-vision",
        }
        configured = Settings.model_validate({**settings.model_dump(), **credentials})
        for field, secret in credentials.items():
            self.assertNotIn(secret, repr(configured))
            self.assertEqual(secret, getattr(configured, field))
            self.assertIsInstance(getattr(configured, field), str)
