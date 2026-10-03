import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from backend.cli import main, parser


class CliTests(unittest.TestCase):
    @patch("backend.cli.initialize_database", return_value={"migrated": True})
    def test_migrate_initializes_database_once_and_reports_result(self, initialize):
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["db", "migrate"])
        self.assertEqual(0, status)
        initialize.assert_called_once_with()
        self.assertEqual({"migrated": True}, json.loads(output.getvalue()))

    @patch.multiple("backend.cli.settings", host="localhost", port=4174)
    @patch("backend.server.app.ThreadingHTTPServer")
    @patch("backend.server.app.initialize_database")
    @patch("backend.cli.initialize_database")
    def test_serve_owns_database_setup_and_respects_address_options(
        self, cli_initialize, server_initialize, server
    ):
        for options, address in (
            ([], ("localhost", 4174)),
            (["--host", "127.0.0.1", "--port", "4175"], ("127.0.0.1", 4175)),
        ):
            with self.subTest(options=options), redirect_stdout(io.StringIO()):
                server.reset_mock()
                server_initialize.reset_mock()
                server.side_effect = lambda *args: (
                    server_initialize.assert_called_once_with() or server.return_value
                )
                self.assertEqual(0, main(["serve", *options]))
                self.assertEqual(address, server.call_args.args[0])
                server.return_value.__enter__.return_value.serve_forever.assert_called_once_with()
        cli_initialize.assert_not_called()

    def test_every_action_has_help_without_database_access(self):
        actions = [
            ["serve"],
            ["db", "migrate"],
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
        with patch("backend.cli.initialize_database") as migrate:
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
            ["merchants", "list", "--limit", "101"],
            ["merchants", "list", "--offset", "-1"],
            ["merchants", "add", "@shop", "--name", "Manual"],
            ["merchants", "add", "@shop", "--description", "Manual"],
        ):
            with self.subTest(argv=argv), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    parser().parse_args(argv)
                self.assertEqual(2, error.exception.code)

    @patch("backend.cli.initialize_database")
    @patch(
        "backend.cli.media.refresh_instagram_profiles",
        side_effect=OSError("unavailable"),
    )
    def test_sync_routes_options_and_propagates_failures(self, refresh, migrate):
        with redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(OSError, "unavailable"):
                main(
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
        refresh.assert_called_once_with(["@shop"], only_missing=True, minimum_images=4, limit=5)

    @patch("backend.cli.initialize_database")
    @patch("backend.cli.media.refresh_instagram_avatars", return_value=[])
    @patch("backend.cli.media.refresh_instagram_profiles")
    def test_avatar_only_sync_does_not_replace_posts(self, profiles, avatars, migrate):
        with redirect_stdout(io.StringIO()):
            status = main(["media", "sync", "--avatars-only", "--only-missing", "--limit", "2"])
        self.assertEqual(0, status)
        avatars.assert_called_once_with([], only_missing=True, limit=2)
        profiles.assert_not_called()
