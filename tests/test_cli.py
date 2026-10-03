import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from scripts.cli import main, parser


class CliTests(unittest.TestCase):
    def test_every_action_has_help_without_database_access(self):
        actions = [
            ["serve"],
            ["db", "migrate"],
            ["db", "import-sqlite"],
            ["merchants", "list"],
            ["merchants", "add"],
            ["merchants", "remove"],
            ["merchants", "import-file"],
            ["catalog", "import"],
            ["catalog", "build-categories"],
            ["media", "status"],
            ["media", "sync"],
            ["media", "cache"],
            ["search", "reindex"],
            ["search", "evaluate"],
            ["search", "enrich"],
        ]
        with patch("scripts.database.migrate") as migrate:
            for action in actions:
                with self.subTest(action=action), redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        main([*action, "--help"])
                    self.assertEqual(0, error.exception.code)
            migrate.assert_not_called()

    def test_cli_rejects_invalid_batch_sizes_and_limits(self):
        for argv in (
            ["search", "reindex", "--batch-size", "0"],
            ["media", "sync", "--limit", "-1"],
        ):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    parser().parse_args(argv)
                self.assertEqual(2, error.exception.code)

    @patch("scripts.database.migrate")
    @patch(
        "scripts.media.refresh_instagram_profiles",
        return_value=[{"updated": False, "error": "unavailable"}],
    )
    def test_sync_routes_options_and_exits_nonzero_on_partial_failure(self, refresh, migrate):
        with redirect_stdout(io.StringIO()):
            status = main(
                [
                    "media",
                    "sync",
                    "@shop",
                    "--only-missing",
                    "--limit",
                    "5",
                    "--minimum-post-images",
                    "4",
                ]
            )
        self.assertEqual(1, status)
        refresh.assert_called_once_with(["@shop"], only_missing=True, minimum_images=4, limit=5)

    @patch("scripts.database.migrate")
    @patch("scripts.media.refresh_instagram_avatars", return_value=[])
    @patch("scripts.media.refresh_instagram_profiles")
    def test_avatar_only_sync_does_not_replace_posts(self, profiles, avatars, migrate):
        with redirect_stdout(io.StringIO()):
            status = main(["media", "sync", "--avatars-only", "--only-missing", "--limit", "2"])
        self.assertEqual(0, status)
        avatars.assert_called_once_with([], only_missing=True, limit=2)
        profiles.assert_not_called()
