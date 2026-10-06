import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, call, patch

from backend.database import (
    MAINTENANCE_LOCK_ID,
    initialize_database,
    run_category_seed,
    run_migrations,
)


class DatabaseMigrationTests(unittest.TestCase):
    def migration_files(self, root):
        migrations = root / "db" / "migrations"
        migrations.mkdir(parents=True)
        (migrations / "002_second.sql").write_text("SECOND MIGRATION;")
        (migrations / "001_first.sql").write_text("FIRST MIGRATION;")
        (root / "data").mkdir()
        seed = root / "data" / "categories.sql"
        seed.write_text("BEGIN;\nCATEGORY SEED;\nCOMMIT;\n")
        return migrations, seed

    def database(self, connect, applied=()):
        database = MagicMock()
        connect.return_value.__enter__.return_value = database
        database.execute.side_effect = lambda sql, params=None: (
            [{"version": version} for version in applied]
            if sql == "SELECT version FROM schema_migrations"
            else []
        )
        return database

    @patch("backend.database.connect")
    def test_initialize_serializes_schema_and_seed_in_one_transaction(self, connect):
        database = self.database(connect)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            migrations, _ = self.migration_files(root)
            with (
                patch("backend.database.PROJECT_ROOT", root),
                patch("backend.database.MIGRATIONS_ROOT", migrations),
            ):
                self.assertEqual(
                    {"migrated": True, "categories_seeded": True}, initialize_database()
                )
        connect.assert_called_once_with()
        database.transaction.assert_called_once_with()
        statements = database.execute.call_args_list
        self.assertEqual(
            call("SELECT pg_advisory_xact_lock(%s)", (MAINTENANCE_LOCK_ID,)), statements[0]
        )
        self.assertEqual(
            [
                call("FIRST MIGRATION;"),
                call("INSERT INTO schema_migrations(version) VALUES(%s)", ("001_first.sql",)),
                call("SECOND MIGRATION;"),
                call("INSERT INTO schema_migrations(version) VALUES(%s)", ("002_second.sql",)),
                call("\nCATEGORY SEED;\n"),
            ],
            statements[3:],
        )
        database.transaction.return_value.__exit__.assert_called_once_with(None, None, None)

    @patch("backend.database.connect")
    def test_migrate_skips_committed_versions_after_acquiring_lock(self, connect):
        database = self.database(connect, applied=("001_first.sql",))
        with TemporaryDirectory() as directory:
            migrations, _ = self.migration_files(Path(directory))
            with patch("backend.database.MIGRATIONS_ROOT", migrations):
                run_migrations()
        self.assertEqual(
            call("SELECT pg_advisory_xact_lock(%s)", (MAINTENANCE_LOCK_ID,)),
            database.execute.call_args_list[0],
        )
        self.assertNotIn(call("FIRST MIGRATION;"), database.execute.call_args_list)
        self.assertIn(call("SECOND MIGRATION;"), database.execute.call_args_list)

    @patch("backend.database.connect")
    def test_seed_failure_rolls_back_schema_and_seed_together(self, connect):
        database = self.database(connect)
        failure = RuntimeError("seed failed")

        def execute(sql, params=None):
            if "CATEGORY SEED;" in sql:
                raise failure
            return []

        database.execute.side_effect = execute
        with TemporaryDirectory() as directory:
            root = Path(directory)
            migrations, _ = self.migration_files(root)
            with (
                patch("backend.database.PROJECT_ROOT", root),
                patch("backend.database.MIGRATIONS_ROOT", migrations),
                self.assertRaisesRegex(RuntimeError, "seed failed"),
            ):
                initialize_database()
        transaction_exit = database.transaction.return_value.__exit__
        self.assertIs(RuntimeError, transaction_exit.call_args.args[0])
        self.assertIs(failure, transaction_exit.call_args.args[1])

    @patch("backend.database.connect")
    def test_standalone_category_seed_uses_the_same_maintenance_lock(self, connect):
        database = self.database(connect)
        with TemporaryDirectory() as directory:
            _, seed = self.migration_files(Path(directory))
            self.assertTrue(run_category_seed(seed))
        self.assertEqual(
            [
                call("SELECT pg_advisory_xact_lock(%s)", (MAINTENANCE_LOCK_ID,)),
                call("\nCATEGORY SEED;\n"),
            ],
            database.execute.call_args_list,
        )
